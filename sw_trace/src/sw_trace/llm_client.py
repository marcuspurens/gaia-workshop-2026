"""LLM call with strict JSON output, plus usage accounting.

Supports OpenAI Responses API and LM Studio chat/completions. `analyze_with_llm`
is the single entry point; the helpers around it normalise truncation and
token-usage reporting into a common shape.
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .config import resolve_llm_config
from .prompt import ANSWER_JSON_SCHEMA, build_prompt


def _extract_openai_response_text(raw: Dict[str, Any]) -> str:
    parts: List[str] = []
    for item in raw.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            ctype = content.get("type")
            if ctype in {"output_text", "text"} and content.get("text"):
                parts.append(content["text"])
    text = "\n".join(p.strip() for p in parts if p and p.strip()).strip()
    if text:
        return text
    if isinstance(raw.get("output_text"), str) and raw.get("output_text").strip():
        return raw["output_text"].strip()
    raise RuntimeError(f"OpenAI response contained no extractable text. Keys: {sorted(raw.keys())}")


def analyze_with_llm(
    provider: str,
    model: str,
    packet: Dict[str, Any],
    api_key: str = "",
    base_url: str = "",
    temperature: float = 0.0,
    max_tokens: int = 2000,
    json_schema: Optional[Dict[str, Any]] = None,
    timeout: float = 300.0,
) -> Dict[str, Any]:
    config = resolve_llm_config(provider, model, lmstudio_base_url=base_url or "http://localhost:1234/v1")
    prompt = build_prompt(packet)
    schema = json_schema or ANSWER_JSON_SCHEMA
    api_style = config.get("api_style")

    if api_style == "chat_completions":
        url = config["base_url"].rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": "You are a careful engineering analysis assistant. Always respond with JSON matching the given schema."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "gaia_answer", "strict": True, "schema": schema},
            },
        }

    elif api_style == "responses":
        if not config.get("api_key"):
            raise RuntimeError("OpenAI selected but api_key is empty.")
        url = config["base_url"].rstrip("/") + "/responses"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {config['api_key']}"}
        payload = {
            "model": config["model"],
            "instructions": "You are a careful engineering analysis assistant. Always respond with JSON matching the given schema.",
            "input": prompt,
            "max_output_tokens": max_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "gaia_answer",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        if config.get("supports_reasoning_effort"):
            payload["reasoning"] = {"effort": config.get("default_reasoning_effort", "none")}

    else:
        raise RuntimeError(f"Unknown api_style: {api_style}")

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"{config['provider']} call failed: HTTP {exc.code}. {body[:1500]}") from exc
    except Exception as exc:
        raise RuntimeError(f"{config['provider']} call failed: {exc}") from exc

    if api_style == "responses":
        content = _extract_openai_response_text(raw)
    else:
        content = raw["choices"][0]["message"]["content"]

    parsed: Optional[Dict[str, Any]]
    parse_error: Optional[str] = None
    try:
        parsed = json.loads(content) if content else None
    except json.JSONDecodeError as exc:
        parsed = None
        parse_error = f"{exc.msg} at pos {exc.pos}"

    truncated, truncation_reason = _detect_truncation(raw, api_style)
    usage = _normalize_usage(raw, api_style)

    return {
        "provider": config["provider"],
        "model": config["model"],
        "content": content,
        "parsed": parsed,
        "parse_error": parse_error,
        "truncated": truncated,
        "truncation_reason": truncation_reason,
        "usage": usage,
        "raw": raw,
    }


def _detect_truncation(raw: Dict[str, Any], api_style: str) -> Tuple[bool, Optional[str]]:
    """Did the model stop because it ran out of output-token budget?

    OpenAI Responses API: `status == "incomplete"` and
    `incomplete_details.reason == "max_output_tokens"`.
    OpenAI / LM Studio chat/completions: `choices[0].finish_reason == "length"`.
    Returns (truncated, short reason string).
    """
    if api_style == "responses":
        status = raw.get("status")
        incomplete = raw.get("incomplete_details") or {}
        reason = incomplete.get("reason")
        if status == "incomplete" or reason:
            return True, reason or status or "incomplete"
        return False, None
    choice = (raw.get("choices") or [{}])[0]
    fr = choice.get("finish_reason")
    if fr in {"length", "max_tokens"}:
        return True, fr
    return False, None


def _normalize_usage(raw: Dict[str, Any], api_style: str) -> Dict[str, int]:
    """Extract token usage from a provider response into a common shape.

    OpenAI Responses API reports  : input_tokens / output_tokens / total_tokens
                                    plus output_tokens_details.reasoning_tokens
    OpenAI / LM Studio chat/completions reports:
                                    prompt_tokens / completion_tokens / total_tokens

    Returned keys (always present, zero if missing):
      input_tokens, output_tokens, total_tokens, reasoning_tokens
    """
    u = raw.get("usage") or {}
    if api_style == "responses":
        details = u.get("output_tokens_details") or {}
        return {
            "input_tokens": int(u.get("input_tokens") or 0),
            "output_tokens": int(u.get("output_tokens") or 0),
            "total_tokens": int(u.get("total_tokens") or 0),
            "reasoning_tokens": int(details.get("reasoning_tokens") or 0),
        }
    # chat/completions shape (LM Studio or OpenAI chat endpoint)
    return {
        "input_tokens": int(u.get("prompt_tokens") or 0),
        "output_tokens": int(u.get("completion_tokens") or 0),
        "total_tokens": int(u.get("total_tokens") or 0),
        "reasoning_tokens": 0,
    }


def format_usage(usage: Optional[Dict[str, int]]) -> str:
    """Render a usage dict as a one-line string. Safe on None."""
    if not usage:
        return "(no token usage reported)"
    pieces = [
        f"input={usage.get('input_tokens', 0):,}",
        f"output={usage.get('output_tokens', 0):,}",
        f"total={usage.get('total_tokens', 0):,}",
    ]
    reasoning = usage.get("reasoning_tokens") or 0
    if reasoning:
        pieces.append(f"reasoning={reasoning:,}")
    return " ".join(pieces)


class UsageTracker:
    """Accumulate token usage across multiple LLM calls.

    Typical workshop flow in the notebook::

        tracker = UsageTracker()
        tracker.record(run_q1)
        tracker.record(run_q2)
        print(tracker.summary())
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.totals: Dict[str, int] = {
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0,
        }

    def record(self, run: Dict[str, Any]) -> Dict[str, int]:
        """Add one run's usage to the running total. Returns this call's
        usage dict (zeroes if the run had no LLM response)."""
        usage: Dict[str, int] = {k: 0 for k in self.totals}
        response = run.get("llm_response") or {}
        u = response.get("usage")
        if u:
            for k in self.totals:
                usage[k] = int(u.get(k, 0) or 0)
                self.totals[k] += usage[k]
        self.calls.append({
            "label": run.get("run_label"),
            "provider": response.get("provider"),
            "model": response.get("model"),
            "usage": dict(usage),
        })
        return usage

    def summary(self) -> str:
        rows = [f"  {c['label'] or '?':<6} {c.get('provider') or '?'}/{c.get('model') or '?':<15} "
                f"{format_usage(c['usage'])}" for c in self.calls]
        head = "Token usage per call:" if rows else "Token usage: (no calls recorded)"
        total_line = f"  TOTAL                          {format_usage(self.totals)}" if rows else ""
        return "\n".join([head, *rows, total_line]).rstrip()
