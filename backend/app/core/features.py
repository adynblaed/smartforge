"""Site-wide feature flags and tier gates (v1 RBAC finalization).

One hierarchical tier ladder spans every surface (ascending):

    user < operator < admin < leadership < developer < superuser

A user's tier derives from the existing identity model — `is_superuser`
wins, then `User.role` maps onto the ladder — so no data migration is
required and every pre-v1 account keeps working. Each feature gate names
the MINIMUM tier; higher tiers inherit everything below them.

Defaults preserve the shipped v1.0.0 authorization behavior (internal
surfaces at operator, the platform control plane at superuser) with three
deliberate hardenings: CSV data exchange is admin+, executive analytics is
leadership+, and the service log console is developer+.

Deployments can flip individual features without code via env kill
switches (`FEATURE_FLAGS_ENABLE` / `FEATURE_FLAGS_DISABLE`, comma-
separated keys). Overrides adjust the tier gate only — they never bypass
authentication or the customer/internal boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from fastapi import Depends, HTTPException

from app.core.config import settings
from app.models import User, UserRole


class Tier(str, Enum):
    user = "user"
    operator = "operator"
    admin = "admin"
    leadership = "leadership"
    developer = "developer"
    superuser = "superuser"


_TIER_ORDER: dict[Tier, int] = {tier: rank for rank, tier in enumerate(Tier)}

# Role → tier. Legacy shop-floor roles (maintenance/planner) sit with
# operator; customer-portal accounts are the base tier.
_ROLE_TIER: dict[UserRole, Tier] = {
    UserRole.customer: Tier.user,
    UserRole.user: Tier.user,
    UserRole.operator: Tier.operator,
    UserRole.maintenance: Tier.operator,
    UserRole.planner: Tier.operator,
    UserRole.beta_client: Tier.operator,
    UserRole.admin: Tier.admin,
    UserRole.leadership: Tier.leadership,
    UserRole.developer: Tier.developer,
}


def tier_for(user: User) -> Tier:
    if user.is_superuser:
        return Tier.superuser
    return _ROLE_TIER.get(user.role, Tier.user)


# Beta is an AUDIENCE, orthogonal to the tier ladder (industry standard:
# early-access cohorts, not privilege levels). A beta-flagged feature must
# clear its tier gate AND the caller must belong to the beta audience —
# beta clients, developers (dogfooding) and superusers.
_BETA_ROLES = {UserRole.beta_client, UserRole.developer}


def is_beta_audience(user: User) -> bool:
    return user.is_superuser or user.role in _BETA_ROLES


# The site-wide gate registry: feature key → minimum tier. Frontend nav,
# page panels and backend dependencies all consult the same map (through
# GET /features and require_feature), so gating stays in parity e2e.
FEATURE_GATES: dict[str, Tier] = {
    # customer / base tier
    "portal": Tier.user,
    "portal_assistant": Tier.user,
    # core operations — any internal staff (v1 behavior preserved)
    "command_center": Tier.operator,
    "factory_simulation": Tier.operator,
    "forge_ai": Tier.operator,
    "machines": Tier.operator,
    "work_orders": Tier.operator,
    "tickets": Tier.operator,
    "quality": Tier.operator,
    "optimizations": Tier.operator,
    "mes": Tier.operator,
    "purchase_orders": Tier.operator,
    "feedback_triage": Tier.operator,
    "datasources_read": Tier.operator,
    "knowledge": Tier.operator,
    "eda": Tier.operator,
    "eda_charts": Tier.operator,
    "eda_galaxy": Tier.operator,
    "mrp": Tier.operator,
    "omega_catalog": Tier.operator,
    # elevated tiers
    "data_exchange": Tier.admin,  # CSV export/import of app data
    "analytics_exec": Tier.leadership,  # executive dashboards
    "logs_console": Tier.developer,  # per-service logs incl. audit trail
    "users_manage": Tier.superuser,
    "platform_ops": Tier.superuser,  # discovery / seed / sync control plane
}

# Early-access modules: tier gate AND beta audience required (env
# FEATURE_FLAGS_ENABLE graduates a beta feature to everyone).
BETA_FEATURES: set[str] = {"eda_galaxy"}


def _override_set(raw: str) -> set[str]:
    return {key.strip() for key in raw.split(",") if key.strip()}


def has_feature(user: User, key: str) -> bool:
    """Resolve one gate for one user (env overrides > beta > tier ladder)."""
    if key in _override_set(settings.FEATURE_FLAGS_DISABLE):
        return False
    if key in _override_set(settings.FEATURE_FLAGS_ENABLE):
        return True
    gate = FEATURE_GATES.get(key)
    if gate is None:
        return False  # unknown features are closed, never open
    if key in BETA_FEATURES and not is_beta_audience(user):
        return False
    return _TIER_ORDER[tier_for(user)] >= _TIER_ORDER[gate]


def resolve_features(user: User) -> dict[str, bool]:
    return {key: has_feature(user, key) for key in FEATURE_GATES}


def require_feature(key: str) -> Callable[..., User]:
    """Route dependency: 403 with a clean body when the gate is closed."""
    from app.api.deps import get_current_user

    def _guard(current_user: User = Depends(get_current_user)) -> User:
        if not has_feature(current_user, key):
            raise HTTPException(
                status_code=403,
                detail=f"Feature '{key}' requires a higher access tier",
            )
        return current_user

    return _guard
