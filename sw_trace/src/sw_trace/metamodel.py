"""Metamodel — pure schema, no per-question answers.

Vocabulary, type aliases, relation whitelists, intent keywords, and generic
defaults. Loaded once at start-up from `data/metamodel.json` (or whichever
path the caller passes).
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set

from .paths import METAMODEL_PATH as DEFAULT_METAMODEL_PATH  # re-exported for back-compat


@dataclass
class TypeAlias:
    aliases: List[str]
    item_types: List[str]


@dataclass
class Metamodel:
    vocabulary_item_types: Set[str]
    vocabulary_relation_sids: Set[str]
    relation_labels: Dict[str, str]
    type_aliases: List[TypeAlias]
    intent_keywords: Dict[str, List[str]]
    defaults: Dict[str, int]
    # SystemWeaver-aligned fields (added in the relation-whitelist refactor)
    relation_schema: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    relation_whitelists: Dict[str, List[str]] = field(default_factory=dict)
    requirement_types: Set[str] = field(default_factory=set)
    requirement_level_values: Set[str] = field(default_factory=set)
    requirement_level_phrases: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_METAMODEL_PATH) -> "Metamodel":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        vocab = raw.get("vocabulary", {}) or {}
        aliases_raw = raw.get("type_aliases") or []
        aliases = [TypeAlias(aliases=list(a.get("aliases") or []), item_types=list(a.get("item_types") or [])) for a in aliases_raw]
        # Relation schema: strip the leading "_note" key if present.
        rel_schema = {k: v for k, v in (raw.get("relation_schema") or {}).items() if not k.startswith("_")}
        rel_whitelists = {k: list(v) for k, v in (raw.get("relation_whitelists") or {}).items() if not k.startswith("_")}
        req_levels_raw = raw.get("requirement_levels") or {}
        if isinstance(req_levels_raw, list):
            level_values = set(req_levels_raw)
            level_phrases: Dict[str, str] = {}
        else:
            level_values = set(req_levels_raw.get("values") or [])
            level_phrases = dict(req_levels_raw.get("phrase_to_level") or {})
        return cls(
            vocabulary_item_types=set(vocab.get("item_types") or []),
            vocabulary_relation_sids=set(vocab.get("relation_sids") or []),
            relation_labels=dict(raw.get("relation_labels") or {}),
            type_aliases=aliases,
            intent_keywords=dict(raw.get("intent_keywords") or {}),
            defaults=dict(raw.get("defaults") or {"max_nodes": 150, "max_edges": 300}),
            relation_schema=rel_schema,
            relation_whitelists=rel_whitelists,
            requirement_types=set(raw.get("requirement_types") or []),
            requirement_level_values=level_values,
            requirement_level_phrases={k.lower(): v for k, v in level_phrases.items()},
        )

    # --- convenience accessors used by the planner and extractor ---

    def whitelist(self, *names: str) -> Set[str]:
        """Return the union of the named relation whitelists.

        Unknown names are silently ignored. An empty union means "any
        relation" (back-compat with the pre-refactor behaviour)."""
        out: Set[str] = set()
        for n in names:
            for sid in self.relation_whitelists.get(n, ()):  # type: ignore[arg-type]
                out.add(sid)
        return out

    def edge_schema_violation(self, from_type: str, sid: str, to_type: str) -> bool:
        """True iff this edge does not fit the metamodel's relation_schema.

        Relations absent from the schema are not flagged — only relations
        with a declared schema whose endpoint types don't match."""
        spec = self.relation_schema.get(sid)
        if not spec:
            return False
        allowed_from = set(spec.get("from") or [])
        allowed_to = set(spec.get("to") or [])
        return (from_type not in allowed_from) or (to_type not in allowed_to)
