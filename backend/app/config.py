"""All runtime configuration comes from environment variables (see .env.example)."""
import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/zippy")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Carrier endpoints. The mock carriers are served by this same app, but adapters reach them
# over HTTP exactly as they would a real carrier; each URL can be repointed independently.
CARRIER_BASE_URL = os.environ.get("CARRIER_BASE_URL", "http://127.0.0.1:8000")
FASTSHIP_BASE_URL = os.environ.get("FASTSHIP_BASE_URL", f"{CARRIER_BASE_URL}/mock/fastship")
QUICKEXPRESS_BASE_URL = os.environ.get("QUICKEXPRESS_BASE_URL", f"{CARRIER_BASE_URL}/mock/quickexpress")
RELIABLE_BASE_URL = os.environ.get("RELIABLE_BASE_URL", f"{CARRIER_BASE_URL}/mock/reliable")
CARRIER_URLS = {"fastship": FASTSHIP_BASE_URL, "quickexpress": QUICKEXPRESS_BASE_URL,
                "reliable": RELIABLE_BASE_URL}
# Where mock carriers deliver webhooks to Zippy.
WEBHOOK_BASE_URL = os.environ.get("WEBHOOK_BASE_URL", CARRIER_BASE_URL)

CARRIER_TIMEOUT_MS = _int("CARRIER_TIMEOUT_MS", 3000)
RATE_CACHE_TTL = _int("RATE_CACHE_TTL", 300)                  # complete results (seconds)
PARTIAL_RATE_CACHE_TTL = _int("PARTIAL_RATE_CACHE_TTL", 60)   # results missing >=1 carrier

DEFAULT_MERCHANT_ID = os.environ.get("DEFAULT_MERCHANT_ID", "MER-DEMO")
SEED_DEMO = os.environ.get("SEED_DEMO", "true").lower() == "true"
# Reschedules further out than this need human approval.
MAX_AUTO_RESCHEDULE_DAYS = _int("MAX_AUTO_RESCHEDULE_DAYS", 2)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
