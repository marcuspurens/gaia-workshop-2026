"""Render the self-eval responses as reviewer-facing natural-language markdown.

Reads `logs/self_eval/<qid>_response.json` and `<qid>_effective.json`
(written by `eval/self_eval.py validate`), feeds each through
`_render_answer_prose()` — the same renderer `run_from_question()` uses
in the live pipeline — and emits:

    output/self_eval/Q<N>_answer.md    — per-question prose
    output/self_eval/answers.md        — all four concatenated

The markdown strips ids and citation triples on purpose; it is the
engineer-facing view. The audit view (ids, citations, grounding metrics)
lives in the JSON sidecars under `logs/self_eval/`.
"""
from __future__ import annotations
import json
from pathlib import Path

from sw_trace import PROJECT_ROOT, SELF_EVAL_LOGS_DIR
from sw_trace.artifacts import _render_answer_prose


QUESTIONS = [
    ("Q1", 'Which function and design requirements will get affected if the legal requirement "UNECE Regulation No.155" gets removed?'),
    ("Q2", 'Does the requirement "Keyless entry" (x0400000000038EAE) have any test cases?'),
    ("Q3", 'Starting from the Stakeholder Requirement "Unauthorized start detection", which Function Requirements appear in the local downstream trace tree, and which Design Requirements appear one level further downstream?'),
    ("Q4", 'If the Function Requirement "Engine start time" is tightened (smaller N), which Design Requirements are impacted downstream? Optionally: Which of them mention timing or timeout explicitly?'),
]

OUT_DIR = PROJECT_ROOT / "output" / "self_eval"


def _run_record(qid: str, qtext: str) -> dict:
    """Assemble the minimal dict shape `_render_answer_prose()` expects."""
    effective_path = SELF_EVAL_LOGS_DIR / f"{qid}_effective.json"
    response_path = SELF_EVAL_LOGS_DIR / f"{qid}_response.json"
    effective = json.loads(effective_path.read_text(encoding="utf-8")) if effective_path.exists() else None
    raw_answer = json.loads(response_path.read_text(encoding="utf-8")) if response_path.exists() else None
    return {
        "run_label": qid,
        "question_text": qtext,
        "llm_answer": raw_answer,
        "llm_answer_effective": effective,
        "llm_response": None,
        "llm_status": "self-eval (hand-authored response)",
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    combined: list[str] = [
        "# sw_trace self-eval — natural-language answers",
        "",
        "_These are the reviewer-facing prose renderings of the four self-eval answers. "
        "Ids, citation triples, and grounding metrics are omitted on purpose; they live in the "
        "JSON sidecars under `logs/self_eval/`. The prose uses the post-demote effective answer "
        "when available, falling back to the raw hand-authored response._",
        "",
    ]
    for qid, qtext in QUESTIONS:
        run = _run_record(qid, qtext)
        md = _render_answer_prose(run)
        per_q_path = OUT_DIR / f"{qid}_answer.md"
        per_q_path.write_text(md, encoding="utf-8")
        combined.append(md.rstrip())
        combined.append("\n---\n")
        print(f"{qid}: wrote {per_q_path}")
    combined_path = OUT_DIR / "answers.md"
    combined_path.write_text("\n".join(combined).rstrip() + "\n", encoding="utf-8")
    print(f"\nWrote combined: {combined_path}")


if __name__ == "__main__":
    main()
