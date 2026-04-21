"""Evidence packet assembly.

Wraps the extracted subgraph with the question text, the root brief, the
planner diagnostics, the policy block, and a small `system_constraints`
list that mirrors the rules encoded in the prompt. Also provides a
compact summary view useful for human quick-scan.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from .graph import brief
from .planner import PlannerDiagnostics, QuestionPolicy


def build_evidence_packet(
    question_text: str,
    subgraph: Dict[str, Any],
    root: Dict[str, Any],
    planner_diag: Optional[PlannerDiagnostics] = None,
    policy: Optional[QuestionPolicy] = None,
) -> Dict[str, Any]:
    constraints = [
        "Use only the evidence packet.",
        "Do not invent items, IDs, links, paths, or tests.",
        "Copy IDs exactly as they appear in the packet.",
        "Every claim in graph_proven_items must list at least one citation whose (from, to, relation_sid) exactly matches an edge in candidate_subgraph.edges.",
        "Prefer findings supported by root-anchored candidate paths.",
        "An id MUST NOT appear in both graph_proven_items and review_items.",
        "State uncertainty if the evidence is partial or ambiguous.",
        # Description is semantic context, not relation evidence — see build_prompt()
        # for the full rule. The short form here keeps the constraint visible inside
        # the packet itself so reviewers see the same rule the LLM was given.
        "Read node descriptions to interpret meaning and relevance; do not cite descriptions as evidence of relations — cite edges only.",
    ]
    policy_block: Dict[str, Any] = {}
    if policy is not None:
        policy_block = {
            "root_id": policy.root_id,
            "claim_relation_sids": sorted(policy.claim_relation_sids),
        }
        if policy.claim_relation_sids:
            constraints.append(
                "For every graph_proven_items entry, the union of citation triples across "
                "graph_proven_items must form a path from that entry's id to policy.root_id "
                "using only relations in policy.claim_relation_sids. Items whose chain relies "
                "on relations outside that set belong in review_items."
            )
    packet = {
        "question_id": "AD_HOC",
        "question": question_text,
        "question_type": "candidate_subgraph_analysis",
        "root": brief(root, include_text=True),
        "candidate_subgraph": subgraph,
        "policy": policy_block,
        "system_constraints": constraints,
    }
    if planner_diag is not None:
        packet["planner"] = planner_diag.to_dict()
    return packet


def compact_answer_view(question_text: str, subgraph: Dict[str, Any], root: Dict[str, Any]) -> Dict[str, Any]:
    sg = subgraph
    return {
        "root": root.get("name"),
        # `root` here is the brief() output which stores the item type under
        # the key "type". Fall back to "item_type" for raw node dicts.
        "root_type": root.get("type") or root.get("item_type"),
        "question": question_text,
        "node_count": sg["packet_metadata"]["node_count"],
        "edge_count": sg["packet_metadata"]["edge_count"],
        "candidate_path_count": sg["packet_metadata"].get("candidate_path_count", len(sg.get("candidate_paths", []))),
        "warning_count": len(sg.get("warnings", [])),
        "sample_node_names": [n["name"] for n in sg["nodes"][:12]],
        "sample_edge_types": sorted({(e.get("relation_sid") or e.get("relation_name") or "") for e in sg["edges"]})[:12],
    }
