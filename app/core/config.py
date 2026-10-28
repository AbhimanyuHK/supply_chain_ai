"""Application configuration loaded from environment variables / .env."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings.

    All values can be overridden via environment variables or a `.env` file
    in the project root. Field names map 1:1 to env var names (case-insensitive).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "staging", "production", "test"] = "development"
    app_name: str = "Supply Chain Planning Platform"
    api_v1_prefix: str = "/api/v1"

    log_level: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_dir: str = "logs"
    log_json: bool = False

    database_url: str = Field(
        default="sqlite+aiosqlite:///./supply_chain.db",
        description=(
            "Async SQLAlchemy database URL. Defaults to a local SQLite file for "
            "dependency-free local development; set to a postgresql+asyncpg:// URL "
            "(see docker-compose.yml) for staging/production."
        ),
    )
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_echo: bool = False

    llm_provider: Literal["groq", "ollama", "gemini"] = Field(
        default="groq",
        description=(
            "Which reasoning engine the 4 LLM-calling agents (Supply Planning, Allocation, "
            "Decision Review, Final Recommendation) use. 'groq' is the primary cloud engine; "
            "'gemini' is a free-tier cloud alternative (per-minute rate limits rather than "
            "Groq's flat daily token cap); 'ollama' runs entirely locally (no API key/quota) "
            "as a fallback — see app/core/llm.py. Switching is a one-line .env change, no "
            "code change."
        ),
    )

    groq_api_key: str = Field(default="", description="API key for the Groq reasoning engine.")
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq-hosted LLM used as the reasoning engine for all agents.",
    )
    groq_temperature: float = Field(
        default=0.0,
        description=(
            "0.0 minimizes LLM sampling randomness so identical inputs produce stable "
            "outputs - a defense-in-depth measure for idempotency; the primary guarantee "
            "is the scope+data+engine cache in app/agents/graph.py, not this."
        ),
    )
    groq_max_retries: int = 3

    gemini_api_key: str = Field(
        default="", description="API key for Google Gemini (AI Studio), used when llm_provider='gemini'."
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model used as the reasoning engine for all agents when llm_provider='gemini'.",
    )
    gemini_temperature: float = 0.0

    ollama_model: str = Field(
        default="mistral",
        description=(
            "Local Ollama model used when llm_provider='ollama'. Must already be pulled "
            "(`ollama pull <model>`) - 'mistral' has more reliable tool-calling/structured "
            "output support than smaller models like 'phi3', which matters since every "
            "agent forces structured JSON output."
        ),
    )
    ollama_base_url: str = Field(default="http://localhost:11434", description="Local Ollama server URL.")
    ollama_temperature: float = 0.0

    fleet_module_enabled: bool = Field(
        default=False,
        description="Toggles the Phase 2 fleet/route optimization agents in the LangGraph workflow.",
    )

    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])

    chronos_model_name: str = Field(
        default="amazon/chronos-t5-tiny",
        description=(
            "HuggingFace Chronos model used for zero-shot demand forecasting. "
            "Larger variants (chronos-t5-small/base/large) trade speed for accuracy."
        ),
    )
    chronos_device: str = Field(default="cpu", description="'cpu' or 'cuda' for Chronos inference.")
    chronos_random_seed: int = Field(
        default=42,
        description=(
            "Chronos forecasts by sampling multiple random trajectories internally and "
            "taking quantiles across them - with no fixed seed, identical historical data "
            "can produce a slightly different forecast on every call, which can flip a "
            "borderline store/product pair across the reorder-point threshold and change "
            "the resulting plan. Seeding torch's RNG before every predict() call makes "
            "forecasting itself deterministic given identical input, closing the one gap "
            "the scope+data+engine idempotency cache doesn't cover: a genuinely fresh "
            "computation (first run of a scope, or force_rerun=True)."
        ),
    )
    forecast_horizon_days: int = Field(default=14, ge=1, description="Days ahead the Demand Forecast Agent predicts.")
    forecast_batch_size: int = Field(
        default=256, ge=1, description="Store/product series per Chronos inference call."
    )

    supply_planning_max_candidate_terminals: int = Field(
        default=5,
        ge=1,
        description=(
            "Max candidate terminals (nearest by distance) considered per shortage when "
            "the Supply Planning Agent prompts Groq — bounds prompt size/cost at scale."
        ),
    )
    supply_planning_batch_size: int = Field(
        default=25,
        ge=1,
        description=(
            "Shortages grouped into one LLM prompt/response per batch, instead of one call "
            "per shortage. At scale (thousands of shortages) one-call-per-shortage means "
            "thousands of sequential LLM round-trips per run - easily exceeding a tight "
            "per-minute cap (e.g. Gemini free tier's 5 requests/minute). Batching reduces "
            "total request count, which per-minute caps actually care about."
        ),
    )
    llm_max_concurrent_requests: int = Field(
        default=3,
        ge=1,
        description=(
            "Max concurrent LLM calls in flight at once (bounds simultaneity, not "
            "requests-per-minute - a semaphore doesn't pace calls across a rolling minute "
            "window). Default of 3 suits Groq (the default provider, generous limits). "
            "Gemini free-tier operators should override to 1 via .env - its real limit is "
            "5 requests/minute, and many batches at concurrency=1 can still exceed that "
            "within one minute; true RPM pacing is a documented follow-up, not built here."
        ),
    )

    llm_native_optimizer_enabled: bool = Field(
        default=False,
        description="Opt in to LLM-generated allocation proposals and iterative search.",
    )
    llm_optimizer_iterations: int = Field(
        default=3, ge=1, le=20,
        description="Maximum LLM allocation improvement attempts per planning run.",
    )

    max_replanning_attempts: int = Field(
        default=2,
        ge=0,
        description=(
            "How many times the Constraint Validation Agent will send violations back to "
            "Supply Planning before giving up and proceeding best-effort."
        ),
    )

    decision_review_critical_stock_threshold: float = Field(
        default=0.1,
        ge=0,
        le=1,
        description=(
            "A (terminal, product) drawn down below this fraction of its pre-shipment "
            "available stock counts toward the Decision Review Agent's future inventory "
            "risk metric."
        ),
    )

    persist_full_master_data_snapshot: bool = Field(
        default=True,
        description=(
            "When True (default, fine at demo/moderate scale), PlanningRun persists the "
            "full input master-data snapshot verbatim. At millions of inventory rows this "
            "JSON blob could be many MB per run - set False to persist only row counts + "
            "business rules (PlanningRun.master_data_row_counts) instead. Master data is "
            "re-derivable from the DB either way; only the LLM-driven stage outputs are "
            "genuinely irreplaceable per run."
        ),
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached, process-wide Settings instance."""
    return Settings()
