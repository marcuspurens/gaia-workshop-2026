"""End-to-end orchestrator + connection smoke test.

`run_question()` does plan+extract only (no LLM call) and returns the
bounded subgraph with planner diagnostics. `run_from_question()` is the
full pipeline: plan -> extract -> packet -> LLM -> grounding, with an
auto-retry once if the first LLM response was truncated.

`build_connection_smoke_test_packet()` is a tiny hand-crafted packet used
at notebook startup to verify the LM Studio / OpenAI endpoint is wired
up before a real run.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from .config import llm_config_ready, resolve_llm_config
from .extractor import extract_candidate_subgraph
from .graph import TraceGraph, brief
from .llm_client import analyze_with_llm
from .metamodel import Metamodel
from .packet import build_evidence_packet, compact_answer_view
from .planner import plan_question
from .prompt import build_answer_schema
from .validator import apply_auto_demotions, validate_llm_output


def run_question(graph: TraceGraph, metamodel: Metamodel, question_text: str) -> Dict[str, Any]:
    """Plan + extract. No LLM call. Returns the bounded subgraph and planner diagnostics."""
    policy, diag = plan_question(graph, metamodel, question_text)
    root = graph.id2node[policy.root_id]
    subgraph = extract_candidate_subgraph(graph, metamodel, policy)
    return {
        "question_text": question_text,
        "root": brief(root, include_text=True),
        "root_node": root,
        "policy": policy,
        "planner_diagnostics": diag,
        "candidate_subgraph": subgraph,
    }


def run_from_question(
    graph: TraceGraph,
    metamodel: Metamodel,
    question_text: str,
    llm_provider: str = "lmstudio",
    llm_model: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
    temperature: float = 0.0,
    max_tokens: int = 2000,
    timeout: float = 300.0,
    run_label: Optional[str] = None,
    auto_retry_on_truncate: bool = True,
    truncate_retry_multiplier: int = 2,
) -> Dict[str, Any]:
    """Full pipeline: plan -> extract -> packet -> LLM -> grounding."""
    result = run_question(graph, metamodel, question_text)
    packet = build_evidence_packet(
        question_text=question_text,
        subgraph=result["candidate_subgraph"],
        root=result["root_node"],
        planner_diag=result["planner_diagnostics"],
        policy=result.get("policy"),
    )
    compact = compact_answer_view(question_text, result["candidate_subgraph"], result["root"])

    resolved_cfg = resolve_llm_config(llm_provider, llm_model, lmstudio_base_url=llm_base_url)
    if llm_provider == "openai" and llm_api_key:
        resolved_cfg["api_key"] = llm_api_key
    config_ok, config_note = llm_config_ready(resolved_cfg)

    llm_response: Optional[Dict[str, Any]] = None
    llm_validation: Optional[Dict[str, Any]] = None
    llm_status: str = config_note
    llm_answer: Optional[Dict[str, Any]] = None

    if config_ok:
        try:
            current_budget = max_tokens
            llm_response = analyze_with_llm(
                provider=resolved_cfg["provider"],
                model=resolved_cfg["model"],
                packet=packet,
                api_key=resolved_cfg.get("api_key", llm_api_key),
                base_url=resolved_cfg.get("base_url", llm_base_url),
                temperature=temperature,
                max_tokens=current_budget,
                timeout=timeout,
                json_schema=build_answer_schema(metamodel),
            )
            llm_status = f"LLM call succeeded via {llm_provider}."
            # Auto-retry once on truncation with a larger output budget.
            if auto_retry_on_truncate and llm_response.get("truncated"):
                retry_budget = int(current_budget * max(truncate_retry_multiplier, 2))
                llm_status = (
                    f"LLM call truncated ({llm_response.get('truncation_reason')}); "
                    f"retrying with max_tokens={retry_budget}."
                )
                llm_response = analyze_with_llm(
                    provider=resolved_cfg["provider"],
                    model=resolved_cfg["model"],
                    packet=packet,
                    api_key=resolved_cfg.get("api_key", llm_api_key),
                    base_url=resolved_cfg.get("base_url", llm_base_url),
                    temperature=temperature,
                    max_tokens=retry_budget,
                    timeout=timeout,
                    json_schema=build_answer_schema(metamodel),
                )
                if llm_response.get("truncated"):
                    llm_status = (
                        f"LLM call truncated twice (last reason: "
                        f"{llm_response.get('truncation_reason')}). "
                        f"Consider raising max_tokens above {retry_budget}."
                    )
                else:
                    llm_status = f"LLM call succeeded via {llm_provider} after one retry at max_tokens={retry_budget}."
            llm_answer = llm_response.get("parsed")
            llm_validation = validate_llm_output(llm_answer, llm_response.get("content") or "", packet)
            # Surface parse/truncation failures in the grounding report as
            # structural issues so the reviewer sees them alongside other flags.
            if llm_response.get("parse_error") and llm_validation is not None:
                llm_validation["structural_issues"] = (llm_validation.get("structural_issues") or []) + [{
                    "issue": "llm_json_parse_failed",
                    "detail": llm_response["parse_error"],
                    "truncated": bool(llm_response.get("truncated")),
                }]
                llm_validation["grounded"] = False
                llm_validation["review_required"] = True
        except Exception as exc:
            llm_status = f"LLM analysis failed: {exc}"

    # If the validator flagged policy violations (citations that do not
    # back-chain to the declared root), produce an effective answer with
    # those claims demoted into review_items. The original llm_answer is
    # preserved for audit.
    llm_answer_effective: Optional[Dict[str, Any]] = None
    if llm_answer is not None and llm_validation is not None:
        llm_answer_effective = apply_auto_demotions(llm_answer, llm_validation)

    return {
        "run_label": run_label or "run",
        "question_text": question_text,
        "result": result,
        "compact_view": compact,
        "planner_diagnostics": result["planner_diagnostics"].to_dict(),
        "evidence_packet": packet,
        "llm_status": llm_status,
        "llm_response": llm_response,
        "llm_answer": llm_answer,
        "llm_answer_effective": llm_answer_effective,
        "llm_validation": llm_validation,
    }


def build_connection_smoke_test_packet(graph: TraceGraph) -> Dict[str, Any]:
    """Tiny hand-crafted packet for verifying the LLM endpoint is live.

    Uses two hardcoded node ids known to exist in the shipped trace graph.
    The returned packet has the minimum shape the notebook needs to send
    a one-question call and confirm the provider returns a parseable
    response — nothing else depends on it being exhaustive.
    """
    trace_item = next(n for n in graph.nodes if n["id"] == "x040000000003854D")
    stakeholder = next(n for n in graph.nodes if n["id"] == "x0400000000003B28")
    return {
        "question_id": "SMOKE",
        "question_text": "Which stakeholder requirement is this req trace item traced from? Answer with the requirement name only.",
        "nodes": [brief(trace_item, include_text=False), brief(stakeholder, include_text=False)],
        "edges": [{"from": trace_item["id"], "to": stakeholder["id"], "relation_name": "Traced from", "relation_sid": "SP0003"}],
    }
