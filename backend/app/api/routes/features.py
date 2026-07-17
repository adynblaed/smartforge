"""Feature-flag resolution for the signed-in user (tag: features).

The single source the frontend consults for page/panel gating: the user's
tier on the site-wide ladder plus every feature gate resolved for them
(app/core/features.py). Elevated gates are ALSO enforced server-side on
their routes (require_feature) — this endpoint is for UX parity, never the
security boundary.
"""

from typing import Any

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.features import is_beta_audience, resolve_features, tier_for

router = APIRouter(prefix="/features", tags=["features"])


@router.get("")
def my_features(current_user: CurrentUser) -> Any:
    return {
        "tier": tier_for(current_user).value,
        "role": current_user.role.value,
        "beta": is_beta_audience(current_user),
        "features": resolve_features(current_user),
    }
