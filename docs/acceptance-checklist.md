# Final acceptance checklist

Evidence: **59 backend tests** (`backend/tests`, real Postgres + Redis + live HTTP server) and a **27-check browser run**
(Playwright/Chromium driving the real UI) executed against both the
local dev stack and the Docker Compose stack.

| # | Item | Verified by |
|---|---|---|
| 1 | Order created from frontend | Browser: Create Order form → rates page |
| 2 | Order duplicate protection | `test_order_idempotency_*` (replay, conflict, per-merchant, concurrent); Browser: duplicate notice |
| 3 | Three distinct courier contracts | `test_shipment_creation_each_carrier_contract`, `test_webhooks_each_carrier_vocabulary`; contracts in README §8 |
| 4 | Rates normalized | `test_rate_normalization_*` (unit), `test_rates_normalized_and_cache_miss_then_hit` |
| 5 | Rates displayed together | Browser: three cards on one page |
| 6 | Rates sortable | Browser: price / delivery time / carrier sort |
| 7 | Cache miss works | `test_rates_normalized_and_cache_miss_then_hit`; Browser label "cache miss" |
| 8 | Cache hit avoids carrier calls | Same test asserts zero `CARRIER_CALL` logs on hit; `test_cache_shared_between_orders...` |
| 9 | Cache expiry works | `test_cache_expiry` (TTL=1s, re-queries carriers after expiry) |
| 10 | `refresh=true` works | `test_refresh_bypasses_and_replaces_cache`; Browser "Refresh rates" |
| 11 | Changed pricing input → new cache key | `test_cache_key_contains_every_pricing_input_and_changes_with_each` (each of 9 fields), `test_changed_pricing_input_changes_cache_key` (parametrized API) |
| 12 | Partial result strategy | `test_partial_failure_returns_others_and_caches_with_short_ttl`, `test_partial_result_expires_quickly_then_recovers`, `test_carrier_timeout`; Browser failure banner |
| 13 | Redis failure fallback | `test_redis_failure_falls_back_to_carriers`; Browser run stops the Redis container and refreshes rates (3 carriers still returned, "Redis unavailable") |
| 14 | Carrier selection | `test_select_carrier` |
| 15 | Quoted amount cannot be modified | `test_quoted_amount_cannot_be_modified`; Browser 409 check |
| 16 | Shipment created | `test_shipment_creation_each_carrier_contract` |
| 17 | Carrier event generated | Mock Carrier Control → `POST /api/mock/...` (all webhook tests, Browser) |
| 18 | Webhook received | `test_webhooks_each_carrier_vocabulary`, E2E |
| 19 | Raw webhook stored | `test_raw_and_normalized_event_both_stored` |
| 20 | Normalized event stored | same test |
| 21 | Duplicate webhook handled | `test_duplicate_webhook_creates_one_event`, `test_duplicate_webhook_concurrent`; Browser "Resend last webhook" |
| 22 | Unknown tracking number handled | `test_unknown_tracking_number_is_quarantined`; Browser quarantine table |
| 23 | Invalid status regression rejected | `test_status_regression_is_rejected`, `test_transition_rules`; Browser |
| 24 | Full tracking history displayed | E2E asserts 6-step history; Browser tracking page |
| 25 | Mock carrier control works | Browser run drives every button |
| 26 | Tests pass | `cd backend && python -m pytest` → 59 passed (also inside the Docker `api` container) |
| 27 | E2E test passes | `test_e2e_full_demo` |
| 28 | Swagger/OpenAPI available | `test_openapi_and_swagger_available`; Browser: Swagger UI renders operations (assets vendored, no CDN) |
| 29 | README complete | `README.md` §1–11 |
| 30 | assumptions.md complete | `docs/assumptions.md` |
| 31 | Docker Compose starts everything | `docker compose up --build`: postgres, redis, api (migrations + seed), web all healthy; UI/API/docs reachable on :3000 / :8000 |

Also covered: carrier timeout (`test_carrier_timeout`, reattempt timeout), structured logs (`test_structured_logs_carry_context`,
`test_shipment_and_webhook_logs_have_shipment_id`), all configuration via environment variables (`.env.example`).
