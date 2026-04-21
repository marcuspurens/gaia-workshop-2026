"""Grounding check + auto-demotion.

Beyond the basic hallucination check, the validator performs a
ROOT-ANCHOR CHAIN check for every entry in graph_proven_items: build an
undirected graph from that entry's citation triples, BFS from the entry's
id, and verify the declared packet root is reachable. Entries that do not
back-chain to the root are AUTO-DEMOTED into review_items by
apply_auto_demotions(), preserving the LLM's original rationale as part
of the demotion reason.

This catches the category of error where an LLM cites real edges whose
upstream anchor is some OTHER root than the one the question declared —
a policy violation that shape-only grounding misses.
"""
from __future__ import annotations
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from .planner import ID_IN_QUESTION


# Reuse the same id regex used in the planner; the shape
# ("x" followed by 15+ hex chars) is the canonical SystemWeaver node id form.
_ID_RE = ID_IN_QUESTION


def _citation_graph(citations_list: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Build an undirected adjacency map from a list of citation triples.
    Relations are treated as undirected because SP0003/SP0006 anchor a Req
    Trace Item to two ends (parent + derived) and the natural "chain"
    reads from either end."""
    adj: Dict[str, Set[str]] = {}
    for c in citations_list or []:
        frm = c.get("from", "")
        to = c.get("to", "")
        if not frm or not to:
            continue
        adj.setdefault(frm, set()).add(to)
        adj.setdefault(to, set()).add(frm)
    return adj


def _chain_reaches_root(adj: Dict[str, Set[str]], start: str, root_id: str) -> bool:
    """BFS from start over adj, return True iff root_id is reachable."""
    if not start:
        return False
    if start == root_id:
        return True
    if start not in adj:
        return False
    visited = {start}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == root_id:
            return True
        for nxt in adj.get(cur, ()):
            if nxt not in visited:
                visited.add(nxt)
                q.append(nxt)
    return False


def _answer_wide_citation_graph(
    claims: List[Dict[str, Any]],
    allowed_sids: Optional[Set[str]] = None,
) -> Dict[str, Set[str]]:
    """Union of citation graphs across every graph_proven_items entry.

    A multi-hop DR may only cite the final hop in its own citations; the
    preceding hops are supplied by the parent FR's citations. Using the
    answer-wide union lets the chain check accept those legitimate
    multi-hop answers.

    If `allowed_sids` is non-empty, only citations with `relation_sid` in
    that set contribute to the graph — this implements the policy-level
    filter where the question names specific sids (e.g. SP0003/SP0006)
    and items whose chain relies on other relations (e.g. Function Inbox
    SP0670/SP0672) must be auto-demoted.
    """
    filtered: List[Dict[str, Any]] = []
    for item in claims or []:
        for c in item.get("citations") or []:
            if allowed_sids and c.get("relation_sid") not in allowed_sids:
                continue
            filtered.append(c)
    return _citation_graph(filtered)


def validate_llm_output(parsed: Optional[Dict[str, Any]], content: str, packet: Dict[str, Any]) -> Dict[str, Any]:
    sg = packet.get("candidate_subgraph") or {}
    packet_node_ids: Set[str] = {n.get("id") for n in sg.get("nodes", []) if n.get("id")}
    packet_node_names: Dict[str, str] = {
        n.get("id"): (n.get("name") or "").strip()
        for n in sg.get("nodes", []) if n.get("id")
    }
    packet_edge_triples: Set[Tuple[str, str, str]] = set(
        (e.get("from", ""), e.get("to", ""), e.get("relation_sid", ""))
        for e in sg.get("edges", [])
    )

    text_mentioned_ids = sorted(set(_ID_RE.findall(content or "")))
    unsupported_text_ids = [x for x in text_mentioned_ids if x not in packet_node_ids]

    parsed_ok = parsed is not None
    structural_issues: List[Dict[str, Any]] = []
    claim_ids: List[str] = []
    unsupported_claim_ids: List[str] = []
    unsupported_citations: List[Dict[str, Any]] = []
    citation_count = 0
    root_anchored_claim_count = 0
    auto_demoted: List[Dict[str, Any]] = []

    if parsed_ok:
        try:
            root_id = sg.get("root_id", "")
            # If the packet declares a claim_relation_sids policy, the
            # chain check restricts to those relations. Otherwise any
            # cited relation counts (back-compat).
            policy_block = packet.get("policy") or {}
            policy_sids = set(policy_block.get("claim_relation_sids") or [])
            answer_adj = _answer_wide_citation_graph(
                parsed.get("graph_proven_items") or [],
                allowed_sids=policy_sids or None,
            )
            for item in parsed.get("graph_proven_items") or []:
                iid = item.get("id", "")
                claim_ids.append(iid)
                if iid and iid not in packet_node_ids:
                    unsupported_claim_ids.append(iid)
                # Name-match check: the claim must carry the packet node's real name.
                # Catches the Q3-style field-shuffling we saw from GPT-5.1 where
                # the rationale was stuffed into `name`.
                if iid and iid in packet_node_names:
                    claimed_name = (item.get("name") or "").strip()
                    expected_name = packet_node_names[iid]
                    if claimed_name and expected_name and claimed_name != expected_name:
                        structural_issues.append({
                            "item_id": iid,
                            "issue": "claim_name_mismatch",
                            "expected": expected_name,
                            "got": claimed_name[:100],
                        })
                anchors_root = False
                citations_list = item.get("citations") or []
                for cit in citations_list:
                    triple = (cit.get("from", ""), cit.get("to", ""), cit.get("relation_sid", ""))
                    citation_count += 1
                    if triple not in packet_edge_triples:
                        unsupported_citations.append({"item_id": iid, "citation": cit})
                    if root_id and (triple[0] == root_id or triple[1] == root_id):
                        anchors_root = True
                if anchors_root:
                    root_anchored_claim_count += 1
                if not citations_list:
                    structural_issues.append({"item_id": iid, "issue": "no_citations_provided"})
                # Root-anchor chain check: does the union of citations across
                # all graph_proven_items form a connected path from this
                # claim back to the declared root?
                if iid and root_id and iid in packet_node_ids and citations_list:
                    chain_ok = _chain_reaches_root(answer_adj, iid, root_id)
                    if not chain_ok:
                        if policy_sids:
                            demote_reason_prefix = (
                                f"Auto-demoted: the citation chain back to the declared root "
                                f"relies on relations outside the policy set "
                                f"{sorted(policy_sids)}, or does not reach the root at all."
                            )
                        else:
                            demote_reason_prefix = (
                                "Auto-demoted: the provided citations do not form a chain "
                                "back to the declared root."
                            )
                        auto_demoted.append({
                            "id": iid,
                            "name": item.get("name", ""),
                            "item_type": item.get("item_type", ""),
                            "reason": (
                                demote_reason_prefix
                                + " Original rationale: "
                                + (item.get("rationale") or "").strip()
                            ).strip(),
                        })
            # Mutual-exclusion check: no id may appear in both graph_proven
            # and review. If it does, the answer contradicts itself (we saw
            # GPT-5.1 do this on Q5). Flag and surface to the reviewer.
            proven_ids_set = {i.get("id") for i in (parsed.get("graph_proven_items") or []) if i.get("id")}
            review_ids_set = {i.get("id") for i in (parsed.get("review_items") or []) if i.get("id")}
            both = sorted(proven_ids_set & review_ids_set)
            if both:
                structural_issues.append({"issue": "ids_in_both_lists", "ids": both})
        except Exception as exc:
            structural_issues.append({"issue": "traversal_error", "detail": str(exc)})

    grounded = (
        parsed_ok
        and not unsupported_text_ids
        and not unsupported_claim_ids
        and not unsupported_citations
        and not structural_issues
    )

    coverage = None
    if claim_ids:
        coverage = round(root_anchored_claim_count / len(claim_ids), 2)

    return {
        "parsed_ok": parsed_ok,
        "grounded": grounded,
        "review_required": not grounded,
        "mentioned_ids": text_mentioned_ids,
        "unsupported_text_ids": unsupported_text_ids,
        "claim_count": len(claim_ids),
        "unsupported_claim_ids": unsupported_claim_ids,
        "citation_count": citation_count,
        "unsupported_citations": unsupported_citations,
        "root_anchored_claim_count": root_anchored_claim_count,
        "root_anchored_coverage": coverage,
        "structural_issues": structural_issues,
        "auto_demoted": auto_demoted,
    }


def apply_auto_demotions(parsed: Optional[Dict[str, Any]], validation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a new answer dict with policy-violating claims moved from
    graph_proven_items to review_items. If nothing was demoted, returns the
    original dict unchanged (same object reference)."""
    if parsed is None or not validation:
        return parsed
    demoted = validation.get("auto_demoted") or []
    if not demoted:
        return parsed
    demoted_by_id = {d.get("id"): d for d in demoted if d.get("id")}
    new_proven = []
    appended_review = []
    for item in parsed.get("graph_proven_items") or []:
        iid = item.get("id", "")
        if iid in demoted_by_id:
            appended_review.append({"id": iid, "reason": demoted_by_id[iid].get("reason", "Auto-demoted.")})
        else:
            new_proven.append(item)
    merged_review = list(parsed.get("review_items") or []) + appended_review
    return {**parsed, "graph_proven_items": new_proven, "review_items": merged_review}
