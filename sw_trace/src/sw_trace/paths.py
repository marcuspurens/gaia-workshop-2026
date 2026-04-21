"""Project path resolution.

Single source of truth for where data, eval, and logs live. Any script or
module that reads a static file should import from here rather than using
a bare relative path.

Layout (from the project root):
    data/           metamodel.json, traceability_graph.json
    eval/           ground_truth.json, self_eval.py
    logs/self_eval/ per-question artefacts from self_eval.py
"""
from __future__ import annotations
from pathlib import Path

# src/sw_trace/paths.py -> project root is two parents up from this file.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

DATA_DIR: Path = PROJECT_ROOT / "data"
METAMODEL_PATH: Path = DATA_DIR / "metamodel.json"
GRAPH_PATH: Path = DATA_DIR / "traceability_graph.json"

EVAL_DIR: Path = PROJECT_ROOT / "eval"
GROUND_TRUTH_PATH: Path = EVAL_DIR / "ground_truth.json"

LOGS_DIR: Path = PROJECT_ROOT / "logs"
SELF_EVAL_LOGS_DIR: Path = LOGS_DIR / "self_eval"

DOCS_DIR: Path = PROJECT_ROOT / "docs"
NOTEBOOKS_DIR: Path = PROJECT_ROOT / "notebooks"
