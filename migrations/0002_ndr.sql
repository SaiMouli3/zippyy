-- NDR agent schema: rules, cases, conversations, actions, approvals, audit.
CREATE SEQUENCE IF NOT EXISTS ndr_case_seq START 20001;

CREATE TABLE seller_rules (
    merchant_id                   TEXT PRIMARY KEY,
    max_attempts                  INTEGER NOT NULL DEFAULT 3,
    auto_rto_attempt              INTEGER NOT NULL DEFAULT 3,
    cod_limit                     NUMERIC(12,2) NOT NULL DEFAULT 10000,
    allowed_channels              TEXT[] NOT NULL DEFAULT '{WHATSAPP,IVR,SMS}',
    comm_hours_start              TEXT NOT NULL DEFAULT '08:00',
    comm_hours_end                TEXT NOT NULL DEFAULT '21:00',
    enforce_comm_hours            BOOLEAN NOT NULL DEFAULT FALSE,
    prepaid_conversion_allowed    BOOLEAN NOT NULL DEFAULT TRUE,
    allow_address_changes         BOOLEAN NOT NULL DEFAULT TRUE,
    early_rto_policy              TEXT NOT NULL DEFAULT 'APPROVAL' CHECK (early_rto_policy IN ('AUTO','APPROVAL','DISALLOWED')),
    allowed_actions               TEXT[] NOT NULL DEFAULT '{REQUEST_REATTEMPT,RESCHEDULE,UPDATE_PHONE,UPDATE_ADDRESS,CONVERT_TO_PREPAID,INITIATE_RTO}',
    default_on_silence            TEXT NOT NULL DEFAULT 'RTO' CHECK (default_on_silence IN ('RTO','ESCALATE')),
    buyer_response_timeout_minutes  INTEGER NOT NULL DEFAULT 240,
    seller_response_timeout_minutes INTEGER NOT NULL DEFAULT 720,
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE carrier_rules (
    carrier_code            TEXT PRIMARY KEY,
    max_attempts            INTEGER NOT NULL DEFAULT 3,
    instruction_cutoff      TEXT NOT NULL DEFAULT '22:00',   -- IST wall clock; later instructions miss next-day attempt
    hold_window_days        INTEGER NOT NULL DEFAULT 7,
    supported_actions       TEXT[] NOT NULL,
    supports_time_slot      BOOLEAN NOT NULL DEFAULT FALSE,
    can_change_payment_mode BOOLEAN NOT NULL DEFAULT FALSE,
    can_change_address      BOOLEAN NOT NULL DEFAULT FALSE,
    can_change_phone        BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE buyer_profiles (
    phone               TEXT PRIMARY KEY,
    name                TEXT,
    preferred_language  TEXT,
    alternate_phone     TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ndr_cases (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_number              TEXT NOT NULL UNIQUE,
    shipment_id              UUID NOT NULL REFERENCES shipments(id),
    order_id                 UUID NOT NULL REFERENCES orders(id),
    shipment_event_id        UUID NOT NULL UNIQUE REFERENCES shipment_events(id),
    attempt_number           INTEGER NOT NULL,
    carrier_code             TEXT NOT NULL,
    carrier_reason_code      TEXT,
    carrier_remark           TEXT,
    normalized_reason        TEXT NOT NULL,
    reason_source            TEXT NOT NULL DEFAULT 'MAPPING',
    language                 TEXT NOT NULL,
    language_source          TEXT NOT NULL,
    buyer_intent             JSONB,
    recommended_action       TEXT,
    actual_action            TEXT,
    state                    TEXT NOT NULL,
    outcome                  TEXT,
    pending                  JSONB,                       -- awaiting-buyer context (confirmation, offers, payment link)
    plan                     JSONB,                       -- ordered carrier actions still to execute
    contact_attempts         INTEGER NOT NULL DEFAULT 0,
    contact_exhausted        BOOLEAN NOT NULL DEFAULT FALSE,
    seller_rules_snapshot    JSONB NOT NULL,
    carrier_constraints_snapshot JSONB NOT NULL,
    last_contacted_at        TIMESTAMPTZ,
    opened_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at                TIMESTAMPTZ,
    UNIQUE (shipment_id, attempt_number)
);
-- one active case per shipment
CREATE UNIQUE INDEX ndr_cases_one_active_per_shipment ON ndr_cases(shipment_id) WHERE state <> 'CLOSED';
CREATE INDEX ndr_cases_state_idx ON ndr_cases(state);

CREATE TABLE ndr_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ndr_case_id   UUID NOT NULL REFERENCES ndr_cases(id),
    event_type    TEXT NOT NULL,
    actor         TEXT NOT NULL,
    actor_type    TEXT NOT NULL,
    description   TEXT NOT NULL,
    data          JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ndr_events_case_idx ON ndr_events(ndr_case_id, created_at);

CREATE TABLE communication_attempts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ndr_case_id   UUID NOT NULL REFERENCES ndr_cases(id),
    channel       TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('SENT','DELIVERED','FAILED','DEFERRED')),
    error         TEXT,
    provider_ref  TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX communication_attempts_case_idx ON communication_attempts(ndr_case_id, created_at);

CREATE TABLE conversation_messages (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ndr_case_id        UUID NOT NULL REFERENCES ndr_cases(id),
    direction          TEXT NOT NULL CHECK (direction IN ('OUTBOUND','INBOUND')),
    sender_type        TEXT NOT NULL,
    channel            TEXT NOT NULL,
    language           TEXT NOT NULL,
    original_text      TEXT NOT NULL,             -- never overwritten by a translation
    internal_text      TEXT,                      -- English/normalized rendering for operators
    interpretation     JSONB,
    delivery_status    TEXT NOT NULL DEFAULT 'SENT',
    processed          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX conversation_messages_case_idx ON conversation_messages(ndr_case_id, created_at);

CREATE TABLE carrier_actions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ndr_case_id       UUID NOT NULL REFERENCES ndr_cases(id),
    shipment_id       UUID NOT NULL REFERENCES shipments(id),
    carrier_code      TEXT NOT NULL,
    action_type       TEXT NOT NULL,
    payload           JSONB NOT NULL,
    idempotency_key   TEXT NOT NULL UNIQUE,
    status            TEXT NOT NULL CHECK (status IN ('PENDING','ACCEPTED','REJECTED','FAILED')),
    request_payload   JSONB,
    response_payload  JSONB,
    carrier_reference TEXT,
    reason            TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at      TIMESTAMPTZ,
    responded_at      TIMESTAMPTZ
);
CREATE INDEX carrier_actions_case_idx ON carrier_actions(ndr_case_id, created_at);

CREATE TABLE approvals (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ndr_case_id      UUID NOT NULL REFERENCES ndr_cases(id),
    order_id         UUID NOT NULL REFERENCES orders(id),
    shipment_id      UUID NOT NULL REFERENCES shipments(id),
    kind             TEXT NOT NULL,
    proposed_action  JSONB NOT NULL,
    buyer_request    TEXT,
    reason           TEXT NOT NULL,
    evidence         JSONB,
    required_roles   TEXT[] NOT NULL,
    granted_roles    TEXT[] NOT NULL DEFAULT '{}',
    blocking         BOOLEAN NOT NULL DEFAULT TRUE,
    status           TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED','EXPIRED')),
    decided_by       TEXT,
    decision_note    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at       TIMESTAMPTZ
);
CREATE INDEX approvals_status_idx ON approvals(status, created_at DESC);

CREATE TABLE audit_logs (
    id               BIGSERIAL PRIMARY KEY,
    actor            TEXT NOT NULL,
    actor_type       TEXT NOT NULL CHECK (actor_type IN ('AGENT','SELLER','OPS','CARRIER','SYSTEM','BUYER')),
    action           TEXT NOT NULL,
    order_id         UUID,
    shipment_id      UUID,
    ndr_case_id      UUID,
    evidence         JSONB,
    previous_state   TEXT,
    new_state        TEXT,
    request_payload  JSONB,
    response_payload JSONB,
    request_id       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX audit_logs_case_idx ON audit_logs(ndr_case_id, created_at);
CREATE INDEX audit_logs_order_idx ON audit_logs(order_id, created_at);
CREATE INDEX audit_logs_created_idx ON audit_logs(created_at DESC);
