"""Anthropic Claude client factory + thin helpers for SmartForge AskAI.

Uses the official `anthropic` SDK (AsyncAnthropic) with model `claude-opus-4-8`.
When no API key is configured the helpers raise `LLMUnavailable`, which callers
turn into a graceful, deterministic fallback so the platform still runs offline.
"""

from __future__ import annotations

import json
from typing import Any, cast

from app.core import privacy
from app.core.config import settings


class LLMUnavailable(RuntimeError):
    """Raised when the Anthropic API key is not configured."""


_client: Any = None


def get_client() -> Any:
    """Return a lazily-created AsyncAnthropic client, or raise if unconfigured."""
    global _client
    if not settings.askai_enabled:
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
    if _client is None:
        from anthropic import AsyncAnthropic

        _client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _first_text(message: Any) -> str:
    for block in message.content:
        if getattr(block, "type", None) == "text":
            return cast(str, block.text)
    return ""


async def complete(
    *,
    system: str,
    user: str,
    max_tokens: int | None = None,
    sensitive_terms: list[str] | None = None,
) -> str:
    """Single-turn completion. Returns Claude's text answer.

    Privacy: PII (emails, phones, UUIDs) and any caller-supplied ``sensitive_terms``
    (e.g. customer/company names) are redacted to placeholders before the prompt
    leaves the process; the placeholders are restored in the returned text. So
    Anthropic only ever receives pseudonymized content. See ``app.core.privacy``.

    Adaptive thinking is left off (default on Opus 4.8) to keep chat latency low;
    the system prompt instructs Claude to answer directly. Refusals degrade to a
    safe message rather than raising.
    """
    client = get_client()
    mapping: dict[str, str] = {}
    system, mapping = privacy.scrub(system, mapping, sensitive_terms)
    user, mapping = privacy.scrub(user, mapping, sensitive_terms)
    message = await client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=max_tokens or settings.ANTHROPIC_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if message.stop_reason == "refusal":
        return "I'm unable to answer that request."
    return privacy.restore(_first_text(message), mapping)


async def extract_json(
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Structured extraction via output_config.format (json_schema)."""
    client = get_client()
    mapping: dict[str, str] = {}
    system, mapping = privacy.scrub(system, mapping)
    user, mapping = privacy.scrub(user, mapping)
    message = await client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=max_tokens or settings.ANTHROPIC_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = privacy.restore(_first_text(message), mapping)
    return json.loads(text) if text else {}
