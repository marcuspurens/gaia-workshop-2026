"""Run-level bundling, token ledger, cumulative summary, ground-truth diffing.

Two layouts are supported:

  "per_question" — each question's individual logs/output files are
                   written; NO run-level bundle is written. Use when a
                   workshop walks through questions one at a time.
  "aggregated"   — per-question files are NOT written; one run-level
                   JSON + MD contains all questions. Use for a single
                   end-to-end run.

In BOTH layouts: every question's token usage is appended to a
cumulative ledger (logs/token_usage_ledger.jsonl, append-only) and the
aggregate summary (logs/token_usage_summary.json) is refreshed at
finalize().
"""
from __future__ import annotations
import datetime as _dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .artifacts import _json_safe, _render_answer_prose, save_run_artifacts
from .llm_client import format_usage


TOKEN_LEDGER_FILE = "token_usage_ledger.jsonl"
TOKEN_SUMMARY_FILE = "token_usage_summary.json"


def make_run_id(mode: str, now: Optional[_dt.datetime] = None) -> str:
    """Build a run id of the form run_YYYYMMDD_HHMMSS_<mode>. Uses local
    time so the filename lines up with the engineer's wall clock."""
    t = now or _dt.datetime.now()
    safe_mode = re.sub(r"[^a-z0-9_\-]+", "_", (mode or "run").lower()).strip("_") or "run"
    return f"run_{t.strftime('%Y%m%d_%H%M%S')}_{safe_mode}"


@dataclass
class RunBundle:
    """Collects one or more question runs and writes layout-appropriate
    artifacts. See module header for the two layouts."""
    mode: str
    graph_path: Optional[str] = None
    metamodel_path: Optional[str] = None
    layout: str = "per_question"
    logs_dir: str = "logs"
    output_dir: str = "output"
    run_id: str = ""
    timestamp_utc: str = ""
    runs: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = make_run_id(self.mode)
        if not self.timestamp_utc:
            self.timestamp_utc = _dt.datetime.now(_dt.timezone.utc).isoformat()
        if self.layout not in {"per_question", "aggregated"}:
            raise ValueError(
                f"Unknown layout {self.layout!r}. Use 'per_question' or 'aggregated'."
            )

    def add(self, run: Dict[str, Any]) -> Dict[str, Any]:
        """Register a run. For per_question layout this writes the run's
        individual files right now; for aggregated layout it only stores
        the run in memory until finalize(). In either case, the token
        ledger is appended to."""
        self.runs.append(run)
        if self.layout == "per_question":
            save_run_artifacts(run, logs_dir=self.logs_dir, output_dir=self.output_dir)
        _append_token_ledger_row(self.logs_dir, self, run)
        return run

    def totals(self) -> Dict[str, int]:
        tot = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
        for r in self.runs:
            u = (r.get("llm_response") or {}).get("usage") or {}
            for k in tot:
                tot[k] += int(u.get(k, 0) or 0)
        return tot

    def finalize(self, ground_truth_path: str | Path | None = "ground_truth.json") -> Dict[str, str]:
        """Emit layout-dependent run-level files, refresh the cumulative
        token summary, and (if a ground-truth file exists at the given
        path) run the ground-truth comparison. Pass ground_truth_path=None
        to skip the comparison."""
        written: Dict[str, str] = {}
        if self.layout == "aggregated":
            written.update(save_run_bundle(self, logs_dir=self.logs_dir, output_dir=self.output_dir))
        written["token_usage_summary"] = rebuild_token_summary(self.logs_dir)
        if ground_truth_path and os.path.exists(str(ground_truth_path)):
            gt = compare_run_to_ground_truth(
                self, ground_truth_path=ground_truth_path,
                logs_dir=self.logs_dir, output_dir=self.output_dir,
            )
            written["ground_truth_json"] = gt["gt_json"]
            written["ground_truth_md"] = gt["gt_md"]
            written["ground_truth_all_passed"] = "PASS" if gt["all_passed"] else "FAIL"
        return written


def _append_token_ledger_row(logs_dir: str, bundle: RunBundle, run: Dict[str, Any]) -> None:
    os.makedirs(logs_dir, exist_ok=True)
    path = os.path.join(logs_dir, TOKEN_LEDGER_FILE)
    resp = run.get("llm_response") or {}
    usage = resp.get("usage") or {}
    provider = resp.get("provider")
    # is_mimic is True only when the run was synthetic (no external LLM call).
    # Failed real calls are distinguished by llm_status, NOT by this flag, so
    # the token summary can correctly separate "mimic" from "failed real".
    is_mimic = provider in {"synthetic", "codex-mimic"}
    row = {
        "run_id": bundle.run_id,
        "mode": bundle.mode,
        "timestamp_utc": bundle.timestamp_utc,
        "question_id": run.get("run_label"),
        "question_text": (run.get("question_text") or "")[:500],
        "provider": provider,
        "model": resp.get("model"),
        "llm_status": run.get("llm_status"),
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
        "reasoning_tokens": int(usage.get("reasoning_tokens", 0) or 0),
        "is_mimic": is_mimic,
        "estimated": is_mimic,  # back-compat alias for older ledger readers
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rebuild_token_summary(logs_dir: str = "logs") -> str:
    """Read the ledger and (re)write the summary JSON next to it."""
    os.makedirs(logs_dir, exist_ok=True)
    ledger_path = os.path.join(logs_dir, TOKEN_LEDGER_FILE)
    out_path = os.path.join(logs_dir, TOKEN_SUMMARY_FILE)
    rows: List[Dict[str, Any]] = []
    if os.path.exists(ledger_path):
        with open(ledger_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
    by_run: Dict[str, Dict[str, int]] = {}
    by_model: Dict[str, Dict[str, Any]] = {}
    by_question: Dict[str, Dict[str, int]] = {}
    estimated_runs: Set[str] = set()
    provider_runs: Set[str] = set()
    for r in rows:
        for k in total:
            total[k] += int(r.get(k, 0) or 0)
        rid = r.get("run_id") or "?"
        bucket = by_run.setdefault(rid, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0, "questions": 0})
        bucket["questions"] += 1
        for k in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens"):
            bucket[k] += int(r.get(k, 0) or 0)
        m = r.get("model") or "?"
        mm = by_model.setdefault(m, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "run_ids": set()})
        for k in ("input_tokens", "output_tokens", "total_tokens"):
            mm[k] += int(r.get(k, 0) or 0)
        mm["run_ids"].add(rid)
        q = r.get("question_id") or "?"
        qq = by_question.setdefault(q, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "occurrences": 0})
        qq["occurrences"] += 1
        for k in ("input_tokens", "output_tokens", "total_tokens"):
            qq[k] += int(r.get(k, 0) or 0)
        if r.get("estimated"):
            estimated_runs.add(rid)
        else:
            provider_runs.add(rid)
    summary = {
        "total_runs": len(by_run),
        "total_input_tokens": total["input_tokens"],
        "total_output_tokens": total["output_tokens"],
        "total_tokens": total["total_tokens"],
        "total_reasoning_tokens": total["reasoning_tokens"],
        "estimated_run_count": len(estimated_runs),
        "provider_reported_run_count": len(provider_runs),
        "totals_by_run": {k: v for k, v in sorted(by_run.items())},
        "totals_by_model": {
            m: {**{k: v[k] for k in v if k != "run_ids"}, "run_count": len(v["run_ids"])}
            for m, v in sorted(by_model.items())
        },
        "totals_by_question": {k: v for k, v in sorted(by_question.items())},
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(summary), f, indent=2, ensure_ascii=False)
    return out_path


def diff_two_run_bundles(
    bundle_a_json: str | Path,
    bundle_b_json: str | Path,
    output_md_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Compare two aggregated-layout run bundles (the files written by
    save_run_bundle) question by question. Reports differences in the
    effective `graph_proven_items` id sets and token spend.

    Typical use: diff a `mimic` run against a real OpenAI run to see
    where a live LLM disagrees with the strict reference.

    Writes `output_md_path` if given; otherwise returns the result dict."""
    a = json.loads(Path(bundle_a_json).read_text(encoding="utf-8"))
    b = json.loads(Path(bundle_b_json).read_text(encoding="utf-8"))

    def _q_map(bundle: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {q.get("run_label"): q for q in (bundle.get("questions") or []) if q.get("run_label")}

    a_q = _q_map(a)
    b_q = _q_map(b)
    labels = sorted(set(a_q.keys()) | set(b_q.keys()))

    per_q: List[Dict[str, Any]] = []
    for lbl in labels:
        aa = a_q.get(lbl) or {}
        bb = b_q.get(lbl) or {}

        def _ids(q: Dict[str, Any]) -> Set[str]:
            eff = q.get("llm_answer_effective") or (q.get("llm_response") or {}).get("parsed") or {}
            return {i.get("id") for i in (eff.get("graph_proven_items") or []) if i.get("id")}

        a_ids = _ids(aa)
        b_ids = _ids(bb)
        common = sorted(a_ids & b_ids)
        only_a = sorted(a_ids - b_ids)
        only_b = sorted(b_ids - a_ids)

        def _tokens(q: Dict[str, Any]) -> int:
            return int(((q.get("llm_response") or {}).get("usage") or {}).get("total_tokens") or 0)

        per_q.append({
            "question_id": lbl,
            "a_count": len(a_ids),
            "b_count": len(b_ids),
            "common_count": len(common),
            "only_in_a": only_a,
            "only_in_b": only_b,
            "a_tokens": _tokens(aa),
            "b_tokens": _tokens(bb),
        })

    result = {
        "a": {"run_id": a.get("run_id"), "mode": a.get("mode"), "totals": a.get("totals", {})},
        "b": {"run_id": b.get("run_id"), "mode": b.get("mode"), "totals": b.get("totals", {})},
        "per_question": per_q,
    }

    if output_md_path is not None:
        lines: List[str] = [
            f"# Run diff — `{a.get('run_id')}` vs `{b.get('run_id')}`",
            "",
            f"- **A:** `{a.get('run_id')}` (mode `{a.get('mode')}`)",
            f"- **B:** `{b.get('run_id')}` (mode `{b.get('mode')}`)",
            "",
            "## Per-question comparison",
            "",
            "| Q | A claims | B claims | Common | Only in A | Only in B | A tokens | B tokens |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for q in per_q:
            lines.append(
                f"| {q['question_id']} | {q['a_count']} | {q['b_count']} | "
                f"{q['common_count']} | {len(q['only_in_a'])} | {len(q['only_in_b'])} | "
                f"{q['a_tokens']:,} | {q['b_tokens']:,} |"
            )
        details_needed = [q for q in per_q if q["only_in_a"] or q["only_in_b"]]
        if details_needed:
            lines.append("")
            lines.append("## Where they differ")
            for q in details_needed:
                lines.append("")
                lines.append(f"### {q['question_id']}")
                if q["only_in_a"]:
                    lines.append("**Only in A:**")
                    for i in q["only_in_a"]:
                        lines.append(f"- `{i}`")
                if q["only_in_b"]:
                    lines.append("**Only in B:**")
                    for i in q["only_in_b"]:
                        lines.append(f"- `{i}`")
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip() + "\n")
        result["md_path"] = str(output_md_path)

    return result


def compare_run_to_ground_truth(
    bundle: RunBundle,
    ground_truth_path: str | Path = "ground_truth.json",
    logs_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare a bundle's effective answers to a ground-truth spec and
    emit:

      logs/<run_id>_ground_truth_comparison.json
      output/<run_id>_ground_truth_comparison.md

    Ground truth is scored on `graph_proven_items` ids only (review_items
    are free-form reviewer notes, not a test target). A question passes
    iff the effective-answer set equals the expected set exactly. The
    effective answer is post auto-demote, so items that got demoted by
    the validator count as "not claimed".

    Returns a dict with at least: `all_passed` (bool), `gt_json`, `gt_md`.
    """
    logs_dir = logs_dir or bundle.logs_dir
    output_dir = output_dir or bundle.output_dir
    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    gt_raw = json.loads(Path(ground_truth_path).read_text(encoding="utf-8"))
    per_q: List[Dict[str, Any]] = []
    all_passed = True

    for run in bundle.runs:
        qid = run.get("run_label")
        spec = gt_raw.get(qid) if qid else None
        if not spec or not isinstance(spec, dict):
            continue
        expected = set(spec.get("expected_graph_proven_ids") or [])
        score_mode = (spec.get("score_mode") or "exact").strip().lower()
        if score_mode not in {"exact", "minimum"}:
            score_mode = "exact"
        effective = run.get("llm_answer_effective") or run.get("llm_answer") or {}
        got = {
            item.get("id")
            for item in (effective.get("graph_proven_items") or [])
            if item.get("id")
        }
        extra = sorted(got - expected)
        missing = sorted(expected - got)
        # "exact"   — sets must match exactly
        # "minimum" — every expected id must be present; extras are allowed
        if score_mode == "minimum":
            passed = not missing
        else:
            passed = not extra and not missing
        per_q.append({
            "question_id": qid,
            "score_mode": score_mode,
            "passed": passed,
            "expected": sorted(expected),
            "got": sorted(got),
            "extra": extra,
            "missing": missing,
        })
        if not passed:
            all_passed = False

    report = {
        "run_id": bundle.run_id,
        "mode": bundle.mode,
        "ground_truth_path": str(ground_truth_path),
        "all_passed": all_passed,
        "totals": bundle.totals(),
        "per_question": per_q,
    }
    json_path = os.path.join(logs_dir, f"{bundle.run_id}_ground_truth_comparison.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(report), f, indent=2, ensure_ascii=False)

    # Prose MD
    lines: List[str] = [
        f"# {bundle.run_id} — ground truth comparison",
        "",
        f"- **Mode:** {bundle.mode}",
        f"- **Ground truth:** `{ground_truth_path}`",
        f"- **Overall:** **{'PASS' if all_passed else 'FAIL'}**",
        "",
        "| Q | Mode | Status | Expected | Got | Extra | Missing |",
        "|---|---|---|---|---|---|---|",
    ]
    for q in per_q:
        status = "PASS" if q["passed"] else "FAIL"
        lines.append(
            f"| {q['question_id']} | {q.get('score_mode','exact')} | {status} | "
            f"{len(q['expected'])} | {len(q['got'])} | {len(q['extra'])} | "
            f"{len(q['missing'])} |"
        )
    fails = [q for q in per_q if not q["passed"]]
    if fails:
        lines.append("")
        lines.append("## Failures")
        for q in fails:
            lines.append("")
            lines.append(f"### {q['question_id']}")
            if q["missing"]:
                lines.append("**Missing from the run's graph_proven_items:**")
                for i in q["missing"]:
                    lines.append(f"- `{i}`")
            if q["extra"]:
                lines.append("**Unexpectedly in the run's graph_proven_items:**")
                for i in q["extra"]:
                    lines.append(f"- `{i}`")
    md_path = os.path.join(output_dir, f"{bundle.run_id}_ground_truth_comparison.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")

    return {"all_passed": all_passed, "gt_json": json_path, "gt_md": md_path, "per_question": per_q}


def save_run_bundle(bundle: RunBundle, logs_dir: str = "logs", output_dir: str = "output") -> Dict[str, str]:
    """Aggregated-layout writer: one JSON + one prose MD for the whole run."""
    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(logs_dir, f"{bundle.run_id}.json")
    md_path = os.path.join(output_dir, f"{bundle.run_id}.md")

    record: Dict[str, Any] = {
        "run_id": bundle.run_id,
        "mode": bundle.mode,
        "timestamp_utc": bundle.timestamp_utc,
        "graph_path": bundle.graph_path,
        "metamodel_path": bundle.metamodel_path,
        "layout": bundle.layout,
        "totals": bundle.totals(),
        "questions": [],
    }
    for r in bundle.runs:
        resp = r.get("llm_response") or {}
        record["questions"].append({
            "run_label": r.get("run_label"),
            "question_text": r.get("question_text"),
            "llm_status": r.get("llm_status"),
            "planner": r.get("planner_diagnostics"),
            "compact_view": _json_safe(r.get("compact_view")),
            "evidence_packet": _json_safe(r.get("evidence_packet")),
            "llm_response": None if not resp else {
                "provider": resp.get("provider"),
                "model": resp.get("model"),
                "content": resp.get("content"),
                "parsed": resp.get("parsed"),
                "usage": resp.get("usage"),
                "truncated": resp.get("truncated"),
                "parse_error": resp.get("parse_error"),
            },
            "llm_answer_effective": _json_safe(r.get("llm_answer_effective")),
            "llm_validation": _json_safe(r.get("llm_validation")),
        })
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(record), f, indent=2, ensure_ascii=False)

    parts: List[str] = [
        f"# {bundle.run_id}",
        "",
        f"- **Mode:** {bundle.mode}",
        f"- **Timestamp (UTC):** {bundle.timestamp_utc}",
        f"- **Questions:** {len(bundle.runs)}",
        f"- **Tokens:** {format_usage(bundle.totals())}",
        "",
        "## Run summary",
        "",
        "| Q | Grounded | Claims | Auto-demoted | Structural issues | Tokens |",
        "|---|---|---|---|---|---|",
    ]
    for r in bundle.runs:
        v = r.get("llm_validation") or {}
        resp = r.get("llm_response") or {}
        u = resp.get("usage") or {}
        grounded_flag = "yes" if v.get("grounded") else "no"
        parts.append(
            f"| {r.get('run_label','?')} | {grounded_flag} | "
            f"{v.get('claim_count', 0)} | {len(v.get('auto_demoted') or [])} | "
            f"{len(v.get('structural_issues') or [])} | {u.get('total_tokens', 0):,} |"
        )
    parts.append("")
    for i, r in enumerate(bundle.runs):
        parts.append(_render_answer_prose(r))
        if i < len(bundle.runs) - 1:
            parts.append("\n---\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts).rstrip() + "\n")

    return {"run_json": json_path, "run_md": md_path}
