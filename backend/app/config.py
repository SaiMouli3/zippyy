from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Development-only fallbacks. `Settings` refuses to start in production while any of these is in use.
_DEV_SECRET = "dev-only-secret-change-me-0000000000000000"
_DEV_PII_KEY = "ZGV2LW9ubHktcGlpLWtleS0zMi1ieXRlcy1sb25nISE="  # base64 of 32 bytes
_DEV_WEBHOOK_SECRET = "dev-only-webhook-secret"


class Settings(BaseSettings):
    # Empty variables (e.g. unset compose interpolations) fall back to defaults; production guards still apply.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    app_env: str = "development"  # development | test | production

    database_url: str = "postgresql+psycopg://zippy:zippy@localhost:5432/zippy"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    redis_url: str = "redis://localhost:6379/0"

    # Where adapters send carrier API calls. Today: the mock carriers living in
    # this same process. Later: real carrier hosts (per-carrier URLs in the adapters).
    carrier_base_url: str = "http://localhost:8000"
    # Where carriers and messaging providers send webhooks. Real providers need a public URL here.
    zippy_public_url: str = "http://localhost:8000"

    carrier_rate_timeout_seconds: float = 2.5
    carrier_booking_timeout_seconds: float = 5.0
    carrier_action_timeout_seconds: float = 6.0

    rate_cache_ttl_seconds: int = 300
    quote_validity_seconds: int = 900

    default_merchant_id: str = "MRC-100"
    agent_provider: str = "rule_based"
    cors_origins: str = "http://localhost:3000"

    # ---- security -------------------------------------------------------------------------------
    secret_key: str = _DEV_SECRET  # signs CSRF tokens and simulator webhooks
    pii_encryption_key: str = _DEV_PII_KEY  # base64, 32 bytes (AES-256-GCM)
    pii_hash_key: str = _DEV_SECRET  # HMAC key for phone lookups
    session_ttl_hours: int = 12
    session_idle_minutes: int = 120
    session_cookie_secure: bool = False  # must be true behind HTTPS
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    rate_limit_per_minute: int = 600  # authenticated API, per session or API key
    login_rate_limit_per_minute: int = 10  # per IP
    max_request_bytes: int = 1_000_000
    legacy_sandbox_enabled: bool = True  # the unauthenticated MVP booking API + mock carriers
    allow_demo_seed: bool = True

    # ---- carriers -------------------------------------------------------------------------------
    carrier_webhook_secret_fastship: str = _DEV_WEBHOOK_SECRET
    carrier_webhook_secret_quickexpress: str = _DEV_WEBHOOK_SECRET
    carrier_webhook_secret_reliable: str = _DEV_WEBHOOK_SECRET
    carrier_webhook_signature_required: bool = False  # MVP mock carriers do not sign; set true in production

    # ---- providers ------------------------------------------------------------------------------
    whatsapp_provider: str = "simulator"  # simulator | meta_cloud
    meta_graph_api_version: str = "v21.0"
    meta_phone_number_id: str = ""
    meta_access_token: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""

    voice_provider: str = "simulator"  # simulator | sarvam_agents
    sarvam_api_key: str = ""  # api.sarvam.ai (speech, language id, chat)
    sarvam_agents_api_key: str = ""  # apps.sarvam.ai workspace key (X-API-Key)
    sarvam_org_id: str = ""
    sarvam_workspace_id: str = ""
    sarvam_app_id: str = ""
    sarvam_app_version: int = 0
    sarvam_connection_id: str = ""
    sarvam_agent_phone_number: str = ""
    voice_webhook_secret: str = _DEV_WEBHOOK_SECRET
    provider_timeout_seconds: float = 8.0

    intent_extractor: str = "rules"  # rules | sarvam_llm | openai_compatible
    llm_base_url: str = ""  # OpenAI-compatible endpoint root, e.g. https://gateway.example/v1
    llm_api_key: str = ""
    llm_model: str = ""
    llm_call_policy: str = "unclear_only"  # unclear_only (rules first, cheapest) | always
    llm_min_rule_confidence: float = 0.8  # rule answers at or above this never reach the model
    sarvam_llm_model: str = "sarvam-105b"
    language_detector: str = "heuristic"  # heuristic | sarvam

    # ---- worker ---------------------------------------------------------------------------------
    worker_poll_seconds: float = 1.0
    worker_batch_size: int = 20
    job_lease_seconds: int = 120
    max_concurrent_calls_per_merchant: int = 10

    log_level: str = "INFO"
    log_json: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _production_guards(self):
        if self.app_env != "production":
            return self
        problems = []
        if self.secret_key == _DEV_SECRET or len(self.secret_key) < 32:
            problems.append("SECRET_KEY")
        if self.pii_encryption_key == _DEV_PII_KEY:
            problems.append("PII_ENCRYPTION_KEY")
        if self.pii_hash_key == _DEV_SECRET:
            problems.append("PII_HASH_KEY")
        if self.voice_webhook_secret == _DEV_WEBHOOK_SECRET:
            problems.append("VOICE_WEBHOOK_SECRET")
        if not self.session_cookie_secure:
            problems.append("SESSION_COOKIE_SECURE must be true")
        if problems:
            raise ValueError("refusing to start in production with insecure settings: " + ", ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
