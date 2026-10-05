-- Order idempotency, dimensions/grams (cache key inputs), raw+normalized events, webhook quarantine.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS merchant_order_id TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS weight_grams INT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS length_cm INT NOT NULL DEFAULT 10;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS width_cm INT NOT NULL DEFAULT 10;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS height_cm INT NOT NULL DEFAULT 10;
UPDATE orders SET weight_grams = round(weight_kg * 1000) WHERE weight_grams IS NULL;
ALTER TABLE orders ALTER COLUMN weight_grams SET NOT NULL;
ALTER TABLE orders ALTER COLUMN length_cm DROP DEFAULT;
ALTER TABLE orders ALTER COLUMN width_cm DROP DEFAULT;
ALTER TABLE orders ALTER COLUMN height_cm DROP DEFAULT;
ALTER TABLE orders DROP COLUMN weight_kg;
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_merchant_order
    ON orders(merchant_id, merchant_order_id) WHERE merchant_order_id IS NOT NULL;

-- `raw` already holds the carrier payload; `normalized` holds Zippy's interpretation of it.
ALTER TABLE shipment_events ADD COLUMN IF NOT EXISTS normalized JSONB;

CREATE TABLE IF NOT EXISTS webhook_quarantine (
    id SERIAL PRIMARY KEY,
    carrier TEXT NOT NULL,
    tracking_number TEXT,
    reason TEXT NOT NULL,          -- UNKNOWN_TRACKING_NUMBER | INVALID_TRANSITION | UNPARSEABLE_PAYLOAD
    detail JSONB,
    raw JSONB,
    normalized JSONB,
    request_id TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quarantine_tracking ON webhook_quarantine(tracking_number);
