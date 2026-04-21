"""Per-run artifact I/O: JSON sidecars + reviewer-facing markdown.

`save_run_artifacts()` writes three JSON files (packet, answer,
grounding) plus a prose markdown file per question. The markdown
purposely strips IDs and citation triples — those live in the JSON
sidecars; the markdown is what a human reviewer reads.

`_render_answer_prose()` is reused by the aggregated run bundle in
`run_bundle.py` so a single end-to-end run can concatenate the same
per-question prose sections into one document.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any, Dict, List


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, set):
        return sorted(_json_safe(v) for v in value)
    return value


_ID_IN_PARENS_RE = re.compile(r"\s*\(x[0-9A-Fa-f]{15,}\)")
_BARE_ID_RE = re.compile(r"\s*\bx[0-9A-Fa-f]{15,}\b")
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?\)])")
# After ID removal, a preposition may dangle right before punctuation or end
# of clause ("ITRQ to.", "via ;", "from and"). Strip it.
_DANGLING_PREP_BEFORE_PUNCT = re.compile(
    r"\s+(?:to|via|from|at|by|of|for|on|in)(?=\s*[.,;:!?\)]|\s*$)",
    re.IGNORECASE,
)
_DANGLING_PREP_BEFORE_CONJ = re.compile(
    r"\s+(?:to|via|from|at|by|of|for|on|in)(?=\s+(?:and|or|but)\b)",
    re.IGNORECASE,
)


def _strip_ids(text: str) -> str:
    """Remove node-id tokens from free-form text. IDs live in the JSON
    sidecars; the MD is for humans."""
    if not text:
        return text
    t = _ID_IN_PARENS_RE.sub("", text)
    t = _BARE_ID_RE.sub("", t)
    t = _DANGLING_PREP_BEFORE_PUNCT.sub("", t)
    t = _DANGLING_PREP_BEFORE_CONJ.sub("", t)
    t = _MULTISPACE_RE.sub(" ", t)
    t = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", t)
    return t.strip()


def _render_answer_prose(run: Dict[str, Any]) -> str:
    """Turn the structured LLM answer into a clean, reviewer-facing markdown body.

    The markdown is intentionally free of IDs, citation triples, JSON dumps,
    grounding metrics, and planner internals — all of those live in the
    companion JSON logs (packet / answer / grounding). The markdown shows
    only the engineer-readable question and a natural-language answer.
    """
    lines: List[str] = []
    lines.append(f"# {run.get('run_label') or 'Run'}")
    lines.append("")
    lines.append("## Question")
    lines.append((run.get("question_text") or "").strip())
    lines.append("")
    lines.append("## Answer")

    # Prefer the post-demotion "effective" answer if present; fall back to
    # the raw LLM answer. The prose MD reflects what the pipeline considers
    # the usable result; the JSON sidecars preserve both originals.
    answer = run.get("llm_answer_effective") or run.get("llm_answer")
    llm_response = run.get("llm_response")
    llm_status = run.get("llm_status") or ""

    if not answer and llm_response and llm_response.get("content"):
        # Free text — LLM did not return schema-compliant JSON.
        lines.append("_The model did not return a structured answer. Raw text follows._")
        lines.append("")
        lines.append(str(llm_response["content"]).strip())
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    if not answer:
        lines.append("_No answer was produced._")
        if llm_status:
            lines.append("")
            lines.append(f"Reason: {llm_status}")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    summary = _strip_ids((answer.get("answer_summary") or "").strip())
    if summary:
        lines.append(summary)
        lines.append("")

    proven = answer.get("graph_proven_items") or []
    if proven:
        lines.append("### Findings supported by the evidence")
        for item in proven:
            name = (item.get("name") or "").strip() or "(unnamed)"
            itype = (item.get("item_type") or "").strip()
            head = f"- **{name}**" + (f" — _{itype}_" if itype else "")
            lines.append(head)
            rationale = _strip_ids((item.get("rationale") or "").strip())
            if rationale:
                lines.append(f"  - {rationale}")
        lines.append("")

    review = answer.get("review_items") or []
    if review:
        lines.append("### Items flagged for human review")
        for item in review:
            reason = _strip_ids((item.get("reason") or "").strip()) or "(no reason given)"
            lines.append(f"- {reason}")
        lines.append("")

    strength = (answer.get("support_strength") or "").strip()
    if strength:
        lines.append(f"**Confidence in the evidence:** {strength}")
        lines.append("")

    uncertainties = [_strip_ids(u.strip()) for u in (answer.get("uncertainties") or []) if (u or "").strip()]
    uncertainties = [u for u in uncertainties if u]
    if uncertainties:
        lines.append("### Caveats")
        for u in uncertainties:
            lines.append(f"- {u}")
        lines.append("")

    checks = [_strip_ids(c.strip()) for c in (answer.get("recommended_human_checks") or []) if (c or "").strip()]
    checks = [c for c in checks if c]
    if checks:
        lines.append("### Recommended human checks")
        for c in checks:
            lines.append(f"- {c}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save_run_artifacts(run: Dict[str, Any], logs_dir: str = "logs", output_dir: str = "output") -> Dict[str, str]:
    """Persist a run.

    Layout:
      logs/{label}_packet.json     — full evidence packet, planner diagnostics, warnings
      logs/{label}_answer.json     — parsed LLM answer + raw content + compact view
      logs/{label}_grounding.json  — grounding validation report
      output/{label}_answer.md     — reviewer-facing prose (question + natural-language answer)
    """
    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    label = re.sub(r"[^a-z0-9_\-]+", "_", (run.get("run_label") or "run").lower()).strip("_") or "run"
    packet_path = os.path.join(logs_dir, f"{label}_packet.json")
    answer_path = os.path.join(logs_dir, f"{label}_answer.json")
    grounding_path = os.path.join(logs_dir, f"{label}_grounding.json")
    md_path = os.path.join(output_dir, f"{label}_answer.md")

    with open(packet_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(run["evidence_packet"]), f, indent=2, ensure_ascii=False)

    answer_payload = {
        "run_label": run.get("run_label"),
        "question_text": run.get("question_text"),
        "llm_status": run.get("llm_status"),
        "planner": run.get("planner_diagnostics"),
        "llm_response": (
            None if run.get("llm_response") is None
            else {
                "provider": run["llm_response"].get("provider"),
                "model": run["llm_response"].get("model"),
                "content": run["llm_response"].get("content"),
                "parsed": run["llm_response"].get("parsed"),
                "usage": run["llm_response"].get("usage"),
            }
        ),
        # Effective answer is the LLM's output with policy-violating claims
        # (citations that do not back-chain to the declared root) demoted
        # into review_items. See llm_validation.auto_demoted for details.
        "llm_answer_effective": _json_safe(run.get("llm_answer_effective")),
        "compact_view": _json_safe(run.get("compact_view")),
    }
    with open(answer_path, "w", encoding="utf-8") as f:
        json.dump(answer_payload, f, indent=2, ensure_ascii=False)

    with open(grounding_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(run.get("llm_validation")), f, indent=2, ensure_ascii=False)

    md = _render_answer_prose(run)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    return {
        "packet": packet_path,
        "answer_json": answer_path,
        "grounding": grounding_path,
        "answer_md": md_path,
    }
