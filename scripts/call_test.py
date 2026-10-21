"""Create one shipment in a live (non-demo) workspace and fail its delivery, so the NDR agent calls the customer.

Run from backend/ with the app's .env loaded and the worker running:
    PYTHONPATH=. .venv/bin/python ../scripts/call_test.py --name Sai --phone +919876543210
    PYTHONPATH=. .venv/bin/python ../scripts/call_test.py --name Sai --phone +919876543210 --reason ADDRESS_ISSUE --cod 499

Only use numbers whose owners agreed to a test call. Calls go out 10:00-19:30 IST (contact policy voice window).
--cod also triggers the pre-delivery confirmation call at OUT_FOR_DELIVERY, so the customer gets two calls.
"""
import argparse
import secrets
from datetime import timedelta

from sqlalchemy import select

from app.db import new_session
from app.platform import clock
from app.platform.audit import Actor
from app.platform.models import Merchant
from app.platform.shipments import AddressIn, ConsentIn, CustomerIn, ShipmentImport, import_shipment
from app.platform.simulation.carrier_sim import schedule_scan

REASONS = ("CUSTOMER_UNAVAILABLE", "REFUSED", "ADDRESS_ISSUE", "PHONE_UNREACHABLE", "COD_NOT_READY", "OTHER")

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True)
ap.add_argument("--phone", required=True, help="E.164, e.g. +919876543210")
ap.add_argument("--workspace", default="MER-CALL-TEST")
ap.add_argument("--reason", default="CUSTOMER_UNAVAILABLE", choices=REASONS)
ap.add_argument("--cod", type=int, default=0, help="COD amount in rupees; 0 = prepaid")
ap.add_argument("--carrier", default="FASTSHIP", choices=("FASTSHIP", "QUICKEXPRESS", "RELIABLE"))
args = ap.parse_args()

db = new_session(system=True)
m = db.scalars(select(Merchant).where(Merchant.code == args.workspace)).one()
if m.is_demo:
    raise SystemExit(f"{args.workspace} is a demo workspace: it only uses simulators and never calls anyone")

ref = secrets.token_hex(3).upper()
now = clock.now()
data = ShipmentImport(
    merchant_order_id=f"CALLTEST-{ref}",
    customer=CustomerIn(name=args.name, phone=args.phone),
    address=AddressIn(line1="12 Test Street", city="Hyderabad", state="Telangana", pincode="500081", landmark="Near test park"),
    payment_mode="COD" if args.cod else "PREPAID", cod_amount_paise=args.cod * 100, order_value_paise=max(args.cod, 499) * 100,
    carrier_code=args.carrier, awb=f"FSTTEST{ref}", consent=ConsentIn(voice=f"Agreed to a test call ({ref})"),
    eta_start=now, eta_end=now + timedelta(hours=8))
shipment, _ = import_shipment(db, m.id, data, Actor("system", "call-test", "Call test script"))
# The worker delivers these as signed carrier webhooks through the normal ingestion path.
for i, status in enumerate(("PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERY_FAILED")):
    schedule_scan(db, shipment, status, now + timedelta(seconds=5 * (i + 1)),
                  args.reason if status == "DELIVERY_FAILED" else None)
db.commit()
print(f"Shipment {shipment.code} (AWB {shipment.tracking_number}) for {args.name} in {args.workspace}; "
      f"delivery fails in ~20 s ({args.reason}), then the agent calls {args.phone}.")
