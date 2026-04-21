"""Rule-based question planner (workshop shortcut).

Turns a natural-language question into a `QuestionPolicy` that drives the
extractor and the validator.

=========================================================================
WORKSHOP SHORTCUT: RULE-BASED QUESTION PLANNER
=========================================================================
plan_question() is deliberately a small, deterministic keyword-based planner.
It turns a natural-language question into a QuestionPolicy by:
  - regex-extracting any node ids (xHEX format) from the question
  - regex-extracting quoted strings (the root is almost always quoted)
  - matching metamodel type-alias phrases against the question text
  - treating the alias phrase that appears closest-before a quoted string
    as the ROOT TYPE HINT (used to disambiguate duplicate names)
  - deriving TARGET item types = all matched types minus the root's own type
  - deriving SUPPORT item types = metamodel vocabulary minus targets minus
    root's type (so paths can pass through intermediate structural nodes)
  - picking a named relation whitelist (or a union) from the metamodel —
    requirement_trace / test_trace / structural_containment — based on the
    target types and intent keywords. Mirrors SystemWeaver's SidsToFollow.
  - applying generic node/edge guard rails from metamodel.defaults (no hop
    budget — reach is bounded by the chosen whitelist)

This is a stand-in for a real planner. In production replace plan_question()
with ONE of:

  (a) Small LLM planner:
      Prompt: "You plan metamodel-valid graph extraction. You see ONLY the
      metamodel vocabulary and the question text (never node contents).
      Return JSON matching the QuestionPolicy schema."
      This preserves the bounded-subgraph principle: the analysis LLM still
      sees only the extracted subgraph, and the planner LLM never sees nodes.

  (b) NER + entity linking:
      A tuned pipeline that understands the organization's naming
      conventions, abbreviations, and project slang. Better for regulated
      environments where auditability of the planning step is critical.

Why the workshop uses (c), this rule-based planner:
  - zero planner tokens (cost)
  - no sampling drift (reproducibility)
  - rules are ~120 lines, reviewable in a diff

Why replace it in real life:
  - limited to the English phrases enumerated in metamodel.type_aliases
  - cannot handle multi-entity questions, negations, or nested scoping
  - silently falls back to generic defaults if nothing matches
  - confused when a real requirement name contains a type word (e.g. a
    requirement literally named "Function start requirement")
=========================================================================
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .graph import TraceGraph
from .metamodel import Metamodel


ID_IN_QUESTION = re.compile(r"x[0-9A-Fa-f]{15,}")
# Back-compat private alias (used to be `_ID_IN_QUESTION` in the monolithic
# helpers module; exported here so the validator can reuse the same regex).
_ID_IN_QUESTION = ID_IN_QUESTION
_QUOTED = re.compile(r'"([^"]+)"')
# Light preprocessing: expand coordinated adjectives so the simple phrase
# matcher below sees each noun phrase as a whole. Example:
#   "function and design requirements"
#   -> "function requirements and design requirements"
# English-only heuristic; an LLM planner would not need this.
_COORD_PATTERN = re.compile(
    r"\b([A-Za-z]+)\s+and\s+([A-Za-z]+)\s+(requirements?|cases?|specifications?|artifacts?|specs?)\b",
    re.IGNORECASE,
)


def _preprocess_question(text: str) -> str:
    return _COORD_PATTERN.sub(r"\1 \3 and \2 \3", text)


@dataclass
class QuestionPolicy:
    """The output of the planner. Drives extraction AND post-hoc validation.

    Two distinct relation-sid sets:
      - `allowed_relation_sids` — controls which edges the extractor may
        traverse during BFS/path-finding. Empty set = any.
      - `claim_relation_sids`   — controls which relations may form a
        valid citation chain back to the root when the validator checks
        graph_proven_items entries. Empty set = any. Populated by the
        planner when the question text names specific sids (e.g. SP0003,
        ITRQ), otherwise left empty for back-compat.
    """
    question_text: str
    root_id: str
    max_nodes: int
    max_edges: int
    target_item_types: Set[str]
    support_item_types: Set[str]
    allowed_relation_sids: Set[str]  # extraction-time filter; empty = any
    claim_relation_sids: Set[str] = field(default_factory=set)  # validator filter

    @property
    def in_scope_item_types(self) -> Set[str]:
        return self.target_item_types | self.support_item_types

    def relation_allowed(self, relation_sid: str) -> bool:
        if not self.allowed_relation_sids:
            return True
        return relation_sid in self.allowed_relation_sids


@dataclass
class PlannerDiagnostics:
    """What the planner inferred, surfaced so reviewers can inspect it."""
    planner_kind: str = "rule_based"
    matched_id: Optional[str] = None
    matched_quoted_name: Optional[str] = None
    root_type_hint: Optional[str] = None
    root_resolved_by: str = ""
    matched_type_phrases: List[Dict[str, Any]] = field(default_factory=list)
    inferred_target_item_types: List[str] = field(default_factory=list)
    inferred_support_item_types: List[str] = field(default_factory=list)
    intent: Optional[str] = None
    chosen_whitelists: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "planner_kind": self.planner_kind,
            "matched_id": self.matched_id,
            "matched_quoted_name": self.matched_quoted_name,
            "root_type_hint": self.root_type_hint,
            "root_resolved_by": self.root_resolved_by,
            "matched_type_phrases": self.matched_type_phrases,
            "inferred_target_item_types": sorted(self.inferred_target_item_types),
            "inferred_support_item_types_count": len(self.inferred_support_item_types),
            "intent": self.intent,
            "chosen_whitelists": sorted(self.chosen_whitelists),
            "notes": self.notes,
        }


def _match_type_phrases(question_text: str, metamodel: Metamodel) -> List[Dict[str, Any]]:
    """Scan the question for any metamodel alias phrase. Returns a list of
    hits sorted by position, each with the phrase, the matched alias, the
    item_types it maps to, and the start index."""
    lower = question_text.lower()
    hits: List[Dict[str, Any]] = []
    for ta in metamodel.type_aliases:
        for alias in ta.aliases:
            alias_l = alias.lower()
            start = 0
            while True:
                idx = lower.find(alias_l, start)
                if idx < 0:
                    break
                # word-ish boundary check
                left_ok = (idx == 0) or not lower[idx - 1].isalnum()
                end = idx + len(alias_l)
                right_ok = (end == len(lower)) or not lower[end].isalnum()
                if left_ok and right_ok:
                    hits.append({
                        "phrase": alias,
                        "item_types": list(ta.item_types),
                        "start": idx,
                        "end": end,
                    })
                # Advance by 1 (not len(alias_l)) so overlapping or nested
                # aliases are both seen, e.g. "function requirement" contains
                # "requirement" which some alias groups also list.
                start = idx + 1
    hits.sort(key=lambda h: h["start"])
    return hits


def _detect_intent(question_text: str, metamodel: Metamodel) -> Optional[str]:
    lower = question_text.lower()
    for direction, keywords in metamodel.intent_keywords.items():
        for kw in keywords:
            if kw.lower() in lower:
                return direction
    return None


def _extract_mentioned_relation_sids(question_text: str, metamodel: Metamodel) -> Set[str]:
    """Scan the question for tokens that exactly match a relation_sid in
    the metamodel vocabulary. Word-boundary matching so e.g. "SP0003" in
    "SP0003/SP0006 chain" is found but "SP00031" would not spuriously
    match "SP0003". Returns a set of sids; empty if the question doesn't
    name any."""
    found: Set[str] = set()
    for sid in metamodel.vocabulary_relation_sids:
        if re.search(r"\b" + re.escape(sid) + r"\b", question_text):
            found.add(sid)
    return found


def _detect_requirement_levels(question_text: str, metamodel: Metamodel) -> Set[str]:
    """Scan the question for `requirement_level` cue phrases from the
    metamodel (e.g. "function requirement" -> "function"). Returns a set
    of level strings; empty if no cue phrase matched."""
    found: Set[str] = set()
    lower = question_text.lower()
    for phrase, level in metamodel.requirement_level_phrases.items():
        if phrase in lower:
            found.add(level)
    return found


def _types_for_levels(graph: TraceGraph, levels: Set[str]) -> Set[str]:
    """Return the distinct item_types present in the graph for nodes whose
    is_requirement_type is True and whose requirement_level is in the
    given set. This lets the planner pin targets to exactly the kind of
    requirement the question is about (e.g. "function" -> the specific
    Function Requirement types present in this graph)."""
    types: Set[str] = set()
    for n in graph.nodes:
        if not n.get("is_requirement_type"):
            continue
        if n.get("requirement_level") in levels:
            it = n.get("item_type")
            if it:
                types.add(it)
    return types


def _pick_whitelists(
    metamodel: Metamodel,
    targets: Set[str],
    root_type: Optional[str],
    question_text: str,
) -> Set[str]:
    """Decide which named whitelists in metamodel.relation_whitelists to
    apply for this question. Mirrors SystemWeaver's SidsToFollow pattern.

    Rules (all additive — the union is used):
      - Any requirement-type target (or root)  -> requirement_trace
      - Any Test Case / Test Specification target -> test_trace
      - Impact-style phrasing (affected / impact / removed / tightened)
        -> also include structural_containment so upstream containment
        edges (Function Inbox / Function Specification) are walked —
        BUT only when the root is a Function-level item. For Legal
        Requirement / Stakeholder Req roots, impact-via-removal stays
        on the requirement_trace chain: a Function / FRG / FunctionSpec
        does not semantically break when its regulatory or stakeholder
        parent is removed, so walking the containment hierarchy would
        drag in spurious co-scope items.
      - If nothing matches, return empty set (falls back to any-relation).

    FUTURE STEP — optional "semantic trace" whitelist (not implemented; intentionally
    deferred). If the exported graph ever carries a pre-collapsed semantic relation
    sid (e.g. a direct FR -> DR edge that summarises the SP0003 -> RTI -> SP0006
    pattern), register it in data/metamodel.json as a new named whitelist (e.g.
    "semantic_requirement_trace": ["<NEW_SID>"]) and add one rule below that picks
    it for pure requirement-to-requirement impact questions. Enforce a single-view
    invariant: never union "requirement_trace" and "semantic_requirement_trace" in
    the same extraction — choose one or the other, or the packet will show two
    overlapping traces of the same thing. Do NOT derive semantic edges inside this
    code: the collapse belongs in a graph-preprocessing step so the derivation rule
    stays auditable. See also the evaluation in docs/technical_report.md.
    """
    chosen: Set[str] = set()
    req_types = metamodel.requirement_types
    types_to_check = set(targets)
    if root_type:
        types_to_check.add(root_type)

    if types_to_check & req_types:
        if "requirement_trace" in metamodel.relation_whitelists:
            chosen.add("requirement_trace")

    if types_to_check & {"Test Case", "Test Specification"}:
        if "test_trace" in metamodel.relation_whitelists:
            chosen.add("test_trace")

    # Impact-phrasing detection: a cheap string match against common cue
    # words. When the engineer asks "what's affected" we also need the
    # upstream structural containment edges so we can answer via sibling
    # containers, not only direct trace items.
    # ANCHOR (legal/stakeholder-root narrowing):
    # We intentionally skip structural_containment when the root is a
    # Legal Requirement or Stakeholder Req. Removing a regulatory parent
    # does not delete the Function Inbox, Function, or FRGs beneath it —
    # those containers remain valid and their contents still exist. Only
    # items whose requirement-trace chain passes through the root break.
    # Walking SP0645/SP0648/SP0670/SP0672/SP0688/SP0691 from such a root
    # reaches the entire co-scope of the Function Inbox, which is
    # semantically "related" but not "impacted".
    lower = question_text.lower()
    impact_cues = ("affected", "impact", "removed", "tightened", "influenced")
    nonimpact_roots = {
        "Legal Requirement", "Legal requirements",
        "Stakeholder Req", "Stakeholder Requirements",
    }
    if any(c in lower for c in impact_cues) and root_type not in nonimpact_roots:
        if "structural_containment" in metamodel.relation_whitelists:
            chosen.add("structural_containment")

    return chosen


def plan_question(
    graph: TraceGraph,
    metamodel: Metamodel,
    question_text: str,
) -> Tuple[QuestionPolicy, PlannerDiagnostics]:
    """Rule-based planner. See the WORKSHOP SHORTCUT block above for scope and
    production-replacement guidance.

    Raises:
        ValueError: when the question is empty or has no root anchor
            (no node id, no quoted name).
        KeyError:   when a referenced id or quoted name can't be resolved
            against the graph; the exception message lists what was tried.
    """
    if not isinstance(question_text, str) or not question_text.strip():
        raise ValueError("plan_question requires a non-empty question string.")
    diag = PlannerDiagnostics()

    # ---- Step 1: find root candidates ----
    ids = ID_IN_QUESTION.findall(question_text)
    quotes = _QUOTED.findall(question_text)
    scan_text = _preprocess_question(question_text)
    type_hits = _match_type_phrases(scan_text, metamodel)
    diag.matched_type_phrases = [{"phrase": h["phrase"], "item_types": h["item_types"]} for h in type_hits]
    if scan_text != question_text:
        diag.notes.append("Applied coordination expansion to the question (e.g. 'X and Y requirements' -> 'X requirements and Y requirements').")

    root: Optional[Dict[str, Any]] = None
    root_type_hint: Optional[str] = None

    if ids:
        candidate_id = ids[0]
        if candidate_id not in graph.id2node:
            raise KeyError(
                f"Planner found id {candidate_id!r} in the question but it is not in the "
                f"loaded graph ({len(graph.id2node):,} nodes). Either the id is stale "
                f"relative to the current graph or the graph file is wrong."
            )
        root = graph.id2node[candidate_id]
        diag.matched_id = candidate_id
        diag.root_resolved_by = "id_in_question"

    elif quotes:
        name = quotes[0].strip()
        diag.matched_quoted_name = name
        # Use the type-alias phrase closest-before the quote as a type hint.
        # Positions are in the scan_text (post preprocessing), which also
        # contains the quote unchanged.
        lower = scan_text.lower()
        quote_pos = lower.find('"' + name.lower() + '"')
        if quote_pos < 0:
            quote_pos = lower.find(name.lower())
        before_hits = [h for h in type_hits if h["end"] <= (quote_pos if quote_pos >= 0 else 10**9)]
        if before_hits:
            # The last matched type-phrase before the quote wins. If the alias
            # maps to multiple types, we keep only those present in the
            # vocabulary and prefer a singular choice if possible.
            chosen = before_hits[-1]
            compatible = [t for t in chosen["item_types"] if t in metamodel.vocabulary_item_types]
            if compatible:
                root_type_hint = compatible[0]
        diag.root_type_hint = root_type_hint

        try:
            root, all_matches = graph.find_best(name=name, item_type=root_type_hint)
            diag.root_resolved_by = "quoted_name" + ("+type_hint" if root_type_hint else "")
        except KeyError:
            if root_type_hint is not None:
                root, all_matches = graph.find_best(name=name, item_type=None)
                diag.root_resolved_by = "quoted_name_type_hint_relaxed"
                diag.notes.append(f"Type hint {root_type_hint!r} did not match any node named {name!r}; relaxed.")
            else:
                raise
        if len(all_matches) > 1:
            diag.notes.append(
                f"Disambiguated {len(all_matches)} candidates for name={name!r}"
                + (f", type={root_type_hint!r}" if root_type_hint else "")
                + ": "
                + ", ".join(f"{m['id']} ({m.get('status','')}, v={m.get('version','')})" for m in all_matches)
                + f" -> picked {root['id']} (prefers CSReleased > Released > Work, then newest version)."
            )

    else:
        raise ValueError(
            "Planner could not find a root in the question. Provide either a node id of "
            'the form x<15+ hex chars> or a quoted entity name (e.g. "Engine start time") '
            "that exists in the graph. The rule-based planner does not do free-form entity "
            "recognition; replace it with the LLM/NER planner described in the WORKSHOP "
            "SHORTCUT block if your questions don't carry an explicit anchor."
        )

    # ---- Step 2: targets and support ----
    root_type = root.get("item_type")
    all_types_mentioned: Set[str] = set()
    for h in type_hits:
        for t in h["item_types"]:
            if t in metamodel.vocabulary_item_types:
                all_types_mentioned.add(t)

    # Use requirement_level phrases ("function requirements", "design
    # requirements", ...) to select specifically level-matched requirement
    # types when the enriched metadata supports it. Falls back to the
    # alias-based match when no level phrases are present.
    mentioned_levels = _detect_requirement_levels(question_text, metamodel)
    if mentioned_levels:
        diag.notes.append(f"Detected requirement levels in question: {sorted(mentioned_levels)}.")
        level_matched_types = _types_for_levels(graph, mentioned_levels)
        if level_matched_types:
            # Prefer level-matched types; keep any non-requirement mentions too
            # (e.g. "Test Case" would survive if also present).
            non_req_mentions = {
                t for t in all_types_mentioned
                if t not in metamodel.requirement_types
            }
            all_types_mentioned = level_matched_types | non_req_mentions

    targets = set(all_types_mentioned)
    if root_type:
        targets.discard(root_type)

    if not targets:
        # Conservative fallback: if the question doesn't mention any type, ask
        # for requirements broadly. This is a generic default, not an answer hint.
        targets = {"Function Requirement", "Design Requirement"} & metamodel.vocabulary_item_types
        diag.notes.append("No target types inferred from question; falling back to FR+DR.")

    support = set(metamodel.vocabulary_item_types) - targets
    if root_type:
        support.discard(root_type)

    # ---- Step 3: defaults (guard-rail only; see Step 5 for the real filter) ----
    # Reach is bounded by the chosen whitelist (Step 5); max_nodes / max_edges
    # are hard-stop guard rails in case a whitelist unexpectedly pulls in a
    # very large subgraph. There is no hop budget.
    max_nodes = int(metamodel.defaults.get("max_nodes", 150))
    max_edges = int(metamodel.defaults.get("max_edges", 300))

    # ---- Step 4: intent ----
    diag.intent = _detect_intent(question_text, metamodel)

    diag.inferred_target_item_types = sorted(targets)
    diag.inferred_support_item_types = sorted(support)

    # ---- Step 5: relation whitelist (SystemWeaver-aligned) ----
    # Pick named whitelists from the metamodel based on what the question
    # asks for. This mirrors SystemWeaver's "SidsToFollow" per-view
    # configuration: Trace View uses the requirement_trace set, Coverage
    # view uses the test_trace set, and impact questions use a union.
    chosen_whitelists = _pick_whitelists(metamodel, targets, root_type, question_text)
    if chosen_whitelists:
        diag.chosen_whitelists = sorted(chosen_whitelists)
        claim_relation_sids = metamodel.whitelist(*chosen_whitelists)
        diag.notes.append(
            f"Picked relation whitelist(s) {sorted(chosen_whitelists)} "
            f"→ sids {sorted(claim_relation_sids)}. Extractor and validator "
            f"will both restrict to this set."
        )
    else:
        # If the question names sids explicitly, honour that; otherwise leave
        # the set empty (any relation allowed).
        claim_relation_sids = _extract_mentioned_relation_sids(question_text, metamodel)
        if claim_relation_sids:
            diag.notes.append(
                f"No whitelist matched; using sids named in question text: "
                f"{sorted(claim_relation_sids)}."
            )

    # Extractor honours the same whitelist when one was chosen; this is what
    # makes extraction behave like SystemWeaver's Trace/Coverage view.
    allowed_relation_sids = set(claim_relation_sids)

    policy = QuestionPolicy(
        question_text=question_text,
        root_id=root["id"],
        max_nodes=max_nodes,
        max_edges=max_edges,
        target_item_types=targets,
        support_item_types=support,
        allowed_relation_sids=allowed_relation_sids,
        claim_relation_sids=claim_relation_sids,
    )
    return policy, diag
