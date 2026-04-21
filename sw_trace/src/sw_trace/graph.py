"""Traceability graph in-memory model.

Loads the SystemWeaver-exported graph JSON into node / edge lookup tables.
`brief()` is the canonical way to shrink a full node dict down to the fields
that travel into the LLM prompt.
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TraceGraph:
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    id2node: Dict[str, Dict[str, Any]]
    out_edges: Dict[str, List[Dict[str, Any]]]
    in_edges: Dict[str, List[Dict[str, Any]]]

    @classmethod
    def from_json(cls, path: str | Path) -> "TraceGraph":
        # utf-8-sig strips an optional BOM (the enriched graph ships with one).
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        nodes = raw["nodes"]
        edges = raw["edges"]
        id2node = {n["id"]: n for n in nodes}
        out_edges: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        in_edges: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for e in edges:
            out_edges[e["from"]].append(e)
            in_edges[e["to"]].append(e)
        return cls(nodes=nodes, edges=edges, id2node=id2node, out_edges=dict(out_edges), in_edges=dict(in_edges))

    def find_by_name(self, name: str, item_type: Optional[str] = None) -> List[Dict[str, Any]]:
        name_norm = name.strip()
        matches = [
            n for n in self.nodes
            if (n.get("name") or "").strip() == name_norm
            and (item_type is None or n.get("item_type") == item_type)
        ]
        return matches

    def find_best(self, name: Optional[str] = None, item_type: Optional[str] = None, item_id: Optional[str] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Return (best_match, all_matches). Disambiguation prefers released
        status over work-in-progress, then the highest version number.

        Returned second element is the full match list (length 1 when no
        ambiguity) so the planner can surface the alternatives.
        """
        if item_id:
            if item_id not in self.id2node:
                raise KeyError(f"No node with id={item_id!r}")
            node = self.id2node[item_id]
            return node, [node]
        matches = self.find_by_name(name or "", item_type=item_type)
        if not matches and name:
            nl = name.strip().lower()
            matches = [
                n for n in self.nodes
                if (n.get("name") or "").strip().lower() == nl
                and (item_type is None or n.get("item_type") == item_type)
            ]
        if not matches:
            raise KeyError(f"No node found for name={name!r}, item_type={item_type!r}")
        if len(matches) > 1:
            # Prefer released/published status, then newest version number.
            # Status preference order (higher = preferred).
            status_rank = {"CSReleased": 3, "Released": 2, "Work": 1}
            def version_num(n: Dict[str, Any]) -> int:
                m = re.search(r"\((\d+)\)", n.get("version", ""))
                return int(m.group(1)) if m else -1
            matches = sorted(
                matches,
                key=lambda n: (status_rank.get(n.get("status", ""), 0), version_num(n)),
                reverse=True,
            )
        return matches[0], matches


def brief(node: Dict[str, Any], include_text: bool = True) -> Dict[str, Any]:
    out = {
        "id": node["id"],
        "type": node["item_type"],
        "name": node["name"],
        "version": node.get("version", ""),
        "status": node.get("status", ""),
    }
    if include_text:
        desc = (node.get("description") or "").strip()
        if desc:
            out["description"] = desc[:500]
    return out
