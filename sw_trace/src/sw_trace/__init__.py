"""sw_trace — SystemWeaver traceability assistant package.

Public API surface. Internal helpers (leading underscore names) are not
re-exported here; import them from their submodules if needed.

Typical use from a notebook / script:

    from sw_trace import (
        TraceGraph, Metamodel,
        resolve_llm_config, llm_config_ready,
        run_from_question, run_question,
        RunBundle, rebuild_token_summary,
    )

    graph = TraceGraph.from_json("data/traceability_graph.json")
    metamodel = Metamodel.load("data/metamodel.json")
    run = run_from_question(graph, metamodel, "...", llm_provider="lmstudio")
"""
from __future__ import annotations

# Path helpers — callers who want to resolve project-rooted file paths
# without hard-coding them in their own code.
from .paths import (
    PROJECT_ROOT,
    METAMODEL_PATH,
    GRAPH_PATH,
    GROUND_TRUTH_PATH,
    SELF_EVAL_LOGS_DIR,
)

# §1 config
from .config import (
    load_local_env,
    resolve_llm_config,
    llm_config_ready,
    MODEL_PROFILES,
)

# §2 graph
from .graph import TraceGraph, brief

# §3 metamodel
from .metamodel import Metamodel, TypeAlias

# §4 planner
from .planner import (
    QuestionPolicy,
    PlannerDiagnostics,
    plan_question,
    ID_IN_QUESTION,
)

# §5 extractor
from .extractor import extract_candidate_subgraph

# §6 packet
from .packet import build_evidence_packet, compact_answer_view

# §7 prompt
from .prompt import ANSWER_JSON_SCHEMA, build_answer_schema, build_prompt

# §8 LLM client
from .llm_client import (
    analyze_with_llm,
    format_usage,
    UsageTracker,
)

# §9 validator
from .validator import validate_llm_output, apply_auto_demotions

# §10 + §11 pipeline
from .pipeline import (
    run_question,
    run_from_question,
    build_connection_smoke_test_packet,
)

# §12 artifacts
from .artifacts import save_run_artifacts

# §13 run bundle / ledger / ground truth
from .run_bundle import (
    RunBundle,
    make_run_id,
    rebuild_token_summary,
    diff_two_run_bundles,
    compare_run_to_ground_truth,
    save_run_bundle,
    TOKEN_LEDGER_FILE,
    TOKEN_SUMMARY_FILE,
)

__all__ = [
    # paths
    "PROJECT_ROOT", "METAMODEL_PATH", "GRAPH_PATH", "GROUND_TRUTH_PATH", "SELF_EVAL_LOGS_DIR",
    # config
    "load_local_env", "resolve_llm_config", "llm_config_ready", "MODEL_PROFILES",
    # graph
    "TraceGraph", "brief",
    # metamodel
    "Metamodel", "TypeAlias",
    # planner
    "QuestionPolicy", "PlannerDiagnostics", "plan_question", "ID_IN_QUESTION",
    # extractor
    "extract_candidate_subgraph",
    # packet
    "build_evidence_packet", "compact_answer_view",
    # prompt
    "ANSWER_JSON_SCHEMA", "build_answer_schema", "build_prompt",
    # LLM client
    "analyze_with_llm", "format_usage", "UsageTracker",
    # validator
    "validate_llm_output", "apply_auto_demotions",
    # pipeline
    "run_question", "run_from_question", "build_connection_smoke_test_packet",
    # artifacts
    "save_run_artifacts",
    # run bundle
    "RunBundle", "make_run_id", "rebuild_token_summary",
    "diff_two_run_bundles", "compare_run_to_ground_truth", "save_run_bundle",
    "TOKEN_LEDGER_FILE", "TOKEN_SUMMARY_FILE",
]
