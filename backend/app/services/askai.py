"""AskAI RAG service (Module 1C, 5A/5B): retrieval over knowledge_documents + Claude."""

from __future__ import annotations

import re
import uuid

from sqlmodel import Session, col, select

from app.core import llm
from app.core.vectorstore import vector_store
from app.models import (
    AskResponse,
    Customer,
    CustomerOrder,
    ForgeResponse,
    KnowledgeBase,
    KnowledgeDocument,
    Machine,
    PurchaseOrder,
    SimFocus,
    Sop,
    SopSection,
    SourceRef,
    Supplier,
    TelemetryEvent,
)
from app.services.machine_intelligence import recent_telemetry

_WORD = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def retrieve(
    session: Session, query: str, *, machine_id: uuid.UUID | None = None, k: int = 4
) -> list[KnowledgeDocument]:
    """Lightweight keyword retrieval over the knowledge corpus."""
    docs = list(session.exec(select(KnowledgeDocument)).all())
    q = _tokenize(query)

    def score(doc: KnowledgeDocument) -> float:
        text = f"{doc.title} {doc.tags or ''} {doc.content}"
        overlap = len(q & _tokenize(text))
        boost = 2.0 if machine_id and doc.machine_id == machine_id else 0.0
        return overlap + boost

    ranked = sorted(docs, key=score, reverse=True)
    return [d for d in ranked if score(d) > 0][:k] or ranked[:k]


def knowledge_bases(session: Session) -> list[KnowledgeBase]:
    """All user-authored Forge Facts — injected into every internal prompt."""
    return [
        kb
        for kb in session.exec(select(KnowledgeBase)).all()
        if (kb.content or "").strip()
    ]


# ----------------------------------------------------------------------------
# Standardized RAG retrieval. Source priority is STRICT and identical for the
# dedicated ForgeAI page and the site-wide agent popup:
#   1. SOPs (Standard Operating Procedures) — authoritative, always first.
#   2. Forge Facts (user-authored knowledge bases) — secondary, additive notes.
# Retrieval is deterministic (DB keyword scoring) so it ALWAYS surfaces an SOP
# that exists, and is augmented by Qdrant vector search + rerank when available.
# ----------------------------------------------------------------------------

_SOP_MENTION = re.compile(r"\bsops?\b")


def _mentions_sop(query: str) -> bool:
    return bool(_SOP_MENTION.search(query.lower()))


def _overlap(qtokens: set[str], text: str) -> int:
    return len(qtokens & _tokenize(text))


def retrieve_sops(session: Session, query: str, k: int = 4) -> list[SourceRef]:
    """SOPs are the first-class, authoritative source for every response.

    Deterministic keyword retrieval over every SOP section (so a named SOP is
    always found), reordered by Qdrant vector rerank when the store is up. When
    the query explicitly says "SOP"/"SOPs", SOPs are returned even on a weak
    keyword match so the assistant can never wrongly claim one doesn't exist.
    """
    qtokens = _tokenize(query)
    sops = {s.id: s for s in session.exec(select(Sop)).all()}
    if not sops:
        return []
    sections = list(
        session.exec(select(SopSection).order_by(col(SopSection.order_index))).all()
    )
    forced = _mentions_sop(query)

    scored: list[tuple[float, Sop, SopSection]] = []
    for sec in sections:
        sop = sops.get(sec.sop_id)
        if not sop:
            continue
        title_hit = _overlap(qtokens, f"{sop.code} {sop.title} {sop.summary}")
        body_hit = _overlap(qtokens, f"{sec.title} {sec.body}")
        # Title/identity matches dominate so the right SOP wins; body matches
        # then pick the most relevant chapter within it.
        score: float = title_hit * 3 + body_hit
        scored.append((float(score), sop, sec))
    scored.sort(key=lambda t: t[0], reverse=True)

    # Vector rerank signal (kind="sop"): blend in when the store is available.
    boost: dict[tuple[str | None, str | None], float] = {}
    for rank, hit in enumerate(vector_store.search(query, kind="sop", top_k=8)):
        boost[(hit.get("code"), hit.get("anchor"))] = 8.0 - rank
    if boost:
        scored = [
            (s + boost.get((sop.code, sec.anchor), 0.0), sop, sec)
            for (s, sop, sec) in scored
        ]
        scored.sort(key=lambda t: t[0], reverse=True)

    out: list[SourceRef] = []
    for score, sop, sec in scored:
        if score <= 0 and not forced:
            continue
        out.append(
            SourceRef(
                document_id=sop.id,
                title=f"{sop.code} §{sec.order_index + 1} — {sec.title}",
                kind="sop",
                code=sop.code,
                anchor=sec.anchor,
                snippet=f"**{sop.title}**\n\n{sec.body}",
            )
        )
        if len(out) >= k:
            break
    return out


def retrieve_forge_facts(session: Session, query: str, k: int = 4) -> list[SourceRef]:
    """Secondary, user-authored notes that augment (never override) SOPs."""
    hits = vector_store.search(query, kind="forge_fact")
    out: list[SourceRef] = []
    seen: set[str | None] = set()
    if hits:
        for h in hits:
            code = h.get("code") or h.get("doc_id") or h.get("name")
            if code in seen:
                continue
            seen.add(code)
            try:
                doc_id = uuid.UUID(str(code))
            except (ValueError, TypeError):
                doc_id = uuid.uuid4()
            out.append(
                SourceRef(
                    document_id=doc_id,
                    title=h.get("name", "Forge Fact"),
                    kind="forge_fact",
                    code=str(code),
                    snippet=h.get("text", ""),
                )
            )
            if len(out) >= k:
                break
        return out

    # Offline fallback: include the most relevant Forge Facts verbatim.
    qtokens = _tokenize(query)
    kbs = sorted(
        knowledge_bases(session),
        key=lambda kb: _overlap(qtokens, f"{kb.name} {kb.content}"),
        reverse=True,
    )
    for kb in kbs[:k]:
        out.append(
            SourceRef(
                document_id=kb.id,
                title=kb.name,
                kind="forge_fact",
                code=str(kb.id),
                snippet=(kb.content or "")[:1500],
            )
        )
    return out


# Shared directive so the popup and the dedicated page rank sources identically.
_SOURCE_PRIORITY = (
    "Source priority is STRICT: (1) Standard Operating Procedures (SOPs) are "
    "authoritative — always consult and cite them FIRST, by code and section "
    "(e.g. SOP-CNC-001 §4). (2) Forge Facts are secondary, user-authored notes "
    "that augment SOPs. If a Forge Fact conflicts with an SOP, follow the SOP and "
    "explicitly note the conflict; if they agree, you may note the agreement. "
    "Every SOP and Forge Fact provided below DOES exist in the knowledge base — "
    "never claim a provided SOP does not exist; if the user names an SOP, cite it."
)


def _rag_block(
    sop_sources: list[SourceRef],
    fact_sources: list[SourceRef],
    doc_block: str,
) -> str:
    parts: list[str] = []
    if sop_sources:
        parts.append(
            "=== STANDARD OPERATING PROCEDURES (authoritative — cite first) ==="
        )
        parts += [f"[SOP {s.code} — {s.title}]\n{s.snippet}" for s in sop_sources]
    if fact_sources:
        parts.append("=== FORGE FACTS (secondary, additive notes) ===")
        parts += [f"[Forge Fact: {s.title}]\n{s.snippet}" for s in fact_sources]
    if doc_block:
        parts.append("=== REFERENCE DOCUMENTS ===")
        parts.append(doc_block)
    return "\n\n".join(parts)


def reindex_rag(session: Session) -> dict[str, int]:
    """Re-vectorize ALL SOPs + Forge Facts into Qdrant from scratch (idempotent).

    Resets the collection first so no stale points survive. No-op (zeros) when
    the vector store is unavailable — retrieval still works deterministically.
    """
    vector_store.reset()
    secs_by_sop: dict[uuid.UUID, list[tuple[str, str, str]]] = {}
    for sec in session.exec(
        select(SopSection).order_by(col(SopSection.order_index))
    ).all():
        secs_by_sop.setdefault(sec.sop_id, []).append((sec.anchor, sec.title, sec.body))
    sop_chunks = sum(
        vector_store.upsert_sop(s.id, s.code, s.title, secs_by_sop.get(s.id, []))
        for s in session.exec(select(Sop)).all()
    )
    fact_chunks = sum(
        vector_store.upsert_kb(kb.id, kb.name, kb.content)
        for kb in session.exec(select(KnowledgeBase)).all()
    )
    return {"sop_chunks": sop_chunks, "fact_chunks": fact_chunks}


def _machine_context(session: Session, machine: Machine) -> str:
    history: list[TelemetryEvent] = recent_telemetry(session, machine.id, limit=5)
    latest = history[0] if history else None
    lines = [
        f"Machine {machine.code} ({machine.name}), type {machine.machine_type.value}",
        f"Status: {machine.status.value}, health score: {machine.health_score}",
        f"Maintenance state: {machine.maintenance_state.value}, runtime: {machine.runtime_hours}h",
    ]
    if latest:
        lines.append(
            f"Latest telemetry — temp {latest.temperature}°C, vibration {latest.vibration}, "
            f"fault {latest.fault_code or 'none'}, power {latest.power_draw}kW"
        )
    return "\n".join(lines)


def _fallback_answer(question: str, docs: list[KnowledgeDocument], ctx: str) -> str:
    parts = [f'Regarding "{question.strip()[:120]}" — based on the documentation:']
    if ctx:
        parts.append(ctx)
    for d in docs[:2]:
        snippet = d.content[:280].strip()
        parts.append(f"- From '{d.title}': {snippet}")
    parts.append(
        "(AskAI is running in offline mode — set ANTHROPIC_API_KEY for full AI answers.)"
    )
    return "\n".join(parts)


async def answer(
    session: Session,
    question: str,
    *,
    machine_id: uuid.UUID | None = None,
    customer_safe: bool = False,
) -> AskResponse:
    """Answer a question with retrieved sources; falls back gracefully offline.

    In customer-safe mode the internal knowledge base and machine telemetry are
    never retrieved or exposed — answers are grounded only in the order/status
    context supplied by the caller.
    """
    machine = (
        None
        if customer_safe
        else (session.get(Machine, machine_id) if machine_id else None)
    )
    ctx = _machine_context(session, machine) if machine else ""
    docs = [] if customer_safe else retrieve(session, question, machine_id=machine_id)
    # SOPs first (authoritative), then Forge Facts — never in customer-safe mode.
    sop_sources = [] if customer_safe else retrieve_sops(session, question)
    fact_sources = [] if customer_safe else retrieve_forge_facts(session, question)

    doc_block = "\n\n".join(f"[{d.title}]\n{d.content}" for d in docs)
    doc_sources = [
        SourceRef(document_id=d.id, title=d.title, kind=d.kind.value) for d in docs
    ]
    sources = sop_sources + fact_sources + doc_sources

    if customer_safe:
        system = (
            "You are SmartForge's customer support assistant. Answer ONLY using the "
            "provided order/status context. Never reveal internal costs, machine "
            "telemetry, staffing, or other customers' data. If you cannot answer "
            "from the context, say so and suggest contacting support."
        )
    else:
        system = (
            "You are SmartForge's plant operations and maintenance assistant. Use the "
            "machine context, SOPs, Forge Facts and documentation to give concise, "
            "actionable guidance. Cite which source informed your answer. Answer "
            "directly without preamble. " + _SOURCE_PRIORITY
        )

    user = (
        f"Question: {question}\n\nMachine context:\n{ctx}\n\n"
        f"{_rag_block(sop_sources, fact_sources, doc_block)}"
    )

    try:
        text = await llm.complete(
            system=system,
            user=user,
            max_tokens=900,
            sensitive_terms=sensitive_terms(session),
        )
        confidence = 0.9
    except llm.LLMUnavailable:
        text = _fallback_answer(question, docs, ctx)
        confidence = 0.4

    suggested = _suggest_actions(question, machine)
    return AskResponse(
        answer=text,
        sources=sources,
        suggested_actions=suggested,
        confidence=confidence,
    )


# ---- ForgeAI: general simulation assistant with an in-scene locator tool ----

# Keywords that map free text to a machine type.
_TYPE_HINTS = {
    "cnc_mill": ("cnc", "mill", "milling"),
    "robotic_arm": ("arm", "robot", "robotic"),
    "hydraulic_press": ("press", "hydraulic", "stamp"),
}


def locate_machines(session: Session, question: str) -> list[Machine]:
    """Tool: resolve a natural-language query to the machines it refers to.

    Supports direct references (code/name/type) and intents like "at risk",
    "faulted", "hottest", or "all" so ForgeAI can highlight assets in-scene.
    """
    machines = list(session.exec(select(Machine)).all())
    if not machines:
        return []
    q = question.lower()
    qtokens = _tokenize(question)
    hits: list[Machine] = []

    for m in machines:
        names = _tokenize(f"{m.code} {m.name}")
        type_words = _TYPE_HINTS.get(m.machine_type.value, ())
        if names & qtokens or any(w in q for w in type_words):
            hits.append(m)

    # Intent-based selection when no explicit machine was named.
    if not hits:
        if any(
            w in q
            for w in ("risk", "worst", "lowest", "unhealth", "critical", "attention")
        ):
            hits = [min(machines, key=lambda x: x.health_score)]
        elif any(w in q for w in ("fault", "alarm", "error", "down", "broken")):
            hits = [m for m in machines if m.last_fault_code] or []
        elif any(w in q for w in ("hot", "temp", "overheat", "thermal")):

            def temp(m: Machine) -> float:
                h = recent_telemetry(session, m.id, limit=1)
                return h[0].temperature if h else 0.0

            hits = [max(machines, key=temp)]
        elif any(
            w in q for w in ("all", "every", "each", "machines", "fleet", "overview")
        ):
            hits = machines

    return hits


def sensitive_terms(session: Session) -> list[str]:
    """Customer + company names/emails to redact from prompts before they reach
    Anthropic (restored locally in the response). See app.core.privacy."""
    terms: list[str] = []
    for c in session.exec(select(Customer)).all():
        if c.name:
            terms.append(c.name)
        if c.contact_email:
            terms.append(c.contact_email)
    return terms


def order_tracker_context(session: Session) -> str:
    """Summarize the active purchase orders (the Order Tracker datasource) so it
    is included with EVERY ForgeAI chat — by order, status, supplier and total."""
    suppliers: dict[uuid.UUID | None, str] = {
        s.id: s.name for s in session.exec(select(Supplier)).all()
    }
    orders = {o.id: o for o in session.exec(select(CustomerOrder)).all()}
    pos = list(session.exec(select(PurchaseOrder)).all())
    active = [p for p in pos if p.status.value != "closed"]
    if not active:
        return "Order tracker: no active purchase orders."
    total = sum(p.amount for p in active)
    lines = [
        f"Active purchase orders: {len(active)} | total value ${total:,.0f}",
    ]
    for p in active[:25]:
        order = orders.get(p.customer_order_id) if p.customer_order_id else None
        lines.append(
            f"- {p.po_number}: order {order.order_number if order else 'n/a'}"
            f"{f' ({order.part_type} x{order.quantity})' if order else ''}, "
            f"status {p.status.value}, ${p.amount:,.0f}, "
            f"supplier {suppliers.get(p.supplier_id, 'n/a')}, "
            f"{'shop-floor ready' if p.shop_floor_ready else 'not ready'}"
        )
    return "\n".join(lines)


# Free-text → logistics / inventory intent (drives the simulation camera).
_LOGISTICS_WORDS = (
    "po",
    "p.o",
    "purchase order",
    "purchase-order",
    "order",
    "delivery",
    "deliver",
    "shipment",
    "ship",
    "forklift",
    "supplier",
    "procurement",
)
_INVENTORY_WORDS = (
    "inventory",
    "stock",
    "receiving",
    "reorder",
    "re-order",
    "material",
    "warehouse",
    "dock",
    "pallet",
    "sku",
)


def _sim_focus(
    question: str, located: list[Machine], machines: list[Machine]
) -> SimFocus:
    """Classify a query into a cinematic camera directive for the simulation."""
    q = question.lower()

    # Logistics / PO / delivery → follow a forklift along its route.
    if any(w in q for w in _LOGISTICS_WORDS):
        return SimFocus(
            mode="logistics",
            machine_ids=[m.id for m in located],
            follow_forklift=True,
            label="Following a forklift - purchase orders in motion",
        )

    # Inventory / receiving / stock → swing to the receiving dock.
    if any(w in q for w in _INVENTORY_WORDS):
        return SimFocus(
            mode="inventory",
            machine_ids=[m.id for m in located],
            follow_forklift=False,
            label="Inventory - receiving dock",
        )

    if located:
        # Fleet view when (almost) every machine is implicated.
        if len(located) >= max(2, len(machines)):
            return SimFocus(
                mode="fleet",
                machine_ids=[m.id for m in located],
                label="Fleet overview",
            )
        codes = ", ".join(m.code for m in located[:3])
        return SimFocus(
            mode="machine",
            machine_ids=[m.id for m in located],
            label=f"Focusing {codes}",
        )

    return SimFocus(mode="none")


def _fleet_context(session: Session, machines: list[Machine]) -> str:
    lines = []
    for m in machines:
        h = recent_telemetry(session, m.id, limit=1)
        t = h[0] if h else None
        lines.append(
            f"- {m.code} ({m.name}, {m.machine_type.value}): status {m.status.value}, "
            f"health {m.health_score}, runtime {m.runtime_hours}h, "
            f"fault {m.last_fault_code or 'none'}"
            + (f", temp {t.temperature}°C, vibration {t.vibration}" if t else "")
        )
    return "\n".join(lines)


async def forge_answer(session: Session, question: str) -> ForgeResponse:
    """ForgeAI: a general, RAG-enabled assistant over the whole simulation.

    Answers across all active machines + the knowledge base and returns the set
    of machines to highlight in the 3D scene (via the locator tool).
    """
    machines = list(session.exec(select(Machine)).all())
    located = locate_machines(session, question)
    docs = retrieve(session, question)
    # SOPs first (authoritative), then Forge Facts (secondary user notes).
    sop_sources = retrieve_sops(session, question)
    fact_sources = retrieve_forge_facts(session, question)
    doc_sources = [
        SourceRef(document_id=d.id, title=d.title, kind=d.kind.value) for d in docs
    ]
    sources = sop_sources + fact_sources + doc_sources

    fleet = _fleet_context(session, located or machines)
    order_tracker = order_tracker_context(session)
    doc_block = "\n\n".join(f"[{d.title}]\n{d.content}" for d in docs)
    system = (
        "You are ForgeAI, the SmartForge factory-simulation assistant. You have a "
        "live view of every machine, the Order Tracker (active purchase orders), the "
        "SOPs (Standard Operating Procedures), the maintenance documentation and the "
        "user-authored Forge Facts. Answer operational questions about the simulation "
        "concisely and concretely, referencing machine codes and PO/order numbers "
        "where relevant. Answer directly without preamble. " + _SOURCE_PRIORITY
    )
    user = (
        f"Question: {question}\n\n"
        f"Active machines:\n{fleet}\n\n"
        f"Order tracker (active purchase orders):\n{order_tracker}\n\n"
        f"{_rag_block(sop_sources, fact_sources, doc_block)}"
    )

    try:
        text = await llm.complete(
            system=system,
            user=user,
            max_tokens=900,
            sensitive_terms=sensitive_terms(session),
        )
        confidence = 0.9
    except llm.LLMUnavailable:
        ctx = f"{fleet}\n\n{order_tracker}"
        text = _fallback_answer(question, docs, ctx)
        confidence = 0.4

    suggested: list[str] = []
    if located:
        codes = ", ".join(m.code for m in located[:4])
        suggested.append(f"Highlighted in scene: {codes}")
    suggested += _suggest_actions(question, located[0] if located else None)

    return ForgeResponse(
        answer=text,
        sources=sources,
        suggested_actions=suggested[:4],
        confidence=confidence,
        highlight=[m.id for m in located],
        focus=_sim_focus(question, located, machines),
    )


def _suggest_actions(question: str, machine: Machine | None) -> list[str]:
    actions: list[str] = []
    ql = question.lower()
    if machine:
        actions.append(f"View live telemetry for {machine.code}")
        if machine.health_score < 70:
            actions.append("Open a predictive maintenance work order")
    if any(w in ql for w in ("fault", "error", "alarm", "code")):
        actions.append("Check the fault troubleshooting guide")
    if any(w in ql for w in ("schedule", "maintenance", "service")):
        actions.append("Review the maintenance alert center")
    return actions[:3]
