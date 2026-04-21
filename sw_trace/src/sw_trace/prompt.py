"""Prompt text and strict JSON schema shown to the LLM.

The schema is used both by OpenAI's Responses API (structured output)
and by LM Studio's `response_format` shape. When a Metamodel is passed in
the `item_type` field is pinned to the known vocabulary — preventing
string-drift like the literal "inference" bug we saw once from GPT-5.1.
"""
from __future__ import annotations
import json
from typing import Any, Dict, Optional

from .metamodel import Metamodel


def build_answer_schema(metamodel: Optional[Metamodel] = None) -> Dict[str, Any]:
    """Build the strict JSON schema used to constrain the LLM response.

    When a Metamodel is supplied, `item_type` is pinned to an enum of known
    metamodel item types — OpenAI's strict mode will then refuse to emit a
    non-vocabulary string (previously observed: GPT-5.1 putting
    "inference" in that field). When no Metamodel is passed the field is a
    plain string for back-compat.
    """
    if metamodel and metamodel.vocabulary_item_types:
        item_type_field: Dict[str, Any] = {
            "type": "string",
            "enum": sorted(metamodel.vocabulary_item_types),
        }
    else:
        item_type_field = {"type": "string"}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "answer_summary",
            "graph_proven_items",
            "review_items",
            "support_strength",
            "uncertainties",
            "recommended_human_checks",
        ],
        "properties": {
            "answer_summary": {"type": "string"},
            "graph_proven_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "name", "item_type", "rationale", "citations"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "item_type": item_type_field,
                        "rationale": {"type": "string"},
                        "citations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["from", "to", "relation_sid"],
                                "properties": {
                                    "from": {"type": "string"},
                                    "to": {"type": "string"},
                                    "relation_sid": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "review_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "reason"],
                    "properties": {
                        "id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "support_strength": {"type": "string", "enum": ["strong", "partial", "weak"]},
            "uncertainties": {"type": "array", "items": {"type": "string"}},
            "recommended_human_checks": {"type": "array", "items": {"type": "string"}},
        },
    }


# Back-compat alias: schema without metamodel-constrained item_type enum.
# Callers that want item_type pinned to the vocabulary should use
# build_answer_schema(metamodel) and pass the result to analyze_with_llm via
# json_schema=. The unconstrained form below is kept so external callers that
# built a prompt directly without a metamodel still work.
ANSWER_JSON_SCHEMA: Dict[str, Any] = build_answer_schema(None)


def build_prompt(packet: Dict[str, Any]) -> str:
    policy = packet.get("policy") or {}
    claim_sids = policy.get("claim_relation_sids") or []
    policy_rule = ""
    if claim_sids:
        policy_rule = (
            f"- The packet's `policy` block declares root_id={policy.get('root_id')!r} and "
            f"claim_relation_sids={claim_sids}. The union of citation triples you provide "
            f"across graph_proven_items MUST form a path from each claimed id back to the "
            f"root_id using ONLY relations in claim_relation_sids. If reaching the root "
            f"requires a citation whose relation_sid is NOT in claim_relation_sids (e.g. "
            f"Function Inbox structural edges), the item belongs in review_items with the "
            f"reason that its trace chain violates the policy.\n"
        )
    return (
        "You are a trustworthy AI traceability assistant for systems engineering.\n\n"
        "Task:\n"
        "Answer the engineering question using only the evidence packet.\n\n"
        "Rules:\n"
        "- Use only the packet below.\n"
        "- Do not invent items, IDs, links, paths, tests, or conclusions not supported by the packet.\n"
        "- Copy any IDs exactly as they appear in the packet.\n"
        "- For every graph_proven_items entry, include at least one citation whose (from, to, relation_sid) triple exactly matches an edge in candidate_subgraph.edges.\n"
        "- An id MUST NOT appear in both graph_proven_items and review_items — decide one list per item.\n"
        "- Prefer findings that are supported by root-anchored candidate paths.\n"
        f"{policy_rule}"
        "- If the evidence is partial, indirect, or ambiguous, say so in uncertainties and mark support_strength accordingly.\n"
        "- Items you consider suspicious or incomplete belong in review_items.\n\n"
        "Use node descriptions for understanding, not as evidence of relations:\n"
        "- Each node in candidate_subgraph.nodes carries a `description` field. Read it\n"
        "  to understand what the item means, to disambiguate similar names, and to\n"
        "  interpret abbreviated or abstract titles before deciding which nodes are\n"
        "  relevant to the question.\n"
        "- A description is semantic context only. It must not be cited as proof of a\n"
        "  relation, and it cannot override the graph structure. Every claim in\n"
        "  graph_proven_items must still be supported by at least one citation whose\n"
        "  (from, to, relation_sid) triple exactly matches an edge in\n"
        "  candidate_subgraph.edges.\n"
        "- If a description suggests a link that the edges do not support, surface that\n"
        "  in uncertainties or review_items rather than inventing a citation.\n\n"
        "Return a JSON object that matches the provided schema exactly.\n\n"
        "Evidence packet:\n"
        f"{json.dumps(packet, indent=2, ensure_ascii=False)}"
    ).strip()
