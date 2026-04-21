"""Self-evaluation harness — the assistant acts as the analysis LLM.

Phases
------
Phase 1 (`build`): build evidence packets for all four questions and dump
    logs/self_eval/<qid>_packet.json   — full evidence packet
    logs/self_eval/<qid>_prompt.txt    — rendered prompt the LLM would see
    logs/self_eval/<qid>_compact.json  — smaller human-friendly view

Phase 2 (manual): the operator hand-writes a JSON answer for each
    question into logs/self_eval/<qid>_response.json, following only the
    rules the real LLM would — no peeking at ground_truth.json.

Phase 3 (`validate`): run validator + apply auto-demotions + compare the
    post-demote set against ground_truth.json. Writes
    logs/self_eval/<qid>_validation.json
    logs/self_eval/<qid>_effective.json
    logs/self_eval/summary.json

Usage
-----
    python eval/self_eval.py build      # phase 1
    python eval/self_eval.py validate   # phase 3
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from sw_trace import (
    GRAPH_PATH,
    GROUND_TRUTH_PATH,
    METAMODEL_PATH,
    SELF_EVAL_LOGS_DIR,
    Metamodel,
    TraceGraph,
    apply_auto_demotions,
    build_evidence_packet,
    build_prompt,
    compact_answer_view,
    extract_candidate_subgraph,
    plan_question,
    validate_llm_output,
)

QUESTIONS = [
    ("Q1", 'Which function and design requirements will get affected if the legal requirement "UNECE Regulation No.155" gets removed?'),
    ("Q2", 'Does the requirement "Keyless entry" (x0400000000038EAE) have any test cases?'),
    ("Q3", 'Starting from the Stakeholder Requirement "Unauthorized start detection", which Function Requirements appear in the local downstream trace tree, and which Design Requirements appear one level further downstream?'),
    ("Q4", 'If the Function Requirement "Engine start time" is tightened (smaller N), which Design Requirements are impacted downstream? Optionally: Which of them mention timing or timeout explicitly?'),
]


def phase_build() -> None:
    SELF_EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    graph = TraceGraph.from_json(GRAPH_PATH)
    metamodel = Metamodel.load(METAMODEL_PATH)

    for qid, qtext in QUESTIONS:
        policy, diag = plan_question(graph, metamodel, qtext)
        subgraph = extract_candidate_subgraph(graph, metamodel, policy)
        root = graph.id2node[policy.root_id]
        packet = build_evidence_packet(qtext, subgraph, root, diag, policy)
        prompt = build_prompt(packet)
        compact = compact_answer_view(qtext, subgraph, root)

        (SELF_EVAL_LOGS_DIR / f"{qid}_packet.json").write_text(
            json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (SELF_EVAL_LOGS_DIR / f"{qid}_prompt.txt").write_text(prompt, encoding="utf-8")
        (SELF_EVAL_LOGS_DIR / f"{qid}_compact.json").write_text(
            json.dumps(compact, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        meta = packet["candidate_subgraph"]["packet_metadata"]
        print(
            f"{qid}: {len(subgraph['nodes'])}n / {len(subgraph['edges'])}e / "
            f"{meta['candidate_path_count']}p  whitelists={diag.chosen_whitelists}"
        )


def phase_validate() -> None:
    gt_raw = json.loads(Path(GROUND_TRUTH_PATH).read_text(encoding="utf-8-sig"))
    gt = {k: v for k, v in gt_raw.items() if not k.startswith("_")}

    rows: List[Dict[str, Any]] = []
    for qid, qtext in QUESTIONS:
        packet_path = SELF_EVAL_LOGS_DIR / f"{qid}_packet.json"
        response_path = SELF_EVAL_LOGS_DIR / f"{qid}_response.json"
        if not response_path.exists():
            print(f"{qid}: SKIPPED — no response file at {response_path}")
            continue

        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        response_text = response_path.read_text(encoding="utf-8")
        answer = json.loads(response_text)
        validation = validate_llm_output(answer, response_text, packet)

        # Apply the same auto-demote that run_from_question applies in
        # the live pipeline so the score reflects what the human reviewer
        # would actually see.
        effective = apply_auto_demotions(answer, validation) or answer
        demoted_ids = [d.get("id") for d in (validation.get("auto_demoted") or []) if d.get("id")]

        (SELF_EVAL_LOGS_DIR / f"{qid}_validation.json").write_text(
            json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (SELF_EVAL_LOGS_DIR / f"{qid}_effective.json").write_text(
            json.dumps(effective, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Ground-truth comparison on the POST-DEMOTE set.
        gte = gt[qid]
        expected = set(gte["expected_graph_proven_ids"])
        got = {it["id"] for it in effective.get("graph_proven_items", [])}
        score_mode = gte.get("score_mode", "minimum")
        missing = sorted(expected - got)
        extra = sorted(got - expected)
        if score_mode == "exact":
            passed = not missing and not extra
        else:
            passed = not missing

        rows.append({
            "qid": qid,
            "question": qtext,
            "score_mode": score_mode,
            "expected": sorted(expected),
            "got": sorted(got),
            "missing": missing,
            "extra": extra,
            "demoted_ids": demoted_ids,
            "grounded": validation.get("grounded"),
            "validation_issues": {k: v for k, v in validation.items() if k not in {"grounded", "summary"} and v},
            "passed": passed,
        })
        flag = "PASS" if passed else "FAIL"
        print(f"{qid}: {flag}  missing={missing} extra={extra} demoted={demoted_ids}")

    (SELF_EVAL_LOGS_DIR / "summary.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {SELF_EVAL_LOGS_DIR / 'summary.json'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        phase_build()
    elif cmd == "validate":
        phase_validate()
    else:
        print(f"unknown command: {cmd}")
        sys.exit(2)
