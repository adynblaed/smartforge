"""Privacy gateway: minimize what leaves the backend for Claude / Anthropic.

Hosted LLM inference fundamentally requires plaintext to generate an answer, so
true zero-knowledge ("Anthropic can never see anything") is not achievable while
using a hosted model. This module gets as close as practical: it replaces PII and
caller-supplied sensitive terms (emails, phone numbers, raw UUIDs, customer /
company names) with stable placeholders *before* the prompt is sent, then restores
the real values in the answer shown to the user. Anthropic only ever receives
tokens like ``[CUSTOMER_1]`` / ``[EMAIL_2]``.

Transport to api.anthropic.com is already TLS-encrypted; combine this with an
org-level zero-data-retention agreement for the strongest posture.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_PH = re.compile(r"\[([A-Z]+)_(\d+)\]")

Mapping = dict[str, str]  # placeholder -> original value


def _seed_counters(mapping: Mapping) -> dict[str, int]:
    counters: dict[str, int] = {}
    for ph in mapping:
        m = _PH.fullmatch(ph)
        if m:
            counters[m.group(1)] = max(counters.get(m.group(1), 0), int(m.group(2)))
    return counters


def scrub(
    text: str, mapping: Mapping, extra_terms: list[str] | None = None
) -> tuple[str, Mapping]:
    """Replace sensitive values in ``text`` with placeholders, recording the
    reverse map in ``mapping`` (shared across calls so the same value always maps
    to the same placeholder within one request)."""
    if not text:
        return text, mapping
    rev = {v: k for k, v in mapping.items()}
    counters = _seed_counters(mapping)

    def token(kind: str, val: str) -> str:
        if val in rev:
            return rev[val]
        counters[kind] = counters.get(kind, 0) + 1
        ph = f"[{kind}_{counters[kind]}]"
        mapping[ph] = val
        rev[val] = ph
        return ph

    # Explicit sensitive terms first (e.g. customer / company names), longest
    # first so "Acme Robotics Inc" is matched before "Acme".
    for term in sorted(
        {t.strip() for t in (extra_terms or []) if t and len(t.strip()) >= 3},
        key=len,
        reverse=True,
    ):
        if term in text:
            text = text.replace(term, token("NAME", term))

    text = _EMAIL.sub(lambda m: token("EMAIL", m.group(0)), text)
    text = _PHONE.sub(lambda m: token("PHONE", m.group(0)), text)
    text = _UUID.sub(lambda m: token("ID", m.group(0)), text)
    return text, mapping


def restore(text: str, mapping: Mapping) -> str:
    """Swap placeholders back to their original values (longest first)."""
    if not text:
        return text
    for ph in sorted(mapping, key=len, reverse=True):
        text = text.replace(ph, mapping[ph])
    return text
