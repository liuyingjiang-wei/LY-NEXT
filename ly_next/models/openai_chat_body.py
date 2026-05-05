"""OpenAI Chat Completions request body assembly (provider-safe optional fields)."""

from __future__ import annotations

from typing import Any


def _get(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def _pick(overrides: dict[str, Any], config: dict[str, Any], keys: list[str]) -> Any:
    for k in keys:
        if overrides.get(k) is not None:
            return overrides[k]
    for k in keys:
        if config.get(k) is not None:
            return config[k]
    return None


def build_openai_chat_completions_body(
    messages: list[dict[str, Any]],
    config: dict[str, Any],
    overrides: dict[str, Any],
    *,
    default_model: str,
) -> dict[str, Any]:
    """
    Build the JSON body for POST .../chat/completions.

    Temperature and sampling-related fields are omitted unless explicitly set.
    Token limit follows ``token_field``: ``max_tokens`` | ``max_completion_tokens`` | ``both``.
    When ``token_field`` is unset, explicit ``max_completion_tokens`` in overrides/config
    selects ``max_completion_tokens``; otherwise ``max_tokens`` is sent (matches strict gateways).
    """
    temperature = _pick(overrides, config, ["temperature"])

    max_completion_explicit = _pick(
        overrides, config, ["max_completion_tokens", "maxCompletionTokens"]
    )
    max_tokens_only = _pick(overrides, config, ["max_tokens", "maxTokens"])
    if max_completion_explicit is not None:
        token_budget = max_completion_explicit
    else:
        token_budget = max_tokens_only

    token_field_raw = (
        (_pick(overrides, config, ["token_field", "tokenField"]) or "").strip().lower()
    )

    model = _pick(overrides, config, ["model", "chatModel"]) or default_model

    stream_val = _pick(overrides, config, ["stream"])
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": bool(stream_val) if stream_val is not None else False,
    }

    if temperature is not None:
        body["temperature"] = temperature

    if token_budget is not None:
        try:
            n = int(token_budget)
        except (TypeError, ValueError):
            n = token_budget
        use_both = token_field_raw == "both"
        use_mct = token_field_raw == "max_completion_tokens" or (
            not token_field_raw and max_completion_explicit is not None
        )
        if use_both:
            body["max_completion_tokens"] = n
            body["max_tokens"] = n
        elif use_mct:
            body["max_completion_tokens"] = n
        else:
            body["max_tokens"] = n

    optional_map = [
        ("top_p", ["top_p", "topP"]),
        ("presence_penalty", ["presence_penalty", "presencePenalty"]),
        ("frequency_penalty", ["frequency_penalty", "frequencyPenalty"]),
        ("stop", ["stop"]),
        ("response_format", ["response_format", "responseFormat"]),
        ("stream_options", ["stream_options", "streamOptions"]),
        ("seed", ["seed"]),
        ("n", ["n"]),
        ("service_tier", ["service_tier", "serviceTier"]),
        ("reasoning_effort", ["reasoning_effort", "reasoningEffort"]),
    ]
    for dest, from_keys in optional_map:
        v = _pick(overrides, config, from_keys)
        if v is not None:
            body[dest] = v

    extra = _pick(overrides, config, ["extra_body", "extraBody"])
    if isinstance(extra, dict):
        body.update(extra)
    eb_cfg = config.get("extra_body") or config.get("extraBody")
    if isinstance(eb_cfg, dict):
        body.update(eb_cfg)

    return body


def attach_tools(
    body: dict[str, Any],
    tools: list[dict[str, Any]] | None,
    tool_choice: str | None,
    parallel_tool_calls: bool | None,
) -> dict[str, Any]:
    if tools:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    if parallel_tool_calls is not None:
        body["parallel_tool_calls"] = parallel_tool_calls
    return body
