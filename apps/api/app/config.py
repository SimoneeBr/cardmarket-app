"""Application configuration, loaded exclusively from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    database_url: str = "postgresql+psycopg://cmc:cmc@localhost:5432/cmc"
    database_pool_size: int = 5

    # --- web sessions -----------------------------------------------------
    session_cookie_name: str = "cmc_session"
    csrf_cookie_name: str = "cmc_csrf"
    session_ttl_hours: int = 24 * 14
    cookie_secure: bool = True
    cookie_domain: str | None = None

    # --- rate limiting ------------------------------------------------------
    login_rate_limit_attempts: int = 8
    login_rate_limit_window_seconds: int = 300
    message_rate_limit_per_minute: int = 20

    # --- agent --------------------------------------------------------------
    agent_api_token: SecretStr = Field(default=SecretStr(""))
    agent_offline_after_seconds: int = 120
    sync_lock_ttl_seconds: int = 300
    sync_interval_seconds: int = Field(default=45, ge=10, le=3600)
    mock_cardmarket: bool = True
    # URL of the remote browser viewer (noVNC) used during manual pairing.
    pairing_viewer_url: str = ""

    # --- action queue ---------------------------------------------------------
    action_max_attempts: int = 5
    action_backoff_base_seconds: int = 10
    action_backoff_max_seconds: int = 900

    # --- web push -------------------------------------------------------------
    vapid_public_key: str = ""
    vapid_private_key: SecretStr = Field(default=SecretStr(""))
    vapid_subject: str = "mailto:admin@example.com"

    # --- privacy / retention --------------------------------------------------
    retention_messages_days: int = 365
    retention_notifications_days: int = 60
    retention_audit_days: int = 365
    retention_sync_runs_days: int = 30
    maintenance_interval_seconds: int = 3600

    # Artifacts (screenshots/traces) written by the agent to a shared volume.
    artifacts_dir: str = "/data/artifacts"

    public_web_url: str = "http://localhost:3000"

    # First-run administrator creation from the web wizard. In production the
    # wizard is refused unless SETUP_TOKEN is set and supplied by the operator
    # (otherwise whoever reaches the site first could claim the admin account).
    setup_token: SecretStr = Field(default=SecretStr(""))

    @field_validator("database_url")
    @classmethod
    def _normalize_driver(cls, value: str) -> str:
        # Accept plain postgres URLs (e.g. from a PaaS) and pin the psycopg3 driver.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key.get_secret_value())

    def validate_for_runtime(self) -> None:
        """Refuse to boot production with insecure defaults."""
        if self.environment != "production":
            return
        problems: list[str] = []
        token = self.agent_api_token.get_secret_value()
        if len(token) < 32:
            problems.append("AGENT_API_TOKEN must be at least 32 characters")
        if _looks_like_placeholder(token):
            problems.append("AGENT_API_TOKEN is a development placeholder")
        if _looks_like_placeholder(self.database_url):
            problems.append("DATABASE_URL uses a development placeholder password")
        setup = self.setup_token.get_secret_value()
        if setup and (len(setup) < 16 or _looks_like_placeholder(setup)):
            problems.append("SETUP_TOKEN must be at least 16 random characters")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if problems:
            raise RuntimeError("Invalid production configuration: " + "; ".join(problems))


_PLACEHOLDER_MARKERS = ("change-me", "dev-only", "cmc-dev-password", "changeme")


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


@lru_cache
def get_settings() -> Settings:
    return Settings()
