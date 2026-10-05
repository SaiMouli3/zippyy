from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://zippy:zippy@localhost:5432/zippy"
    redis_url: str = "redis://localhost:6379/0"

    # Where adapters send carrier API calls. Today: the mock carriers living in
    # this same process. Later: real carrier hosts (per-carrier URLs in the adapters).
    carrier_base_url: str = "http://localhost:8000"
    # Where carriers send webhooks. Real carriers need a public URL here.
    zippy_public_url: str = "http://localhost:8000"

    carrier_rate_timeout_seconds: float = 2.5
    carrier_booking_timeout_seconds: float = 5.0

    rate_cache_ttl_seconds: int = 300
    quote_validity_seconds: int = 900

    default_merchant_id: str = "MRC-100"
    agent_provider: str = "rule_based"
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
