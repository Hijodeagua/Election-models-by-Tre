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

    # Silver Bulletin model CSV download URLs (refresh_data.py --source silverb)
    silverb_approval_csv_url: str = "https://static.natesilver.net/approval.csv"
    silverb_gb_csv_url: str = "https://static.natesilver.net/generic-ballot.csv"

    # ── Prediction markets (keyless public APIs) ──────────────────────
    polymarket_base_url: str = "https://gamma-api.polymarket.com"
    kalshi_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    # Weight of the Polymarket/Kalshi consensus when blending into the
    # per-race model probability (0 = pure model, 1 = pure markets).
    market_blend_weight: float = 0.25

    # ── Publishing ────────────────────────────────────────────────────
    datawrapper_api_token: str = ""
    substack_url: str = "https://policyypeaches.substack.com"
    substack_name: str = "Policy & Peaches"

    # Datawrapper chart IDs — set via .env after creating charts in the UI
    dw_chart_approval_id: str = ""
    dw_chart_approval_pro_id: str = ""
    dw_chart_gb_id: str = ""
    dw_chart_senate_id: str = ""
    dw_chart_house_effects_id: str = ""

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
