-- Core logistics aggregation schema: orders, quotes, shipments, events.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SEQUENCE IF NOT EXISTS order_seq START 10001;

CREATE TABLE orders (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zippy_order_id       TEXT NOT NULL UNIQUE,
    merchant_id          TEXT NOT NULL,
    merchant_order_id    TEXT NOT NULL,
    customer_name        TEXT NOT NULL,
    customer_phone       TEXT NOT NULL,
    customer_email       TEXT,
    pickup_address_line1 TEXT NOT NULL,
    pickup_address_line2 TEXT,
    pickup_city          TEXT NOT NULL,
    pickup_state         TEXT NOT NULL,
    pickup_pincode       TEXT NOT NULL,
    delivery_address_line1 TEXT NOT NULL,
    delivery_address_line2 TEXT,
    delivery_city        TEXT NOT NULL,
    delivery_state       TEXT NOT NULL,
    delivery_pincode     TEXT NOT NULL,
    weight_grams         INTEGER NOT NULL CHECK (weight_grams > 0),
    length_cm            NUMERIC(8,2) NOT NULL CHECK (length_cm > 0),
    width_cm             NUMERIC(8,2) NOT NULL CHECK (width_cm > 0),
    height_cm            NUMERIC(8,2) NOT NULL CHECK (height_cm > 0),
    payment_type         TEXT NOT NULL CHECK (payment_type IN ('COD','PREPAID')),
    cod_amount           NUMERIC(12,2) NOT NULL DEFAULT 0,
    language             TEXT,                       -- seller-provided order language (ISO code)
    status               TEXT NOT NULL DEFAULT 'ORDER_CREATED',
    selected_quote_id    UUID,
    selected_carrier_code TEXT,
    selected_service_code TEXT,
    quoted_amount        NUMERIC(12,2),
    selected_at          TIMESTAMPTZ,
    rates_fetched_at     TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT orders_merchant_order_unique UNIQUE (merchant_id, merchant_order_id),
    CONSTRAINT orders_cod_positive CHECK (payment_type <> 'COD' OR cod_amount > 0)
);

CREATE TABLE shipping_quotes (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id             UUID NOT NULL REFERENCES orders(id),
    quote_group_id       UUID NOT NULL,
    cache_key            TEXT NOT NULL,
    carrier_code         TEXT NOT NULL,
    carrier_name         TEXT NOT NULL,
    service_code         TEXT NOT NULL,
    service_name         TEXT NOT NULL,
    base_charge          NUMERIC(12,2) NOT NULL,
    cod_charge           NUMERIC(12,2) NOT NULL,
    additional_charges   NUMERIC(12,2) NOT NULL,
    tax                  NUMERIC(12,2) NOT NULL,
    total_charge         NUMERIC(12,2) NOT NULL,
    estimated_min_days   INTEGER NOT NULL,
    estimated_max_days   INTEGER NOT NULL,
    quote_reference      TEXT,
    raw_carrier_response JSONB,
    expires_at           TIMESTAMPTZ NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX shipping_quotes_order_idx ON shipping_quotes(order_id, created_at DESC);
CREATE INDEX shipping_quotes_group_idx ON shipping_quotes(quote_group_id);

CREATE TABLE shipments (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id             UUID NOT NULL UNIQUE REFERENCES orders(id),
    carrier_code         TEXT NOT NULL,
    carrier_shipment_id  TEXT NOT NULL,
    tracking_number      TEXT NOT NULL UNIQUE,
    selected_service_code TEXT NOT NULL,
    quoted_amount        NUMERIC(12,2) NOT NULL,
    current_status       TEXT NOT NULL,
    label_url            TEXT,
    carrier_response     JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT shipments_carrier_shipment_unique UNIQUE (carrier_code, carrier_shipment_id)
);

CREATE TABLE shipment_events (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shipment_id          UUID NOT NULL REFERENCES shipments(id),
    idempotency_key      TEXT NOT NULL UNIQUE,
    carrier_code         TEXT NOT NULL,
    carrier_event_id     TEXT,
    carrier_status       TEXT NOT NULL,
    normalized_status    TEXT NOT NULL,
    description          TEXT,
    location             TEXT,
    event_time           TIMESTAMPTZ NOT NULL,
    ndr_reason_code      TEXT,
    ndr_remark           TEXT,
    -- APPLIED: moved/confirmed state. REJECTED_TRANSITION: quarantined, excluded from history.
    disposition          TEXT NOT NULL DEFAULT 'APPLIED' CHECK (disposition IN ('APPLIED','REJECTED_TRANSITION')),
    raw_event_payload    JSONB NOT NULL,
    received_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX shipment_events_shipment_idx ON shipment_events(shipment_id, event_time, received_at);

-- Every raw webhook delivery, including ones that never reach shipment_events (unknown tracking, bad signature).
CREATE TABLE webhook_inbox (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    carrier_code   TEXT NOT NULL,
    raw_payload    JSONB,
    raw_body       TEXT,
    outcome        TEXT NOT NULL,
    detail         TEXT,
    request_id     TEXT,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX webhook_inbox_outcome_idx ON webhook_inbox(outcome, received_at DESC);

CREATE TABLE idempotency_records (
    key            TEXT NOT NULL,
    scope          TEXT NOT NULL,
    request_hash   TEXT NOT NULL,
    status_code    INTEGER NOT NULL,
    response       JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, key)
);
