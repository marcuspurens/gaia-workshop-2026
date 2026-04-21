"""Environment loading and LLM provider configuration.

Supports two providers:
    - openai   (Responses API)
    - lmstudio (local chat/completions-compatible server)

Call flow::

    resolve_llm_config(provider, model)      # merges profile + env
    ok, note = llm_config_ready(config)      # pre-flight check
    analyze_with_llm(..., **config)          # see llm_client module
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict, Tuple


def load_local_env(env_path: str | Path = ".env") -> Dict[str, str]:
    """Load `KEY=VALUE` lines from a .env file into os.environ (no overwrite)."""
    path = Path(env_path)
    loaded: Dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
        loaded[key] = os.environ.get(key, value)
    return loaded


MODEL_PROFILES = {
    "openai:gpt-5-mini":         {"provider": "openai",   "api_style": "responses",        "base_url": "https://api.openai.com/v1", "supports_reasoning_effort": True,  "default_reasoning_effort": "none"},
    "openai:gpt-5.1":            {"provider": "openai",   "api_style": "responses",        "base_url": "https://api.openai.com/v1", "supports_reasoning_effort": True,  "default_reasoning_effort": "none"},
    "lmstudio:qwen3-14b@q3_k_l": {"provider": "lmstudio", "api_style": "chat_completions", "base_url": "http://localhost:1234/v1",  "supports_reasoning_effort": False},
}


def resolve_llm_config(provider: str, model: str, env_path: str | Path = ".env", lmstudio_base_url: str = "http://localhost:1234/v1") -> Dict[str, Any]:
    provider = provider.lower().strip()
    load_local_env(env_path)
    profile = dict(MODEL_PROFILES.get(f"{provider}:{model}", {}))
    if provider == "openai":
        profile.setdefault("provider", "openai")
        profile.setdefault("api_style", "responses")
        profile.setdefault("base_url", "https://api.openai.com/v1")
        profile["model"] = model
        profile["api_key"] = os.getenv("OPENAI_API_KEY", "").strip()
        return profile
    if provider == "lmstudio":
        profile.setdefault("provider", "lmstudio")
        profile.setdefault("api_style", "chat_completions")
        profile["model"] = model
        profile["api_key"] = ""
        profile["base_url"] = lmstudio_base_url or profile.get("base_url", "http://localhost:1234/v1")
        return profile
    raise ValueError(f"Unsupported provider: {provider}")


def llm_config_ready(config: Dict[str, Any]) -> Tuple[bool, str]:
    provider = str(config.get("provider", "")).lower().strip()
    if provider == "lmstudio":
        base_url = str(config.get("base_url", "")).strip()
        if not base_url:
            return False, "LM Studio selected but the base URL is empty."
        return True, f"LM Studio selected at {base_url}."
    if provider == "openai":
        api_key = str(config.get("api_key", "")).strip()
        if not api_key:
            return False, "OpenAI selected but OPENAI_API_KEY is missing from .env."
        return True, "OpenAI selected and API key loaded from .env."
    return False, f"Unknown provider: {provider}"
