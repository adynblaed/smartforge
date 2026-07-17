"""Site-wide feature flags & tier gates (app/core/features.py).

Proves: the tier ladder derives correctly from the existing identity model,
GET /features resolves per-tier, elevated gates are enforced server-side
(403 below tier, 200 at/above), and env overrides flip gates without ever
bypassing authentication.
"""

from app.core.config import settings
from app.core.features import FEATURE_GATES, Tier, has_feature, tier_for
from app.models import User, UserRole


def _user(role: UserRole, superuser: bool = False) -> User:
    return User(
        email=f"{role.value}@t.co",
        hashed_password="x",
        role=role,
        is_superuser=superuser,
    )


class TestTierLadder:
    def test_roles_map_onto_tiers(self):
        assert tier_for(_user(UserRole.customer)) == Tier.user
        assert tier_for(_user(UserRole.user)) == Tier.user
        assert tier_for(_user(UserRole.operator)) == Tier.operator
        assert tier_for(_user(UserRole.maintenance)) == Tier.operator
        assert tier_for(_user(UserRole.planner)) == Tier.operator
        assert tier_for(_user(UserRole.admin)) == Tier.admin
        assert tier_for(_user(UserRole.leadership)) == Tier.leadership
        assert tier_for(_user(UserRole.developer)) == Tier.developer

    def test_superuser_flag_wins_over_role(self):
        assert tier_for(_user(UserRole.customer, superuser=True)) == Tier.superuser

    def test_tiers_are_hierarchical(self):
        # A developer inherits every gate at or below their tier…
        dev = _user(UserRole.developer)
        assert has_feature(dev, "machines")
        assert has_feature(dev, "data_exchange")
        assert has_feature(dev, "analytics_exec")
        assert has_feature(dev, "logs_console")
        # …but never superuser-only control-plane features.
        assert not has_feature(dev, "platform_ops")
        assert not has_feature(dev, "users_manage")

    def test_operator_lacks_elevated_gates(self):
        op = _user(UserRole.operator)
        assert has_feature(op, "machines")
        assert not has_feature(op, "data_exchange")
        assert not has_feature(op, "analytics_exec")
        assert not has_feature(op, "logs_console")

    def test_unknown_features_are_closed(self):
        assert not has_feature(_user(UserRole.admin, superuser=True), "nope")


class TestBetaAudience:
    def test_beta_features_need_tier_and_audience(self):
        # Operator clears the tier gate but is not in the beta audience.
        assert not has_feature(_user(UserRole.operator), "eda_galaxy")
        # Beta clients sit at operator tier AND in the audience.
        beta = _user(UserRole.beta_client)
        assert tier_for(beta) == Tier.operator
        assert has_feature(beta, "eda_galaxy")
        # Developers dogfood betas; superusers see everything.
        assert has_feature(_user(UserRole.developer), "eda_galaxy")
        assert has_feature(_user(UserRole.customer, superuser=True), "eda_galaxy")

    def test_beta_membership_never_raises_tier(self):
        beta = _user(UserRole.beta_client)
        assert not has_feature(beta, "data_exchange")
        assert not has_feature(beta, "logs_console")

    def test_env_enable_graduates_a_beta_feature(self, monkeypatch):
        monkeypatch.setattr(settings, "FEATURE_FLAGS_ENABLE", "eda_galaxy")
        assert has_feature(_user(UserRole.operator), "eda_galaxy")

    def test_endpoint_reports_beta_membership(self, beta_client, internal_client):
        assert beta_client.get("/api/v1/features").json()["beta"] is True
        assert internal_client.get("/api/v1/features").json()["beta"] is False


class TestEnvOverrides:
    def test_disable_wins_even_for_superuser(self, monkeypatch):
        monkeypatch.setattr(settings, "FEATURE_FLAGS_DISABLE", "logs_console")
        assert not has_feature(_user(UserRole.admin, superuser=True), "logs_console")

    def test_enable_opens_a_gate_below_tier(self, monkeypatch):
        monkeypatch.setattr(settings, "FEATURE_FLAGS_ENABLE", "logs_console")
        assert has_feature(_user(UserRole.operator), "logs_console")


class TestFeaturesEndpoint:
    def test_resolves_every_gate_for_the_caller(self, internal_client):
        r = internal_client.get("/api/v1/features")
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "operator"
        assert set(body["features"]) == set(FEATURE_GATES)
        assert body["features"]["machines"] is True
        assert body["features"]["logs_console"] is False

    def test_leadership_tier_resolves(self, leadership_client):
        body = leadership_client.get("/api/v1/features").json()
        assert body["tier"] == "leadership"
        assert body["features"]["analytics_exec"] is True
        assert body["features"]["logs_console"] is False


class TestServerSideGates:
    def test_logs_console_requires_developer_tier(
        self, internal_client, developer_client
    ):
        denied = internal_client.get("/api/v1/logs/services")
        assert denied.status_code == 403
        assert "tier" in denied.json()["detail"]
        assert developer_client.get("/api/v1/logs/services").status_code == 200

    def test_data_exchange_requires_admin_tier(
        self, internal_client, admin_client
    ):
        assert internal_client.get("/api/v1/datasources/export").status_code == 403
        assert admin_client.get("/api/v1/datasources/export").status_code == 200
