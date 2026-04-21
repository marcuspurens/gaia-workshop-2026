"""Metamodel-valid candidate subgraph extraction.

Given a `TraceGraph` and a `QuestionPolicy`, this module walks the graph
under the policy's relation whitelist (mirroring SystemWeaver's
`SidsToFollow` pattern), produces a bounded subgraph, finds a shortest
root-anchored path per target, and emits the packet shape that downstream
stages consume.
"""
from __future__ import annotations
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from .graph import TraceGraph, brief
from .metamodel import Metamodel
from .planner import QuestionPolicy


def _neighbors_policy(graph: TraceGraph, node_id: str, policy: QuestionPolicy):
    for e in graph.out_edges.get(node_id, []):
        if policy.relation_allowed(e.get("relation_sid", "")):
            yield e, e["to"]
    for e in graph.in_edges.get(node_id, []):
        if policy.relation_allowed(e.get("relation_sid", "")):
            yield e, e["from"]


def _reachability_policy(graph: TraceGraph, root_id: str, policy: QuestionPolicy) -> Tuple[Dict[str, int], bool]:
    """Whitelist-constrained reachability search from root.

    Mirrors SystemWeaver's SidsToFollow traversal: walks edges whose
    relation_sid is allowed (empty whitelist = any), bidirectional,
    admits only nodes whose item_type is in scope. Stops naturally when
    the whitelist runs out of frontier nodes, or abruptly when the
    max_nodes guard rail trips.

    Returns (visited, guard_rail_tripped). `visited` maps node_id to hop
    distance from root (useful for stable ordering of output). There is
    no hop budget — reach is what the chosen whitelist permits.
    `guard_rail_tripped` is True iff the traversal hit policy.max_nodes
    before the whitelist was exhausted; callers surface that as a
    warning so the engineer knows the subgraph is truncated.
    """
    visited = {root_id: 0}
    q = deque([root_id])
    in_scope = policy.in_scope_item_types
    guard_rail_tripped = False
    while q:
        if len(visited) >= policy.max_nodes:
            guard_rail_tripped = True
            break
        current = q.popleft()
        hop = visited[current]
        for _, nxt in _neighbors_policy(graph, current, policy):
            if nxt in visited:
                continue
            node = graph.id2node.get(nxt)
            if node is None:
                continue
            if in_scope and node.get("item_type") not in in_scope:
                continue
            if len(visited) >= policy.max_nodes:
                guard_rail_tripped = True
                break
            visited[nxt] = hop + 1
            q.append(nxt)
        if guard_rail_tripped:
            break
    return visited, guard_rail_tripped


# Back-compat alias: the old name was _bfs_policy before the whitelist refactor.
# Keep the alias so any external caller/notebook holding the old name doesn't
# break; preferred name is _reachability_policy.
_bfs_policy = _reachability_policy


def _shortest_path_within(graph: TraceGraph, root_id: str, target_id: str, allowed_nodes: Set[str], policy: QuestionPolicy) -> Optional[List[str]]:
    if root_id == target_id:
        return [root_id]
    q = deque([root_id])
    parent: Dict[str, Optional[str]] = {root_id: None}
    while q:
        cur = q.popleft()
        if cur == target_id:
            break
        for _, nxt in _neighbors_policy(graph, cur, policy):
            if nxt not in allowed_nodes or nxt in parent:
                continue
            parent[nxt] = cur
            q.append(nxt)
    if target_id not in parent:
        return None
    path: List[str] = []
    cur: Optional[str] = target_id
    while cur is not None:
        path.append(cur)
        cur = parent[cur]
    return list(reversed(path))


def _path_edges(graph: TraceGraph, node_path: List[str], policy: QuestionPolicy) -> List[Dict[str, Any]]:
    # Given a node-id path (from _shortest_path_within), return the concrete
    # edges connecting each consecutive pair. Checks both directions because
    # the reachability search is bidirectional but the underlying edges are
    # stored directed. If a link cannot be resolved under the policy's allowed
    # relations, it is skipped silently — callers can detect this by comparing
    # len(returned_edges) to len(node_path) - 1. In the normal case this never
    # happens because the node path was built only from allowed neighbours.
    edges: List[Dict[str, Any]] = []
    for a, b in zip(node_path[:-1], node_path[1:]):
        found = None
        for e in graph.out_edges.get(a, []):
            if e["to"] == b and policy.relation_allowed(e.get("relation_sid", "")):
                found = e
                break
        if not found:
            for e in graph.in_edges.get(a, []):
                if e["from"] == b and policy.relation_allowed(e.get("relation_sid", "")):
                    found = e
                    break
        if found:
            edges.append(found)
    return edges


def extract_candidate_subgraph(graph: TraceGraph, metamodel: Metamodel, policy: QuestionPolicy) -> Dict[str, Any]:
    visited, guard_rail_tripped = _reachability_policy(graph, root_id=policy.root_id, policy=policy)
    allowed_nodes = set(visited.keys())

    # Target nodes among reachable = what the question is asking about.
    # Root is excluded because a root->root path is trivial.
    target_ids = [
        nid for nid in allowed_nodes
        if nid != policy.root_id and graph.id2node[nid].get("item_type") in policy.target_item_types
    ]

    candidate_node_ids: Set[str] = {policy.root_id}
    candidate_edges: List[Dict[str, Any]] = []
    candidate_paths: List[List[Dict[str, Any]]] = []
    reached_target_ids: Set[str] = set()
    unreached_target_ids: List[str] = []

    # Step 2: one root-anchored path per target. Paths use only whitelisted
    # relations, so the LLM sees a real trace chain it can cite back.
    for tid in target_ids:
        path = _shortest_path_within(graph, policy.root_id, tid, allowed_nodes, policy)
        if not path:
            unreached_target_ids.append(tid)
            continue
        reached_target_ids.add(tid)
        candidate_paths.append([brief(graph.id2node[nid], include_text=False) for nid in path])
        candidate_node_ids.update(path)
        candidate_edges.extend(_path_edges(graph, path, policy))

    # Step 3: one-hop support expansion. Adds structural context nodes (groups,
    # specs, trace items) adjacent to path nodes so the packet shows the
    # container each path node lives in, without ballooning the subgraph.
    support_node_ids: Set[str] = set(candidate_node_ids)
    for nid in list(candidate_node_ids):
        for e, nxt in _neighbors_policy(graph, nid, policy):
            node = graph.id2node.get(nxt)
            if node and node.get("item_type") in policy.support_item_types:
                support_node_ids.add(nxt)
                candidate_edges.append(e)

    # Step 4: dedup + max_edges guard rail. The cap is checked before append,
    # so the hard limit is never exceeded. Edges whose endpoints did not make
    # it into support_node_ids are dropped — their partner node isn't in the
    # packet, so showing the edge would be misleading.
    dedup_edges: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, str, str]] = set()
    for e in candidate_edges:
        if len(dedup_edges) >= policy.max_edges:
            break
        key = (e["from"], e["to"], e.get("relation_sid", ""), e.get("relation_name", ""))
        if key in seen:
            continue
        if e["from"] not in support_node_ids or e["to"] not in support_node_ids:
            continue
        seen.add(key)
        dedup_edges.append(e)

    nodes_out: List[Dict[str, Any]] = []
    for nid in sorted(support_node_ids, key=lambda x: (visited.get(x, 999), x)):
        node = dict(brief(graph.id2node[nid], include_text=True))
        node["hop"] = visited.get(nid)
        nodes_out.append(node)

    edges_out: List[Dict[str, Any]] = [
        {
            "from": e["from"],
            "to": e["to"],
            "relation_sid": e.get("relation_sid", ""),
            "relation_name": e.get("relation_name", ""),
        }
        for e in dedup_edges
    ]

    warnings: List[Dict[str, Any]] = []
    node_item_types = {n["type"] for n in nodes_out}
    unknown_types = sorted(t for t in node_item_types if t and t not in metamodel.vocabulary_item_types)
    if unknown_types:
        warnings.append({"kind": "unknown_item_types", "values": unknown_types})

    edge_sids = {e["relation_sid"] for e in edges_out if e["relation_sid"]}
    unknown_sids = sorted(s for s in edge_sids if s not in metamodel.vocabulary_relation_sids)
    if unknown_sids:
        warnings.append({"kind": "unknown_relation_sids", "values": unknown_sids})

    # Edge-schema check: does each edge fit the (from_type, sid, to_type)
    # pattern the metamodel declares? Data-drift signal.
    schema_violations: List[Dict[str, Any]] = []
    for e in edges_out:
        sid = e.get("relation_sid", "")
        if not sid:
            continue
        ft = (graph.id2node.get(e["from"], {}) or {}).get("item_type", "")
        tt = (graph.id2node.get(e["to"], {}) or {}).get("item_type", "")
        if metamodel.edge_schema_violation(ft, sid, tt):
            schema_violations.append({
                "from_type": ft, "sid": sid, "to_type": tt,
                "from": e["from"], "to": e["to"],
            })
    if schema_violations:
        warnings.append({
            "kind": "edge_schema_violation",
            "count": len(schema_violations),
            "examples": schema_violations[:5],
        })

    if guard_rail_tripped:
        warnings.append({
            "kind": "max_nodes_guard_rail_tripped",
            "note": (
                f"Extraction stopped at max_nodes={policy.max_nodes} before the relation "
                f"whitelist was exhausted. Expected answer ids could be outside the "
                f"extracted subgraph. Consider raising defaults.max_nodes in the metamodel."
            ),
        })

    missing_target_types = sorted(policy.target_item_types - {graph.id2node[t]["item_type"] for t in reached_target_ids})
    if missing_target_types and policy.target_item_types:
        warnings.append({"kind": "target_item_types_not_reached", "values": missing_target_types})

    if unreached_target_ids:
        warnings.append({
            "kind": "targets_visible_but_not_root_anchored",
            "count": len(unreached_target_ids),
            "ids": unreached_target_ids[:10],
        })

    name_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for n in nodes_out:
        name_groups[(n["name"] or "").strip()].append(n)
    name_duplicates = [
        {"name": name, "variants": [{"id": n["id"], "version": n["version"], "status": n["status"]} for n in group]}
        for name, group in name_groups.items() if len(group) > 1
    ]
    if name_duplicates:
        warnings.append({"kind": "duplicate_names_in_subgraph", "values": name_duplicates[:10]})

    return {
        "root_id": policy.root_id,
        "nodes": nodes_out,
        "edges": edges_out,
        "candidate_paths": candidate_paths[:40],
        "warnings": warnings,
        "packet_metadata": {
            "node_count": len(nodes_out),
            "edge_count": len(edges_out),
            "max_nodes": policy.max_nodes,
            "max_edges": policy.max_edges,
            "target_types": sorted(policy.target_item_types),
            "support_types": sorted(policy.support_item_types),
            "allowed_relation_sids": sorted(policy.allowed_relation_sids),
            "candidate_path_count": len(candidate_paths),
            "reached_target_count": len(reached_target_ids),
            "unreached_target_count": len(unreached_target_ids),
        },
    }
