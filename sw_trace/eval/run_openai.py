"""Run the four workshop questions against a real OpenAI model (gpt-5.1 by
default) and save every artifact with collision-free, inspection-friendly
filenames.

Layout (all paths relative to the project root):

    logs/openai_gpt51/
        Q1_packet.json            — full evidence packet + planner diagnostics
        Q1_answer.json            — raw LLM content, parsed JSON, effective answer
        Q1_grounding.json         — validator's grounding report
        Q2_packet.json ... Q4_grounding.json
    output/openai_gpt51/
        Q1_answer.md              — reviewer prose (IDs stripped)
        Q2_answer.md ... Q4_answer.md
        answers.md                — all four prose answers concatenated

    logs/run_<ts>_openai_gpt51.json                          — aggregated bundle
    output/run_<ts>_openai_gpt51.md                          — run summary + prose
    logs/run_<ts>_openai_gpt51_ground_truth_comparison.json  — scored against GT
    output/run_<ts>_openai_gpt51_ground_truth_comparison.md

    logs/token_usage_ledger.jsonl  — append-only, one row per question
    logs/token_usage_summary.json  — aggregated by run / model / question

The per-question files under `logs/openai_gpt51/` and `output/openai_gpt51/`
are the individual inspection handles. The run-id-stamped files live at
the top of `logs/` and `output/` because they are per-run (not per-mode)
and never collide.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from sw_trace import (
    GRAPH_PATH,
    GROUND_TRUTH_PATH,
    METAMODEL_PATH,
    Metamodel,
    RunBundle,
    TraceGraph,
    UsageTracker,
    format_usage,
    llm_config_ready,
    resolve_llm_config,
    run_from_question,
    save_run_artifacts,
)
from sw_trace.artifacts import _render_answer_prose


QUESTIONS = [
    ("Q1", 'Which function and design requirements will get affected if the legal requirement "UNECE Regulation No.155" gets removed?'),
    ("Q2", 'Does the requirement "Keyless entry" (x0400000000038EAE) have any test cases?'),
    ("Q3", 'Starting from the Stakeholder Requirement "Unauthorized start detection", which Function Requirements appear in the local downstream trace tree, and which Design Requirements appear one level further downstream?'),
    ("Q4", 'If the Function Requirement "Engine start time" is tightened (smaller N), which Design Requirements are impacted downstream? Optionally: Which of them mention timing or timeout explicitly?'),
]


def _short_status(run: dict) -> str:
    """One-line status for console reporting."""
    v = run.get("llm_validation") or {}
    resp = run.get("llm_response") or {}
    u = resp.get("usage") or {}
    grounded = v.get("grounded")
    claim_count = v.get("claim_count", 0)
    demoted = len(v.get("auto_demoted") or [])
    structural = len(v.get("structural_issues") or [])
    truncated = resp.get("truncated")
    grounded_tag = "GROUNDED" if grounded else "REVIEW"
    parts = [
        f"{grounded_tag:<9}",
        f"claims={claim_count}",
        f"demoted={demoted}",
        f"structural={structural}",
        f"tokens={u.get('total_tokens', 0):,}",
    ]
    if truncated:
        parts.append(f"TRUNCATED({resp.get('truncation_reason')})")
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai", help="LLM provider (openai / lmstudio). Default: openai.")
    parser.add_argument("--model", default="gpt-5.1", help="Model id. Default: gpt-5.1.")
    parser.add_argument("--max-tokens", type=int, default=8000, help="Per-call output-token budget (auto-retry doubles on truncate). Default: 8000.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature. Default: 0.0.")
    parser.add_argument("--timeout", type=float, default=300.0, help="Per-call timeout in seconds. Default: 300.")
    parser.add_argument("--mode-label", default=None, help="Override the mode label used in filenames. Default: <provider>_<model-sanitised>.")
    args = parser.parse_args()

    mode_label = args.mode_label or f"{args.provider}_{args.model}".replace(".", "").replace("-", "")

    # Project-rooted subdirectories for this mode so per-question files
    # don't collide across runs.
    project_root = Path(GRAPH_PATH).resolve().parent.parent
    mode_logs_dir = project_root / "logs" / mode_label
    mode_output_dir = project_root / "output" / mode_label
    top_logs_dir = project_root / "logs"
    top_output_dir = project_root / "output"
    mode_logs_dir.mkdir(parents=True, exist_ok=True)
    mode_output_dir.mkdir(parents=True, exist_ok=True)

    # Sanity: make sure credentials are present before loading the graph.
    cfg = resolve_llm_config(args.provider, args.model)
    ok, note = llm_config_ready(cfg)
    print(f"[config] {note}")
    if not ok:
        print("Aborting: LLM config not ready.", file=sys.stderr)
        return 2

    print(f"[load ] graph={GRAPH_PATH}")
    print(f"[load ] metamodel={METAMODEL_PATH}")
    graph = TraceGraph.from_json(str(GRAPH_PATH))
    metamodel = Metamodel.load(str(METAMODEL_PATH))
    print(f"[load ] {len(graph.nodes):,} nodes, {len(graph.edges):,} edges; "
          f"{len(metamodel.vocabulary_item_types)} item types, "
          f"{len(metamodel.vocabulary_relation_sids)} relation sids")

    # Aggregated layout: one run-level bundle JSON+MD at the top of
    # logs/ and output/. Token ledger always appends globally.
    bundle = RunBundle(
        mode=mode_label,
        graph_path=str(GRAPH_PATH),
        metamodel_path=str(METAMODEL_PATH),
        layout="aggregated",
        logs_dir=str(top_logs_dir),
        output_dir=str(top_output_dir),
    )
    print(f"[bundle] run_id={bundle.run_id}")
    print(f"[bundle] per-question artifacts -> {mode_logs_dir}, {mode_output_dir}")
    print()

    tracker = UsageTracker()
    per_q_prose: list[str] = []

    for qid, qtext in QUESTIONS:
        print(f"=== {qid} ===")
        print(f"[q    ] {qtext}")
        run = run_from_question(
            graph,
            metamodel,
            qtext,
            llm_provider=args.provider,
            llm_model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
            run_label=qid,
        )
        bundle.add(run)  # appends to global ledger; bundle holds the run
        tracker.record(run)

        # Per-question inspection files under logs/<mode>/ and output/<mode>/.
        # Using save_run_artifacts directly lets us point it at a mode-specific
        # subdirectory instead of the top-level logs/output, so repeated runs
        # with different models don't overwrite each other.
        written = save_run_artifacts(
            run,
            logs_dir=str(mode_logs_dir),
            output_dir=str(mode_output_dir),
        )

        # Keep the prose for the combined answers.md in the mode subdir.
        per_q_prose.append(_render_answer_prose(run))

        print(f"[stat ] {_short_status(run)}")
        print(f"[stat ] {run.get('llm_status','(no status)')}")
        print(f"[file ] packet  -> {written['packet']}")
        print(f"[file ] answer  -> {written['answer_json']}")
        print(f"[file ] ground  -> {written['grounding']}")
        print(f"[file ] prose   -> {written['answer_md']}")
        print()

    # Combined prose MD inside the mode subdir — the notebook's per_question
    # layout doesn't do this, but it's genuinely useful for inspection.
    combined_md = "\n---\n\n".join(p.rstrip() for p in per_q_prose) + "\n"
    combined_path = mode_output_dir / "answers.md"
    combined_path.write_text(
        "# " + mode_label + " — all answers\n\n" + combined_md,
        encoding="utf-8",
    )
    print(f"[file ] combined prose -> {combined_path}")

    # Run-level: bundle JSON+MD at top-level, ledger summary, ground truth.
    written = bundle.finalize(ground_truth_path=GROUND_TRUTH_PATH)
    print()
    print("=== finalize ===")
    for k, v in written.items():
        print(f"[file ] {k}: {v}")

    print()
    print("=== token usage ===")
    print(tracker.summary())

    # Short per-question final summary for the console.
    print()
    print("=== per-question summary ===")
    for run in bundle.runs:
        print(f"  {run.get('run_label'):<4} {_short_status(run)}")

    # Exit code reflects ground-truth outcome when a GT report was produced.
    gt_status = written.get("ground_truth_all_passed")
    if gt_status == "PASS":
        print("\nGround truth: PASS (all questions matched expected ids)")
        return 0
    if gt_status == "FAIL":
        print("\nGround truth: FAIL (see the comparison MD for details)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
