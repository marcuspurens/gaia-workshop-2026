# sw_trace — Trustworthy AI for Requirements Traceability

A metamodel-driven pipeline that answers engineering questions over a
SystemWeaver-style traceability graph using only a bounded, policy-filtered
subgraph. The LLM never sees the full graph — it only sees what the
deterministic extractor puts in front of it, and every claim it makes is
checked against that evidence.

## Repo layout

```
sw_trace/
├── pyproject.toml              # install as an editable package: pip install -e .
├── README.md                   # this file
├── src/sw_trace/               # the pipeline package
│   ├── __init__.py             # re-exports the public API
│   ├── paths.py                # project-rooted paths for data / eval / logs
│   ├── config.py               # LLM config + .env loader
│   ├── graph.py                # TraceGraph, brief()
│   ├── metamodel.py            # Metamodel, TypeAlias
│   ├── planner.py              # plan_question() — the rule-based planner
│   ├── extractor.py            # extract_candidate_subgraph()
│   ├── packet.py               # build_evidence_packet(), compact_answer_view()
│   ├── prompt.py               # strict JSON schema + build_prompt()
│   ├── llm_client.py           # analyze_with_llm(), UsageTracker
│   ├── validator.py            # validate_llm_output(), apply_auto_demotions()
│   ├── pipeline.py             # run_question(), run_from_question()
│   ├── artifacts.py            # per-run I/O + natural-language markdown
│   └── run_bundle.py           # RunBundle, token ledger, ground-truth diff
├── data/
│   ├── traceability_graph.json # the graph — ~4.9k nodes, ~15k edges
│   └── metamodel.json          # schema vocabulary + whitelists
├── eval/
│   ├── ground_truth.json       # expected graph_proven_items per question
│   └── self_eval.py            # build/validate harness (stand-in for a live LLM)
├── notebooks/
│   └── workshop.ipynb          # per-question cells or run end-to-end
├── docs/
│   ├── technical_report.md     # design narrative, pipeline, trade-offs
│   └── accuracy_report.md      # Q1–Q4 run report with numbers
└── logs/
    └── self_eval/              # per-question sidecars from the self-eval harness
```

Generated at runtime:

| Directory | Contents |
|---|---|
| `logs/` | JSON sidecars (packet, parsed answer, grounding report), plus the cumulative `token_usage_ledger.jsonl` and `token_usage_summary.json` |
| `output/` | Engineer-facing prose markdown — clean, id-stripped, reviewer-ready |

## The pipeline

```
question text
    │
    ▼   plan_question()                     # rule-based planner (workshop shortcut)
QuestionPolicy (root, targets, support, budgets, claim_relation_sids)
    │
    ▼   extract_candidate_subgraph()        # whitelist-constrained reachability + paths
bounded subgraph (+ warnings)
    │
    ▼   build_evidence_packet()             # packet with policy block, system constraints
evidence packet
    │
    ▼   analyze_with_llm()                  # strict JSON schema; OpenAI Responses or LM Studio
parsed answer
    │
    ▼   validate_llm_output()               # id check, name match, mutual exclusion,
    │                                        citation-triple check, policy-filtered
    │                                        back-chain-to-root BFS, truncation detection
    ▼   apply_auto_demotions()              # claims that don't back-chain to root
effective answer                            # move from graph_proven_items to review_items
    │
    ▼   artifacts._render_answer_prose()    # id-stripped natural-language markdown
engineer-facing output
```

## Quickstart

### 1. Install

```bash
# From the project root:
pip install -e .
```

This makes `sw_trace` importable from any directory — the notebook,
the self-eval harness, and any downstream scripts all use the same
`from sw_trace import ...` line.

### 2. Configure

Either an OpenAI API key in `.env` as `OPENAI_API_KEY=...`, or LM Studio
running locally at `http://localhost:1234/v1`.

### 3. Run the notebook

```bash
jupyter lab notebooks/workshop.ipynb
```

At the top:

```python
LLM_PROVIDER = "openai"        # or "lmstudio"
LLM_MODEL    = "gpt-5.1"       # or a local model id
RUN_LAYOUT   = "per_question"  # or "aggregated"
MODE_LABEL   = "openai_gpt51"  # becomes part of run file names
```

Then step through the cells, or Run All. The final cell prints the token
usage summary and calls `bundle.finalize()`, which:

1. Writes per-question files (if `RUN_LAYOUT == "per_question"`) or a
   single run-level bundle (if `"aggregated"`).
2. Appends one row per question to `logs/token_usage_ledger.jsonl`.
3. Regenerates `logs/token_usage_summary.json`.
4. If `eval/ground_truth.json` is present, runs
   `compare_run_to_ground_truth()` and writes a pass/fail report.

### 4. Or run the self-eval harness

The self-eval harness emits the exact packet + prompt that the notebook
would send to the LLM, and lets you hand-write an answer JSON for each
question before scoring it against `eval/ground_truth.json`:

```bash
python eval/self_eval.py build     # phase 1: emit packets + prompts
# write logs/self_eval/Q*_response.json by hand (or with a live LLM)
python eval/self_eval.py validate  # phase 3: validate + compare to ground truth
```



## Output layout

### `per_question` layout

Each question writes immediately:

```
logs/q<N>_packet.json      # bounded evidence packet + planner diagnostics + warnings
logs/q<N>_answer.json      # raw + parsed LLM answer + compact view
logs/q<N>_grounding.json   # grounding report (unsupported ids, auto-demoted, structural issues)
output/q<N>_answer.md      # clean prose for engineers — no ids, no JSON
```

Use when walking through questions one at a time in a workshop.

### `aggregated` layout

Per-question files are skipped. Instead, one bundle:

```
logs/run_<YYYYMMDD_HHMMSS>_<mode>.json       # every Q's packet/answer/grounding in one file
output/run_<YYYYMMDD_HHMMSS>_<mode>.md       # all prose answers + run summary table
```

Use for end-to-end runs and sharing a single file.

### Always written (both layouts)

```
logs/token_usage_ledger.jsonl                # append-only, one row per question per run
logs/token_usage_summary.json                # derived aggregate: totals by run / model / question
```

### If `eval/ground_truth.json` is present

```
logs/run_<ts>_<mode>_ground_truth_comparison.json
output/run_<ts>_<mode>_ground_truth_comparison.md
```

The MD contains a `PASS`/`FAIL` table and details for any failures.

## How to interpret outputs

### "Grounded"

The run is `grounded` iff every claim in the LLM answer back-verifies
against the evidence packet:

- Every id in `graph_proven_items` exists in the packet.
- Every claim's `name` matches the packet node's name.
- Every `item_type` is a known metamodel item type (enum-pinned).
- Every citation triple `(from, to, relation_sid)` is a real edge in
  the packet.
- No id appears in both `graph_proven_items` and `review_items`.
- The union of citations per claim forms a path from that claim's id
  to the declared `policy.root_id` using only relations in
  `policy.claim_relation_sids` (the validator filter — this is what
  keeps "cites SP0670 Function Inbox edges to sneak to root" from
  counting when the question asked for an SP0003/SP0006 trace).
- No id leakage in the prose fields that isn't in the packet.
- JSON parsed without truncation.

"Grounded" means *the answer is consistent with the packet*. It does
NOT mean *the answer is the right answer to the question* — the LLM
can still be too narrow or too broad, and the extractor can still
under-scope. Grounding is the cheap deterministic proxy for "not
hallucinated," not a correctness oracle.

### "review_items"

Items the LLM (or the validator, via auto-demote) considers not fully
supported under the stated criterion, but worth a human's eyes. The
reason is spelled out for each. Not scored by ground-truth comparison.

### "auto_demoted"

Claims the validator moved from `graph_proven_items` to `review_items`
because their citation chain didn't back-chain to the root through
policy-allowed relations. The LLM's original rationale is preserved in
the demotion reason so nothing is lost.

### "structural_issues"

Answer-shape problems that aren't fixable by demotion: JSON parse
errors, ids appearing in both lists, name mismatches, missing
citations, truncated output. When present, the run is marked
`grounded: false` and `review_required: true`.

## What's production-ready vs workshop shortcut

See `docs/technical_report.md` §3a for the full table. The 30-second version:

- **Green (production-ready):** graph loading, root disambiguation,
  whitelist-constrained reachability extraction, shortest-path root-anchoring,
  support-type expansion, edge dedup, warnings, claim-time sid
  extraction, strict-JSON LLM glue, all validator checks, auto-demote,
  prose renderer, run bundling, token ledger + summary, ground-truth
  comparison.

- **Yellow (workshop shortcut, each explicitly labeled in code):**
  - **Rule-based planner** in `sw_trace.planner.plan_question()` — a
    keyword-based mapper from question text to `QuestionPolicy`. In
    production replace with either a small LLM planner (seeing only
    the metamodel vocabulary + question, never node contents) or an
    NER + entity-linking pipeline.
  - **Type-alias phrase map** in `data/metamodel.json → type_aliases`.
    English phrase list; the LLM planner above replaces it.
  - **Coordination expansion regex** (`"X and Y requirements"` → two
    phrases). English-only heuristic.
  - **Generic extraction defaults** (`max_nodes=150 / max_edges=300`,
    no hop bound — the relation whitelist is what bounds reach).
    Single guard rail for every question; may need per-question tuning.

- **Red (hardcoded per Q1–Q4):** none. Removed during the "is the code
  cheating?" refactor. Nothing in the repo depends on knowing the
  answers.

## Re-using the pipeline on your own questions

1. Edit or add a question cell in the notebook. Make sure the question
   contains either an explicit node id (`x` followed by 15+ hex chars)
   or a quoted entity name that exists in your graph.
2. If the question names a specific trace relation convention, spell
   out the sids: "SP0003/SP0006 chain" or "ITRQ direct" — the planner
   picks these up automatically and the validator enforces them.
3. Run the cell. Check the planner diagnostics first, the compact
   view second, the grounding report third, and the prose MD last.
4. If `grounded: false`, open `logs/q<N>_grounding.json`: every
   failure is spelled out with ids and citation triples.

## Replacing the planner (production path)

The planner is the one "demo shortcut" that most limits the code.
To swap it:

1. Implement a `plan_question_with_llm(graph, metamodel, question_text)`
   that returns `(QuestionPolicy, PlannerDiagnostics)` — same shape as
   the current `plan_question()`.
2. The LLM call must see only the metamodel vocabulary and the
   question text, never node contents. This preserves the
   bounded-subgraph principle during analysis.
3. Wire it into `run_question()` behind a `PLANNER` flag
   (`rule_based` / `llm` / `auto`).

Everything downstream stays the same — extractor, validator, auto-demote,
renderer, bundle, ledger, ground truth.

## Known characteristics and limits

- The planner is English-only and needs an explicit anchor in the
  question (id or quoted name).
- Strict JSON mode on some local LM Studio models may not be honored;
  when that happens the validator flags `llm_json_parse_failed` and
  the run lands in review-required.
- Very large packets (hundreds of nodes) can hit model context windows;
  increase `MAX_TOKENS` or narrow the planner's target types.
- `max_nodes=150 / max_edges=300` is a single global guard rail (the
  relation whitelist is the primary bound on reach); per-question
  tuning is a valid next step if your real-world data is larger.
- Ground truth is scored only on `graph_proven_items` ids. `review_items`
  are free-form reviewer notes, not a test target.

## Token accounting

Every LLM call captures usage (input / output / total / reasoning) and
every question lands as a row in `logs/token_usage_ledger.jsonl`. Rows
are tagged with a `mode` so you can segment by provider/experiment.
`logs/token_usage_summary.json` aggregates by run, model, and question
— it's regenerated from the ledger on every `bundle.finalize()`, so it
stays in sync.

Mimic runs (no external LLM call, e.g. acting as the analysis LLM
yourself during development) show `provider: codex-mimic`,
`estimated: true`, and `output_tokens: 0` — easy to filter out when
reading the summary.

## Comparing two runs

```python
from sw_trace import diff_two_run_bundles

diff_two_run_bundles(
    "logs/run_20260417_120000_mimic.json",
    "logs/run_20260417_121500_openai_gpt51.json",
    output_md_path="output/diff_mimic_vs_gpt51.md",
)
```

Produces a per-question table of claim counts, differences, and token
spend. Useful when swapping planners or comparing models.
