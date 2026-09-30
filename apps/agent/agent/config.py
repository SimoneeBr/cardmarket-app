"""Agent configuration (environment variables only)."""

import socket
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    api_url: str = "http://localhost:8000"
    agent_api_token: SecretStr = Field(default=SecretStr(""))
    agent_id: str = Field(default_factory=lambda: f"agent-{socket.gethostname()}"[:80])

    mock_cardmarket: bool = True

    # --- loop timing ----------------------------------------------------------
    heartbeat_seconds: int = 15
    action_poll_seconds: float = 2.0
    # Fallback when the API is unreachable at boot; the API value wins afterwards.
    sync_interval_seconds: int = 45
    action_lease_seconds: int = 300
    max_actions_per_tick: int = 10
    max_details_per_sync: int = 25

    # --- browser ----------------------------------------------------------------
    browser_profile_dir: Path = Path("/data/browser-profile")
    artifacts_dir: Path = Path("/data/artifacts")
    artifacts_keep: int = 200
    headless: bool = True
    browser_locale: str = "it-IT"
    browser_timezone: str = "Europe/Rome"
    navigation_timeout_ms: int = 30_000
    action_timeout_ms: int = 15_000
    # Random pause between navigations: be a polite, human-paced client.
    min_navigation_delay_ms: int = 800
    max_navigation_delay_ms: int = 2_500
    trace_on_failure: bool = False
    # Keep raw HTML of parsed pages (development only; never enable in production).
    debug_capture_html: bool = False
    pairing_timeout_seconds: int = 600

    # --- cardmarket ---------------------------------------------------------------
    # TODO: VERIFY AGAINST LIVE CARDMARKET - base URL, language segment and game.
    cardmarket_base_url: str = "https://www.cardmarket.com"
    cardmarket_language: str = "it"
    cardmarket_game: str = "Magic"
    max_list_pages: int = 2

    # --- mock ---------------------------------------------------------------------
    mock_state_file: Path = Path("/data/mock/state.json")
    mock_seed: int = 42
    mock_auto_pair: bool = True
    mock_pairing_delay_seconds: float = 3.0
    # Probability, per sync cycle, that the mock marketplace produces new activity.
    mock_activity_rate: float = 0.35

    @property
    def agent_version(self) -> str:
        from agent import __version__

        return __version__


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()
