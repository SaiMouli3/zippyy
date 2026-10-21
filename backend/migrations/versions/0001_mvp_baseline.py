"""MVP baseline: orders, shipping_quotes, shipments, shipment_events (as created by the MVP's create_all).

Existing databases created before migrations existed already have these tables; each is created only if
missing, so `alembic upgrade head` adopts them without touching data.

Revision ID: 0001_mvp_baseline
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_mvp_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _has(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    tz = sa.DateTime(timezone=True)
    if not _has("orders"):
        op.create_table(
            "orders",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("merchant_id", sa.String(50), nullable=False, index=True),
            sa.Column("merchant_order_id", sa.String(100), nullable=False),
            sa.Column("customer_name", sa.String(200), nullable=False),
            sa.Column("customer_phone", sa.String(20), nullable=False),
            sa.Column("pickup_pincode", sa.String(6), nullable=False),
            sa.Column("delivery_pincode", sa.String(6), nullable=False),
            sa.Column("weight_grams", sa.Integer, nullable=False),
            sa.Column("length_cm", sa.Integer, nullable=False),
            sa.Column("width_cm", sa.Integer, nullable=False),
            sa.Column("height_cm", sa.Integer, nullable=False),
            sa.Column("payment_type", sa.String(10), nullable=False),
            sa.Column("cod_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("created_at", tz, nullable=False),
            sa.Column("updated_at", tz, nullable=False),
            sa.UniqueConstraint("merchant_id", "merchant_order_id"),
        )
    if not _has("shipping_quotes"):
        op.create_table(
            "shipping_quotes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=False, index=True),
            sa.Column("batch_id", sa.String(36), nullable=False, index=True),
            sa.Column("carrier_code", sa.String(30), nullable=False),
            sa.Column("service_code", sa.String(50), nullable=False),
            sa.Column("service_name", sa.String(100), nullable=False),
            sa.Column("base_charge", sa.Numeric(12, 2), nullable=False),
            sa.Column("cod_charge", sa.Numeric(12, 2), nullable=False),
            sa.Column("additional_charges", sa.Numeric(12, 2), nullable=False),
            sa.Column("tax", sa.Numeric(12, 2), nullable=False),
            sa.Column("total_charge", sa.Numeric(12, 2), nullable=False),
            sa.Column("estimated_min_days", sa.Integer),
            sa.Column("estimated_max_days", sa.Integer),
            sa.Column("quote_reference", sa.String(100)),
            sa.Column("raw_carrier_response", sa.JSON, nullable=False),
            sa.Column("created_at", tz, nullable=False),
            sa.Column("expires_at", tz, nullable=False),
        )
    if not _has("shipments"):
        op.create_table(
            "shipments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=False, unique=True),
            sa.Column("quote_id", sa.String(36), sa.ForeignKey("shipping_quotes.id"), nullable=False),
            sa.Column("carrier_code", sa.String(30), nullable=False),
            sa.Column("carrier_shipment_id", sa.String(100)),
            sa.Column("tracking_number", sa.String(100), unique=True, index=True),
            sa.Column("selected_service_code", sa.String(50), nullable=False),
            sa.Column("quoted_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("current_status", sa.String(30), nullable=False),
            sa.Column("created_at", tz, nullable=False),
            sa.Column("updated_at", tz, nullable=False),
        )
    if not _has("shipment_events"):
        op.create_table(
            "shipment_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("shipment_id", sa.String(36), sa.ForeignKey("shipments.id"), nullable=False, index=True),
            sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
            sa.Column("carrier_status", sa.String(60), nullable=False),
            sa.Column("normalized_status", sa.String(30), nullable=False),
            sa.Column("description", sa.String(500)),
            sa.Column("location", sa.String(200)),
            sa.Column("event_time", tz, nullable=False),
            sa.Column("raw_event_payload", sa.JSON, nullable=False),
            sa.Column("received_at", tz, nullable=False),
        )


def downgrade() -> None:
    raise RuntimeError("The MVP baseline is not reversible: it would drop order and shipment history")
