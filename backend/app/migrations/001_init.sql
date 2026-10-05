CREATE SEQUENCE IF NOT EXISTS order_seq START 10001;
CREATE SEQUENCE IF NOT EXISTS ndr_seq START 1001;

CREATE TABLE IF NOT EXISTS merchants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    customer_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    pickup_pincode TEXT NOT NULL,
    delivery_pincode TEXT NOT NULL,
    weight_kg NUMERIC(8,3) NOT NULL,
    payment_mode TEXT NOT NULL CHECK (payment_mode IN ('COD','PREPAID')),
    cod_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'CREATED',
    selected_carrier TEXT,
    selected_service TEXT,
    quoted_price NUMERIC(10,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shipping_quotes (
    id SERIAL PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    carrier TEXT NOT NULL,
    service TEXT NOT NULL,
    service_name TEXT NOT NULL,
    price NUMERIC(10,2) NOT NULL,
    eta_min_days INT NOT NULL,
    eta_max_days INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (order_id, carrier, service)
);

CREATE TABLE IF NOT EXISTS shipments (
    id SERIAL PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
    carrier TEXT NOT NULL,
    service TEXT NOT NULL,
    carrier_shipment_id TEXT NOT NULL,
    tracking_number TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'SHIPMENT_CREATED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shipment_events (
    id SERIAL PRIMARY KEY,
    shipment_id INT NOT NULL REFERENCES shipments(id),
    carrier TEXT NOT NULL,
    tracking_number TEXT NOT NULL,
    status TEXT NOT NULL,
    event_id TEXT NOT NULL,
    reason TEXT,
    raw JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- webhook idempotency key
    UNIQUE (carrier, tracking_number, status, event_id)
);

CREATE TABLE IF NOT EXISTS ndr_cases (
    id TEXT PRIMARY KEY DEFAULT ('NDR-' || nextval('ndr_seq')),
    shipment_id INT NOT NULL REFERENCES shipments(id),
    order_id TEXT NOT NULL REFERENCES orders(id),
    reason TEXT NOT NULL,
    attempt_number INT NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'OPEN',
    last_intent JSONB,
    last_decision JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id SERIAL PRIMARY KEY,
    ndr_case_id TEXT NOT NULL REFERENCES ndr_cases(id),
    sender TEXT NOT NULL CHECK (sender IN ('BUYER','AGENT')),
    message TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS carrier_actions (
    id SERIAL PRIMARY KEY,
    ndr_case_id TEXT NOT NULL REFERENCES ndr_cases(id),
    action_type TEXT NOT NULL,
    status TEXT NOT NULL,
    request JSONB,
    response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    event TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_shipment ON shipment_events(shipment_id);
CREATE INDEX IF NOT EXISTS idx_ndr_shipment ON ndr_cases(shipment_id);
CREATE INDEX IF NOT EXISTS idx_msgs_case ON conversation_messages(ndr_case_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_type, entity_id);
