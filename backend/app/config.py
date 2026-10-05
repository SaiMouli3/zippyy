import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/zippy")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# The mock carriers run inside this API; adapters call them over real HTTP.
CARRIER_BASE_URL = os.environ.get("CARRIER_BASE_URL", "http://127.0.0.1:8000")
# Where mock carriers deliver webhooks.
WEBHOOK_BASE_URL = os.environ.get("WEBHOOK_BASE_URL", CARRIER_BASE_URL)
RATE_CACHE_TTL = int(os.environ.get("RATE_CACHE_TTL", "300"))
CARRIER_TIMEOUT = float(os.environ.get("CARRIER_TIMEOUT", "3"))
SEED_DEMO = os.environ.get("SEED_DEMO", "true").lower() == "true"
# Reschedules further out than this need human approval.
MAX_AUTO_RESCHEDULE_DAYS = 2
