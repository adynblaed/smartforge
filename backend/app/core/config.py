import warnings
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    # Deliberately the known template default, NOT a random value: a random
    # default silently mints a different key per worker/replica/restart —
    # breaking cross-worker JWT validation and permanently orphaning
    # EncryptedString ciphertext. "changethis" trips the non-default-secret
    # validator below, so a deploy that forgot to set SECRET_KEY fails
    # loudly instead of corrupting quietly (SEC-001).
    SECRET_KEY: str = "changethis"
    # Session length without a refresh-token flow. 12h balances security (a
    # leaked token expires same-day) with usability (no mid-shift logouts).
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    # Host header allow-list (TrustedHostMiddleware). Default "*" for local/CI;
    # set explicit hostnames in production to block Host-header injection.
    ALLOWED_HOSTS: Annotated[list[str] | str, BeforeValidator(parse_cors)] = ["*"]

    # App-layer role-aware rate limiting (API-017/SEC-012): per-minute token
    # buckets PER PROCESS, keyed by user identity (or client IP when
    # anonymous). Traefik's coarse per-IP limit at ingress is separate; see
    # app/core/ratelimit.py for the tier semantics.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_SUPERUSER_PER_MINUTE: int = 600
    RATE_LIMIT_INTERNAL_PER_MINUTE: int = 300
    RATE_LIMIT_CUSTOMER_PER_MINUTE: int = 120
    RATE_LIMIT_ANONYMOUS_PER_MINUTE: int = 30

    # Site-wide feature-flag overrides (app/core/features.py): comma-
    # separated feature keys force-enabled/disabled regardless of tier.
    # Overrides never bypass authentication or the customer boundary.
    FEATURE_FLAGS_ENABLE: str = ""
    FEATURE_FLAGS_DISABLE: str = ""

    # Interactive API documentation (/docs Swagger UI, /redoc ReDoc, and the
    # OpenAPI schema). Served in every environment by default — the schema
    # documents only the contract (auth is still enforced per endpoint);
    # set false to withdraw the surface entirely on hardened deployments.
    API_DOCS_ENABLED: bool = True

    # Optional static bearer token for GET /api/v1/metrics. Empty (default)
    # keeps the scrape endpoint open for in-network Prometheus; set it when
    # the API port is reachable beyond the scrape network, and configure
    # the scraper's `authorization` credentials to match.
    METRICS_BEARER_TOKEN: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str
    # Password assigned to the seeded sandbox (operator/maintenance/planner/
    # customer) accounts. Override in production or disable sandbox seeding.
    SANDBOX_USER_PASSWORD: str = "changethis"

    # ---- SmartForge: Redis (pub/sub fan-out + health probe; see core/redis.py) ----
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # ---- SmartForge: AskAI / Claude ----
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-opus-4-8"
    ANTHROPIC_MAX_TOKENS: int = 1024

    @computed_field  # type: ignore[prop-decorator]
    @property
    def askai_enabled(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY)

    # ---- SmartForge: Qdrant vector database (RAG over knowledge bases) ----
    QDRANT_URL: str = "http://qdrant:6333"
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION: str = "knowledge_bases"
    # FastEmbed models for embedding + reranking (downloaded on first use).
    EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"
    RERANK_MODEL: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    RAG_ENABLED: bool = True
    RAG_RERANK: bool = True
    # how many candidates to retrieve / how many to keep after reranking
    RAG_CANDIDATES: int = 20
    RAG_TOP_K: int = 5

    # ---- SmartForge: Fiix work-order integration (mock) ----
    FIIX_BASE_URL: str = "https://mock.fiix.local/api"
    FIIX_API_KEY: str | None = None

    # ---- SmartForge: telemetry simulator ----
    SIMULATOR_ENABLED: bool = True
    SIMULATOR_INTERVAL_SECONDS: float = 3.0
    # A machine is considered "live" (and the simulator "running") if telemetry
    # has landed within this window — used by the Services health board.
    TELEMETRY_FRESH_SECONDS: int = 30

    # ---- SmartForge: business rules (env-overridable, was hardcoded) ----
    # Quoting rate card (Module 4)
    QUOTE_MATERIAL_RATE: float = 3.5
    QUOTE_LABOR_RATE: float = 12.0
    QUOTE_MACHINE_RATE: float = 0.85
    QUOTE_RUSH_MULTIPLIER: float = 0.25
    QUOTE_TARGET_MARGIN: float = 0.35
    # Quality cost assumptions (Module 2)
    SCRAP_UNIT_COST: float = 42.0
    REWORK_UNIT_COST: float = 18.0
    # Alert-rule thresholds (Module 1B)
    ALERT_VIBRATION_LIMIT: float = 0.6
    ALERT_TEMP_LIMIT: float = 85.0
    ALERT_RUNTIME_LIMIT: float = 2000.0
    ALERT_HEALTH_FLOOR: float = 60.0
    # Customer-portal escalation: answers below this confidence are escalated.
    ESCALATION_CONFIDENCE_THRESHOLD: float = 0.5

    # Values that must never reach a shared environment: the template default
    # plus the documented sandbox demo logins (README/QUICKSTART). Sandbox
    # credentials are convenient locally but are public knowledge — outside
    # `local` they are treated exactly like "changethis" (IAM-002/SEC-001).
    _INSECURE_DEFAULTS = frozenset({"changethis", "futureform2026", "admin"})

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value in self._INSECURE_DEFAULTS:
            message = (
                f'The value of {var_name} is "{value}" (a known default), '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )
        self._check_default_secret("SANDBOX_USER_PASSWORD", self.SANDBOX_USER_PASSWORD)

        return self

    @model_validator(mode="after")
    def _enforce_production_boundaries(self) -> Self:
        """Misconfiguration traps that only bite in shared environments:
        an open Host allowlist defeats TrustedHostMiddleware, and a
        localhost FRONTEND_HOST poisons CORS and password-reset links.
        Warn in staging, refuse in production (same posture as the
        non-default-secret gate)."""
        problems: list[str] = []
        if self.ALLOWED_HOSTS == ["*"]:
            problems.append(
                "ALLOWED_HOSTS is '*' — set the real hostname allowlist"
            )
        if "localhost" in self.FRONTEND_HOST or "127.0.0.1" in self.FRONTEND_HOST:
            problems.append(
                "FRONTEND_HOST points at localhost — CORS and password-reset "
                "links will target the wrong origin"
            )
        for message in problems:
            if self.ENVIRONMENT == "production":
                raise ValueError(message)
            if self.ENVIRONMENT == "staging":
                warnings.warn(message, stacklevel=1)
        return self


settings = Settings()  # type: ignore
