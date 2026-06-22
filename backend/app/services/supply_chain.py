"""Quoting engine + supply-chain risk helpers (Module 4)."""

from __future__ import annotations

from sqlmodel import Session, select

from app.core.config import settings
from app.models import InventoryItem, Quote

# Rate card — env-overridable via settings.
MATERIAL_RATE = settings.QUOTE_MATERIAL_RATE  # per unit
LABOR_RATE = settings.QUOTE_LABOR_RATE  # per unit
MACHINE_RATE = settings.QUOTE_MACHINE_RATE  # per unit-minute
RUSH_MULTIPLIER = settings.QUOTE_RUSH_MULTIPLIER
TARGET_MARGIN = settings.QUOTE_TARGET_MARGIN


def price_quote(quote: Quote) -> Quote:
    """Estimate price, margin, timeline, and risk flags (spec §4B)."""
    material = quote.material_cost or quote.quantity * MATERIAL_RATE
    labor = quote.labor_cost or quote.quantity * LABOR_RATE
    machine_time = quote.machine_time_cost or quote.quantity * MACHINE_RATE
    base = material + labor + machine_time
    rush_premium = base * RUSH_MULTIPLIER if quote.rush else 0.0
    cost = base + rush_premium
    price = round(cost / (1.0 - TARGET_MARGIN), 2)

    quote.material_cost = round(material, 2)
    quote.labor_cost = round(labor, 2)
    quote.machine_time_cost = round(machine_time, 2)
    quote.rush_premium = round(rush_premium, 2)
    quote.estimated_price = price
    quote.margin_estimate = round((price - cost) / price, 4) if price else 0.0
    quote.timeline_days = 3 if quote.rush else max(5, quote.quantity // 100 + 5)

    flags = []
    if quote.quantity > 5000:
        flags.append("high_volume_capacity_risk")
    if quote.rush:
        flags.append("rush_premium_applied")
    quote.risk_flags = ",".join(flags) or None
    return quote


def inventory_below_threshold(session: Session) -> list[InventoryItem]:
    items = list(session.exec(select(InventoryItem)).all())
    return [i for i in items if i.quantity < i.reorder_threshold]
