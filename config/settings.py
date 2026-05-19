"""Application settings managed via pydantic-settings."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Central configuration — reads from .env, environment variables, or defaults."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Data source URLs ──────────────────────────────────────────────
    votehub_base_url: str = "https://votehub.com/polls/api"
    fiftyplusone_api_key: str = ""
    congress_gov_api_key: str = ""
    nyt_api_key: str = ""

    # ── Publishing ────────────────────────────────────────────────────
    datawrapper_api_token: str = ""

    # ── Database ──────────────────────────────────────────────────────
    database_url: str = Field(
        default=f"sqlite:///{PROJECT_ROOT / 'data' / 'election_oracle.db'}"
    )

    # ── Scheduling ────────────────────────────────────────────────────
    refresh_interval_minutes: int = 60

    # ── Logging ───────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Polling average parameters ────────────────────────────────────
    recency_half_life_days: float = 14.0
    min_sample_size: int = 100
    lv_weight_multiplier: float = 1.5
    rv_weight_multiplier: float = 1.0
    adults_weight_multiplier: float = 0.6
    partisan_bias_penalty: float = 0.5

    # ── Paths ─────────────────────────────────────────────────────────
    @property
    def raw_data_dir(self) -> Path:
        return PROJECT_ROOT / "data" / "raw"

    @property
    def processed_data_dir(self) -> Path:
        return PROJECT_ROOT / "data" / "processed"

    @property
    def historical_data_dir(self) -> Path:
        return PROJECT_ROOT / "data" / "historical"


settings = Settings()
