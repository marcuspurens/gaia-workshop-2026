# Technical Report — Trustworthy AI for Requirements Traceability

## 1. Problem statement

Given:

- A SystemWeaver-style traceability graph (nodes = requirements /
  functions / designs / tests; edges = trace relations with typed
  `relation_sid` codes such as `SP0003`, `SP0006`, `ITRQ`, `ITTR`,
  `ITEC`).
- An engineer's question in natural language (e.g. "which function
  and design requirements will be affected if legal requirement X is
  removed?").

Produce:

- An answer that is **bounded** (the LLM sees a small, question-scoped
  subgraph, never the full graph), **grounded** (every claim cites
  real evidence), **reproducible** (deterministic before the LLM call,
  strict-schema after), and **auditable** (every pipeline step writes a
  sidecar file that can be checked by hand or by a future LLM).

## 2. Pipeline at a glance

```
question text
    │
    ▼   plan_question()                      # rule-based planner
QuestionPolicy (root, targets, support, budgets, claim_relation_sids)
    │
    ▼   extract_candidate_subgraph()         # whitelist-constrained reachability + paths
bounded subgraph (+ warnings)
    │
    ▼   build_evidence_packet()              # +policy block, +system constraints
evidence packet
    │
    ▼   analyze_with_llm()                   # strict JSON schema
parsed answer
    │
    ▼   validate_llm_output()                # grounding + policy checks
    ▼   apply_auto_demotions()               # demote policy-violating claims
effective answer
    │
    ▼   _render_answer_prose()               # id-stripped reviewer markdown
human-readable output
```

Every stage writes an inspectable artifact. No LLM call uses more than
the evidence packet it was shown.

## 3. Subgraph construction — the heart of the approach

The extractor is in `extract_candidate_subgraph()`. Its job is to
produce the smallest subgraph that can support an answer to the
question without leaking information the engineer didn't ask for.

**Approach:** relation-whitelist reachability search rooted at the
question's anchor, bidirectional, mirroring how SystemWeaver's own
Trace View, Design Trace View, and Coverage view work. The tool
publicly describes its traversal config as `SidsToFollow`, a set of
relation/part types that bounds the view. We model the same concept
in `data/metamodel.json → relation_whitelists` and pick one (or a
union) per question.

This is not promoted as better than BFS/Dijkstra/Steiner; it is simply
aligned with the data source's own view semantics.

### 3.1 Inputs

- `TraceGraph` — loaded from JSON (handles UTF-8 BOM); provides
  `id2node`, `out_edges[src]`, `in_edges[dst]`.
- `Metamodel` — parsed `data/metamodel.json`. Used for:
  - `vocabulary_item_types` / `vocabulary_relation_sids` — known vocab.
  - `relation_schema` — allowed `(from_type, to_type)` per sid.
  - `relation_whitelists` — named sid sets per question intent.
  - `requirement_types` / `requirement_level_values` — which nodes the
    enriched data already tags as requirements and at what level.
- `QuestionPolicy` — produced by the planner:
  - `root_id` — the anchor node (from id or quoted name in the question).
  - `target_item_types` — types the question asks about. When the
    question mentions a requirement-level phrase ("function
    requirements"), the planner pulls the matching types from the
    graph via `is_requirement_type=true` AND
    `requirement_level=="function"` rather than relying on a string
    alias list.
  - `support_item_types` — intermediate types needed to carry trace
    chains (Req Trace Item, Function Requirement Group, Function
    Specification, Test Specification, etc.).
  - `allowed_relation_sids` — the chosen whitelist. Empty means "any
    sid allowed" (back-compat fallback when the planner can't match).
  - `claim_relation_sids` — the same whitelist, used by the validator
    when checking that claim citations back-chain to root.
  - `max_nodes` / `max_edges` — guard rails, not primary filters.

### 3.2 Algorithm

```
Step 1  Whitelist reachability from root (bidirectional)
Step 2  For each target-type node, shortest path back to root within
        the reachable set (root-anchoring)
Step 3  Expand each node on any path by its support-type neighbors
Step 4  Dedup and bound edges; sort nodes; emit warnings
```

Each step in detail:

#### Step 1 — Whitelist reachability (`_reachability_policy`)

Breadth-first reachability from `root_id` — the traversal only follows
edges whose `relation_sid` is in `policy.allowed_relation_sids`, so it
stops automatically when the whitelisted relations run out. This is
the SystemWeaver behaviour. The only stopping condition that normally
fires is the `max_nodes` guard rail, and if it does, a
`max_nodes_guard_rail_tripped` warning is emitted so the engineer
knows the traversal was truncated.

Neighbors come from `_neighbors_policy`, which walks both `out_edges`
and `in_edges` (the graph is directed but the engineer's "affected by
/ related to" intuition is not).

An edge is walkable iff `policy.relation_allowed(relation_sid)`
returns true. When the whitelist is empty, any sid is walkable. When
the planner picked a named whitelist (e.g. `requirement_trace =
[SP0003, SP0006]` for a question like "what's traced from X"), only
those sids are walkable — and this is what gives the extractor the
SystemWeaver-view behaviour.

A neighbor is admitted iff its `item_type` is in
`policy.target_item_types ∪ policy.support_item_types`. This keeps
unrelated sub-trees of the graph out entirely.

#### Step 2 — Root-anchored target paths (`_shortest_path_within`)

For each id in the reachable set whose `item_type` is a target type,
compute the shortest path back to root **constrained to edges whose
endpoints are both in the reachable set** (and whose sid is in the
whitelist). This is the `candidate_paths` list in the packet and the
engineer's primary aid when reading the answer.

Each path's edges are gathered by `_path_edges` (prefers out-edges,
falls back to in-edges). Targets that are reachable but cannot be
path-connected to root go into
`warnings["targets_visible_but_not_root_anchored"]`.

#### Step 3 — Support-type expansion

For every node currently in the candidate set (root + path nodes),
add its neighbors whose `item_type` is in
`policy.support_item_types`. These are the structural context nodes
(groups, specs, test specifications) that carry the trace chains.

This is **one hop only** from the path set — deliberately shallow so
the packet doesn't balloon.

#### Step 4 — Edge dedup and bound

Edges are de-duplicated on `(from, to, relation_sid, relation_name)`
and hard-capped at `policy.max_edges` with the cap checked **before**
each append. Edges whose endpoints are not both in the final node set
are dropped.

### 3.2a — Why this is a good shape for traceability

Pros:
- **Matches SystemWeaver's own view semantics.** Engineers already
  reason in "which relations do I follow"; the extractor follows the
  same mental model.
- **Deterministic and auditable.** Given the same question and
  whitelist, the same packet is produced every time. Every decision
  (why this node? why this edge?) is one step of a named traversal.
- **Sharp packet sizes.** Because the whitelist stops when it dead-ends
  instead of exploring N hops of structurally-adjacent but
  semantically-irrelevant content, packets shrink dramatically when
  the question is trace-focused (Q3 dropped from 59 nodes to 10 after
  the whitelist refactor).
- **No hop budget guessing.** `max_nodes` exists only as a guard rail;
  with a suitable whitelist the traversal never hits it.

Known limits:
- **One whitelist per question.** Questions that mix trace and
  containment intent need to union whitelists; the planner does this
  for impact-phrased questions ("affected", "removed", "tightened") by
  combining `requirement_trace` with `structural_containment`. The
  union is intentionally suppressed when the root is a
  `Legal Requirement` or `Stakeholder Req`: removing a
  regulatory/stakeholder parent does not delete the Function Inbox,
  Function, or FRGs beneath it, so walking containment from such a
  root would reach the entire co-scope of the inbox rather than the
  items whose requirement-trace chain actually breaks.
- **Whitelist per intent is encoded by rule, not learned.** A future
  LLM planner could propose a per-question whitelist.
- **No edge weights.** All whitelisted edges are treated equally. If
  the engineer wants "prefer direct trace over structural even when
  both are in scope", the current extractor can't do it without edge
  costs.

### 3.3 Warnings emitted during extraction

The extractor is honest about what it had to omit or couldn't justify:

| Warning kind | Means |
|---|---|
| `unknown_item_types` | Types present in the subgraph that aren't in metamodel vocabulary (data drift signal) |
| `unknown_relation_sids` | Same, for relations |
| `edge_schema_violation` | An edge's `(from_type, sid, to_type)` triple doesn't match `metamodel.relation_schema`. Data drift against SystemWeaver's declared view semantics. |
| `target_item_types_not_reached` | Planner asked for `Test Case` but none reached from root |
| `targets_visible_but_not_root_anchored` | Target reached by traversal but no path within the allowed set |
| `duplicate_names_in_subgraph` | Multiple nodes share a display name — surfaces version/status ambiguities |
| `max_nodes_guard_rail_tripped` | Traversal stopped at `max_nodes` before the whitelist ran out. Expected answer ids may be outside the packet. |

### 3.4 Output shape (what goes into the packet)

```json
{
  "root_id": "x04000000000384CF",
  "nodes":   [ {id, type, name, version, status, description, hop}, ... ],
  "edges":   [ {from, to, relation_sid, relation_name}, ... ],
  "candidate_paths": [ [node_brief, ...], ... ],
  "warnings": [...],
  "packet_metadata": {
    "node_count": 14, "edge_count": 13,
    "target_types": [...], "support_types": [...],
    "allowed_relation_sids": [...],
    "candidate_path_count": 4,
    "reached_target_count": 3, "unreached_target_count": 0
  }
}
```

### 3.5 Worked example (Q1)

Question: *"Which function and design requirements will get affected
if the legal requirement 'UNECE Regulation No.155' gets removed?"*

- **Planner output:**
  - root = `x04000000000384CF` (resolved by matching the quoted name,
    disambiguated by the phrase "legal requirement" pointing at item
    type `Legal Requirement`).
  - Targets = {Function Requirement, Design Requirement}, matched via
    the `function` and `design` requirement levels in the enriched
    metadata.
  - Whitelists picked: `requirement_trace` only (`SP0003 + SP0006`).
    Although the question is impact-phrased, the root is a
    `Legal Requirement`, so the planner's Legal/Stakeholder carveout
    suppresses the `structural_containment` pairing. Traversal and
    validator both restrict to `{SP0003, SP0006}`.
- **Reachability:** grows out of UNECE R155 only through its Req
  Trace Items (`SP0003` / `SP0006`). Packet: 14 nodes, 13 edges.
- **Root-anchored paths:** 4 paths, e.g.
  `UNECE R155 → x0400000000038550 (Req Trace Item)
     → Engine start/stop → x0400000000039045 (Req Trace Item)
     → Key authentication before engine start`.
- **Support expansion:** Req Trace Items, Function Requirement
  Groups, Function Specifications get pulled in as context.
- **Warnings:** one `duplicate_names_in_subgraph` (UNECE R155 appears
  twice — once as the Legal Requirement, once as its own Req Trace
  Item).

The LLM then sees only this 54/63/11 packet. No other part of the
4,864-node graph is reachable to it during analysis.

Compared with the previous hop-bounded extraction (59/75/15), the new
whitelist extraction produces a slightly smaller, strictly-typed
packet and surfaces the two whitelists used as a diagnostic the
engineer can sanity-check.

### 3a. Production-ready vs workshop-shortcut by pipeline step

This table makes explicit which parts of the pipeline carry no
question-specific assumptions (green) and which are deliberate
workshop shortcuts with a named production replacement (yellow). It is
the answer to "what would I need to change to ship this?"

**Production-ready (no hardcoded Q1–Q4 assumptions):**

| Step | Where | Notes |
|---|---|---|
| Graph loading | `TraceGraph.from_json` | UTF-8 BOM tolerant |
| Root disambiguation (duplicate names) | `TraceGraph.find_best` | Status rank `CSReleased > Released > Work`, then newest version. Surfaced as a `PlannerDiagnostics.notes` entry when it fires |
| Whitelist-constrained reachability | `_reachability_policy` | Respects `allowed_relation_sids` (the chosen whitelist), admits only in-scope item types, bounded by `max_nodes` |
| Shortest root-anchored path extraction | `_shortest_path_within` | Per-target path; only uses edges with allowed relation sids |
| Support-type neighbor expansion | inside `extract_candidate_subgraph` | Adds structural context (Req Trace Items, FR Groups) one hop from the primary path set |
| Edge dedup + max_edges bound | inside `extract_candidate_subgraph` | Stable ordering, drops edges with endpoints not in the final node set |
| Warnings emission | inside `extract_candidate_subgraph` | Machine-readable; the engineer's first signal if the planner under-scoped |
| Claim-time sid extraction | `_extract_mentioned_relation_sids` | Scans question text for sids that are in the metamodel vocabulary, word-boundary matched |
| Evidence packet assembly | `build_evidence_packet` | Strict structure, carries policy block for the LLM and validator |

**Workshop shortcuts (labeled in code, named replacement available):**

| Item | Where | Shortcut rationale | Production alternative |
|---|---|---|---|
| Rule-based planner | `plan_question()` | Zero planner tokens, no LLM drift, ~120 lines of rules reviewable in a diff | (a) Small LLM planner receiving only metamodel + question text, or (b) NER + entity-linking tuned to org naming |
| Type-alias phrase map | `data/metamodel.json → type_aliases` | English phrase list; inputs only question text, no model call | Covered by the planner-replacement options above |
| Coordination expansion (`"X and Y requirements"` → `"X requirements and Y requirements"`) | `_COORD_PATTERN` in `sw_trace.planner` | English-only heuristic so the alias matcher doesn't miss coordinated adjectives | Same |
| Generic extraction defaults (`max_nodes=150 / max_edges=300`) | `data/metamodel.json → defaults` | Single guard rail per question; fits this dataset | Per-question tuning or an LLM-proposed budget |

What is **not** a shortcut anymore: no per-question hardcoded root,
target types, support types, or relation sid lists; no static
`QUESTION_TEXT / QUESTION_ROOT / QUESTION_HOPS` dicts; no question-id
lookup; no answers baked into code or metamodel. The notebook passes
question strings only.

## 4. The planner — where the question becomes policy

`plan_question()` is explicitly labeled a workshop shortcut (see the
`WORKSHOP SHORTCUT` comment block in Section 4 of the helpers). It is
rule-based for two reasons:

1. Zero planner tokens — predictable cost, no sampling drift.
2. ~120 lines of rules reviewable in a diff — auditable by reviewers.

### 4.1 What it does

1. Scan the question for explicit node ids (`xHEX` regex) — first id
   wins as root.
2. Scan for quoted strings — first quoted name becomes a candidate
   root if no id was found.
3. Scan for type-alias phrases from `metamodel.type_aliases` (e.g.
   "function requirement", "test cases"). The alias phrase closest
   **before** a quoted name is treated as a root-type hint for
   disambiguation.
4. Scan for `requirement_level` phrases (e.g. "function requirements",
   "design requirements") using `metamodel.requirement_levels.phrase_to_level`.
   When a level phrase is present, targets are pulled from the graph
   using `is_requirement_type=true AND requirement_level==level`
   rather than the alias list — robust against item-type variants in
   the data.
5. Coordination expansion: `"X and Y requirements"` becomes
   `"X requirements and Y requirements"` so that both adjectives are
   captured. Helper for the level-phrase and alias matchers.
6. Derive `target_item_types` from matched types minus the root's own
   type. `support_item_types = vocabulary - targets - root_type`.
7. **Pick relation whitelists from the metamodel** based on the
   question's target types and intent cues:
   - Requirement-typed target or root → `requirement_trace`
     (`SP0003 + SP0006`).
   - Test Case / Test Specification target → `test_trace`
     (`ITRQ + ITTR + ITEC + ITSI`).
   - Impact-phrased question (`"affected"`, `"impact"`, `"removed"`,
     `"tightened"`, `"influenced"`) → also include
     `structural_containment` so Function Inbox / Function
     Specification containment is walked — **unless** the root is a
     `Legal Requirement` or `Stakeholder Req`, in which case
     containment is intentionally skipped (removing such a root does
     not delete the containers beneath it; only its requirement-trace
     descendants are truly impacted).
   The union of these whitelists fills both
   `policy.allowed_relation_sids` (for extractor) and
   `policy.claim_relation_sids` (for validator) — one consistent set,
   same logic as SystemWeaver's `SidsToFollow`.
8. Budgets from `metamodel.defaults` — `max_nodes`, `max_edges` as
   guard rails. No hop budget: reach is bounded by the chosen whitelist.
9. Detect intent keywords (downstream/upstream) for diagnostics.

### 4.2 Root disambiguation

When multiple nodes share a name, `TraceGraph.find_best` prefers:

```
status rank: CSReleased > Released > Work
then:        newer version number wins
```

The chosen root and any competing candidates are recorded in
`PlannerDiagnostics.notes` so the engineer can see the decision.

### 4.3 Why the planner should eventually be replaced

The comment block lists two production replacements:

- A small LLM planner that sees only the metamodel vocabulary and the
  question text (never node contents). This preserves the
  bounded-subgraph principle for the analysis LLM.
- An NER + entity-linking pipeline tuned to the organization's naming
  conventions.

Limitations of the current rule-based planner: English-only keyword
lists, no handling of multi-entity questions, no understanding of
negations or scoping clauses, silent fallback to generic defaults when
nothing matches. These are acceptable for the workshop demo and not
acceptable in production.

## 5. LLM interaction — strict-JSON on both providers

### 5.1 Schema

`build_answer_schema(metamodel)` returns a JSON schema that:

- Requires exactly these top-level fields: `answer_summary`,
  `graph_proven_items`, `review_items`, `support_strength` (enum
  strong/partial/weak), `uncertainties`, `recommended_human_checks`.
- Requires each `graph_proven_items[i]` to carry id, name, item_type
  (enum-pinned to the metamodel vocabulary), rationale, and citations.
- Requires each citation to be a `{from, to, relation_sid}` triple.
- Uses `additionalProperties: false` everywhere.

### 5.2 Provider plumbing

Two API styles supported, both with strict JSON schema:

- OpenAI Responses API — `text.format = {type: "json_schema",
  strict: true, schema: ...}`. OpenAI enforces the schema server-side.
- LM Studio chat/completions — `response_format = {type: "json_schema",
  json_schema: {strict: true, schema: ...}}`.

### 5.3 Resilience

- `_detect_truncation` reads OpenAI `status`/`incomplete_details` and
  chat/completions `finish_reason`. On truncation,
  `run_from_question` auto-retries once with `max_tokens * 2`.
- `parse_error` is surfaced as a structural issue in the grounding
  report rather than silently producing `parsed: None`.
- Per-call `usage` is normalized into a common dict
  `{input_tokens, output_tokens, total_tokens, reasoning_tokens}`
  regardless of provider shape.

### 5.4 System prompt

`build_prompt()` wraps the packet with:

- A rules block forbidding invention, requiring id-exact copying,
  requiring at least one citation per claim, and stating the
  mutual-exclusion rule (an id may not be in both
  graph_proven_items and review_items).
- A policy-echo block (only present when `claim_relation_sids` is
  non-empty) restating the chain constraint in plain English.
- A **node-description usage block** telling the LLM to read the
  `description` field of each packet node for semantic
  understanding — disambiguating similar names, interpreting
  abbreviated titles, judging relevance — while forbidding the LLM
  from citing description text as evidence of a relation. Every
  graph_proven_items claim must still resolve to a real edge in
  `candidate_subgraph.edges`. If a description suggests a link the
  edges do not support, the LLM is instructed to surface that in
  `uncertainties` or `review_items` rather than inventing a citation.
  This block is always on; it adds semantic richness without
  changing the trust model.

## 6. Grounding and validation

`validate_llm_output()` runs eight checks against the packet:

1. JSON parsed and schema-compliant (via the strict-mode schema).
2. Every `id` in `graph_proven_items` exists in `packet.nodes`.
3. Every claim's `name` equals the packet node's `name` for that id
   (catches field shuffling observed in earlier GPT-5.1 runs).
4. Every `item_type` is within the metamodel enum (enforced at the
   schema level for compliant models; checked again here for safety).
5. Every citation triple `(from, to, relation_sid)` matches a real
   edge in `packet.edges`.
6. No id appears in both `graph_proven_items` and `review_items`
   (mutual exclusion).
7. **Root-anchor chain check (policy-aware):** the union of citations
   across all graph_proven_items must form a path from each claim's id
   back to the packet's declared `policy.root_id`, using only
   relations in `policy.claim_relation_sids` (when that list is
   non-empty). When it is empty (current default for natural
   questions), any cited relation contributes to the path graph.
8. No stray `xHEX` id appears in free-text fields that isn't in the
   packet (catches id leakage from training-data memory).

The report includes `grounded` (the top-level boolean),
`review_required`, `mentioned_ids`, `unsupported_text_ids`,
`unsupported_claim_ids`, `unsupported_citations`,
`root_anchored_claim_count`, `root_anchored_coverage`,
`structural_issues`, and `auto_demoted`.

### 6.1 Auto-demotion

`apply_auto_demotions()` produces an "effective" answer with
policy-violating claims moved into `review_items`. The LLM's original
rationale is preserved in the demotion reason so nothing is lost. Both
versions (original and effective) are written to the answer sidecar.

## 7. Output layout

Two layouts picked via `RUN_LAYOUT` at the top of the notebook:

### `per_question` (default)

Each question writes immediately on `bundle.add(run)`:

```
logs/q<N>_packet.json      # bounded evidence packet + planner diagnostics + warnings
logs/q<N>_answer.json      # raw + parsed LLM answer + compact view + usage
logs/q<N>_grounding.json   # grounding report
output/q<N>_answer.md      # clean prose — id-stripped, reviewer-facing
```

### `aggregated`

Per-question files are skipped; one run-level bundle:

```
logs/run_<YYYYMMDD_HHMMSS>_<mode>.json     # every Q in one machine-readable file
output/run_<YYYYMMDD_HHMMSS>_<mode>.md     # all prose answers + run-summary rollup
```

### Cumulative (always written)

```
logs/token_usage_ledger.jsonl              # append-only, one row per question per run
logs/token_usage_summary.json              # derived aggregate
```

### Ground-truth comparison (when `ground_truth.json` exists)

```
logs/<run_id>_ground_truth_comparison.json
output/<run_id>_ground_truth_comparison.md
```

## 8. Ground truth and scoring

`ground_truth.json` encodes the expected `graph_proven_items` id set
per question with a `score_mode`:

- `"exact"` — got set must equal expected. Used for Q2 where the
  answer is a definite list.
- `"minimum"` — every expected id must be present; extras are
  tolerated. Used for Q1, Q3, Q4 — open-ended impact questions where
  broader but defensible readings are still "correct".

`compare_run_to_ground_truth()` runs automatically in
`bundle.finalize()` when the file exists. Failures are enumerated with
ids and reasons in the sidecar MD.

## 9. Tokens and cost

Every real LLM call returns a normalized `usage` dict. `UsageTracker`
accumulates per-call totals and prints a per-call + running total in
the notebook. A per-row entry is appended to
`logs/token_usage_ledger.jsonl` tagged with `run_id`, `mode`, `model`,
`provider`, and `estimated` (true for mimic runs whose token counts
come from prompt length / 4).

`rebuild_token_summary()` re-reads the ledger at finalize time and
produces `logs/token_usage_summary.json` with totals by run, by model,
and by question — idempotent and append-safe.

## 10. What is pre-coded vs data-driven

| Element | Pre-coded? | Notes |
|---|---|---|
| Question text | No | Engineer types it; the notebook passes a string |
| Root node | No | Planner extracts from question (id or quoted name) |
| Target / support item types | No | Planner derives from matched phrases |
| Budgets (max_nodes, max_edges) | Yes (generic) | In `metamodel.defaults`, same for every question; reach is bounded by the whitelist, not a hop count |
| Type-alias phrase map | Yes | In `metamodel.type_aliases`; the only question-aware knob |
| Coordination expansion regex | Yes | English-only; "X and Y requirements" → both |
| Relation sid vocabulary | Yes | From metamodel; used by extractor + validator |
| LLM answer schema | Yes | Pinned to metamodel enum for item_type |
| Ground truth | Yes | Per-question expected ids + score_mode |

No Q1–Q5 answers are hardcoded anywhere. All pre-coded elements are
general-purpose (vocabulary, schema, defaults) rather than
question-specific.

## 11. Known limitations

- **Planner is English rule-based.** Cannot handle multi-entity
  questions, negation, scoping, abbreviations, or project slang. The
  Tier-4 replacement (LLM planner with access only to metamodel
  vocabulary) is designed but not yet implemented.
- **Single guard rail across all questions.** `max_nodes=150 /
  max_edges=300` (no hop bound — reach is bounded by the relation
  whitelist) is generous enough for this dataset, but may need
  tuning per question on larger graphs.
- **Local LM Studio speed.** 14B-class local models can exceed our
  120-second timeout for a full packet; workarounds include raising
  `timeout`, using a quantized smaller model, or routing to OpenAI.
- **Some models don't honor strict JSON mode.** The validator flags
  `llm_json_parse_failed` and the run lands in review-required so the
  engineer isn't shown a broken answer silently.
- **Review items are not scored.** They are free-form reviewer notes,
  not a test target. Ground truth checks only `graph_proven_items`.
- **Ground-truth comparison relies on ids.** If a node id changes
  between graph versions, the ground truth needs to be updated to
  match. Run-level artifacts carry the graph path so you can always
  tell which graph was used.

### 11.1 Deferred: optional "semantic trace" whitelist

Not implemented in this version. The whitelist mechanism already does
most of what a semantic layer would do: `requirement_trace` and
`test_trace` name the SystemWeaver patterns that matter for a given
question class, and the extractor respects them. A further collapsed
layer (e.g. a pre-derived direct `FR -> DR` edge that summarises
`FR --SP0003--> RTI --SP0006--> DR`) would only add value if packet
size becomes a binding constraint on larger graphs — which it is not
on this dataset (current packets are 8–14 nodes against a `max_nodes`
guard rail of 150).

If such a layer is ever introduced, the least-disruptive integration
is zero-code at the helpers level:

1. Add the collapsed sid to `data/metamodel.json` under
   `vocabulary_relation_sids`, `relation_schema`, and a new named
   entry in `relation_whitelists` (e.g.
   `"semantic_requirement_trace": ["<NEW_SID>"]`).
2. Add one rule to `_pick_whitelists()` that picks it for pure
   requirement-to-requirement impact questions.
3. Enforce a single-view invariant: do not union
   `requirement_trace` and `semantic_requirement_trace` in the same
   extraction — pick one or the other, otherwise the packet shows two
   overlapping traces of the same thing.

The derivation of the collapsed edges themselves is out of scope for
the helpers — it belongs in a separate graph-preprocessing step so the
collapse rule stays documented and auditable. A derived edge that is
not visible in source SystemWeaver can still be a valid citation,
provided the collapse rule is deterministic and version-pinned.

## 12. Current measurement (mimic loop, post-whitelist refactor)

With me acting as the analysis LLM — exercises the pipeline
end-to-end without external LLM cost:

| Q | Score mode | Packet (n/e/p) | Whitelists picked | Status |
|---|---|---|---|---|
| Q1 | exact   | 14 / 13 / 4   | requirement_trace                          | PASS |
| Q2 | exact   | 8 / 8 / 5     | requirement_trace + test_trace             | PASS |
| Q3 | minimum | 10 / 9 / 6    | requirement_trace                          | PASS |
| Q4 | minimum | 8 / 8 / 2     | requirement_trace + structural_containment | PASS |

Grounded: 4/4. Ground-truth PASS: 4/4.

This proves the **deterministic pipeline** (whitelist extractor +
validator + auto-demote + comparator + score modes) is correct
end-to-end. It does NOT prove external LLMs answer these questions
correctly — that requires a real notebook run against the target
provider.

Compared with the pre-refactor hop-bounded BFS packets (59/75/15,
17/17/11, 59/73/15, 48/55/9), the whitelist extractor produces much
tighter packets on test-trace (Q2) and stakeholder-trace (Q3)
questions, while preserving the broader context on impact-phrased
questions with non-regulatory roots (Q4). Q1's packet is kept tight
as well — the Legal/Stakeholder carveout (§3.2, §4.1 step 7)
suppresses the `structural_containment` pairing that would otherwise
be added for impact-phrased questions, because removing a Legal
Requirement does not delete the containers beneath it.

## 13. Design decisions worth naming

- **Bounded subgraph + strict schema + grounding check** is the
  smallest set of constraints that makes an answer auditable. Remove
  any one and the guarantees collapse: unbounded graph means no
  provenance, free-form output means no citations, no grounding means
  no proof of honesty.
- **Extraction is deterministic, analysis is stochastic.** We
  deliberately keep the LLM out of the extractor so the same question
  always produces the same packet. Variability lives in the LLM's
  answer over that packet — where we can audit it.
- **Grounding ≠ correctness.** The validator catches hallucination,
  not policy mistakes. Correctness against a reference requires a
  separate comparator. We have both, and we keep them separate in the
  UI (`grounded` vs ground-truth `passed`).
- **Auto-demotion instead of hard fail.** A sloppy but usable LLM
  answer is better than a dropped run — provided the audit trail
  (`auto_demoted` in grounding.json) records exactly what the
  pipeline corrected.
- **Ids stripped from the prose MD.** The markdown is for humans; ids
  belong in the JSON sidecar. If the reader wants the machine-readable
  evidence, it's one file away.
