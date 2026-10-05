from psycopg.types.json import Jsonb

from . import db


def seed() -> None:
    """Demo merchant + one order with a created FastShip shipment, ready to drive from Mock Carrier Control."""
    with db.conn() as c:
        c.execute("INSERT INTO merchants(id,name) VALUES ('MER-DEMO','Demo Merchant') ON CONFLICT DO NOTHING")
        if c.execute("SELECT 1 FROM orders LIMIT 1").fetchone():
            return
        c.execute("""INSERT INTO orders(id, merchant_id, merchant_order_id, customer_name, phone, address,
                         pickup_pincode, delivery_pincode, weight_grams, length_cm, width_cm, height_cm,
                         payment_mode, cod_amount, status, selected_carrier, selected_service, quoted_price)
                     VALUES (('ZPY-ORD-' || nextval('order_seq')), 'MER-DEMO','DEMO-1001','Rahul Sharma','9876543210',
                         '12 MG Road, Connaught Place, New Delhi','560001','110001',1500,20,15,10,'COD',2500,'SHIPPED',
                         'FASTSHIP','FAST-AIR',182.90)""")
        oid = c.execute("SELECT id FROM orders").fetchone()["id"]
        for carrier, svc, name, price, lo, hi in [
            ("FASTSHIP", "FAST-AIR", "Fast Air", 182.90, 2, 2),
            ("QUICKEXPRESS", "EXPRESS", "Express", 197.06, 2, 3),
            ("RELIABLECOURIER", "RC-SURFACE", "Surface", 159.30, 4, 5)]:
            c.execute("""INSERT INTO shipping_quotes(order_id,carrier,service,service_name,price,eta_min_days,eta_max_days)
                         VALUES (%s,%s,%s,%s,%s,%s,%s)""", (oid, carrier, svc, name, price, lo, hi))
        s = c.execute("""INSERT INTO shipments(order_id,carrier,service,carrier_shipment_id,tracking_number)
                         VALUES (%s,'FASTSHIP','FAST-AIR','FS-700001','FST123456789') RETURNING id""", (oid,)).fetchone()
        c.execute("""INSERT INTO shipment_events(shipment_id,carrier,tracking_number,status,event_id,raw)
                     VALUES (%s,'FASTSHIP','FST123456789','SHIPMENT_CREATED','created',%s)""",
                  (s["id"], Jsonb({"source": "seed"})))
        db.audit(c, "ORDER_CREATED", "order", oid, {"seed": True})
        db.audit(c, "SHIPMENT_CREATED", "shipment", str(s["id"]), {"seed": True})
