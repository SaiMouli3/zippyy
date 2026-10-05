# API reference

The authoritative, example-rich contract is **`docs/openapi.yaml`**, served by the running API:

* Swagger UI: <http://localhost:8080/api/docs>
* Raw spec: <http://localhost:8080/api/openapi.yaml>

## Quick tour (curl)

```bash
API=http://localhost:8080
# 1. order
curl -sX POST $API/api/orders -H 'Content-Type: application/json' -d @- <<'JSON'
{"merchantOrderId":"MERCHANT-10001","merchantId":"MRC-100",
 "customer":{"name":"Rahul Sharma","phone":"9876543210","email":"rahul@example.com"},
 "pickupAddress":{"addressLine1":"15 MG Road","city":"Bengaluru","state":"Karnataka","pincode":"560001"},
 "deliveryAddress":{"addressLine1":"22 Connaught Place","city":"New Delhi","state":"Delhi","pincode":"110001"},
 "package":{"weightGrams":1500,"lengthCm":20,"widthCm":15,"heightCm":10},"paymentType":"COD","codAmount":2500}
JSON
# 2. rates → select → shipment
curl -sX POST "$API/api/orders/ZPY-ORD-10001/rates?refresh=true"
curl -sX POST $API/api/orders/ZPY-ORD-10001/select-carrier -H 'Content-Type: application/json' \
  -d '{"carrierCode":"FASTSHIP","serviceCode":"FAST-AIR","quotedAmount":182.90,"quoteReference":null}'
curl -sX POST $API/api/orders/ZPY-ORD-10001/shipment
# 3. drive the carrier
curl -sX POST $API/api/mock-carriers/FASTSHIP/shipments/<shipmentId>/trigger -H 'Content-Type: application/json' -d '{"event":"PICKED_UP"}'
# 4. NDR agent
curl -sX POST $API/api/ndr/cases/<caseId>/contact
curl -sX POST $API/api/ndr/cases/<caseId>/buyer-reply -H 'Content-Type: application/json' -d '{"text":"Tomorrow evening after 6. Please tell security guard."}'
# 5. approvals need a role
curl -sX POST $API/api/approvals/<id>/approve -H 'X-Zippy-Role: SELLER'
```

`scripts/smoke.sh` runs the full scenario against a live stack.

## Endpoint index

| Area | Endpoints |
|---|---|
| Orders | `POST /api/orders`, `GET /api/orders`, `GET /api/orders/{orderId}` |
| Rates | `POST|GET /api/orders/{orderId}/rates`, `POST /api/orders/{orderId}/select-carrier` |
| Shipments | `POST /api/orders/{orderId}/shipment`, `GET /api/orders/{orderId}/tracking`, `GET /api/shipments` |
| Webhooks | `POST /api/webhooks/{fastship|quickexpress|reliable}`, `GET /api/webhooks-inbox` |
| NDR | `GET /api/ndr/cases`, `GET /api/ndr/cases/{id}`, `POST …/contact`, `…/buyer-reply`, `…/process`, `…/approve`, `…/reject`, `…/actions`, `GET …/timeline` |
| Approvals | `GET /api/approvals`, `POST /api/approvals/{id}/approve|reject` |
| Mock carriers | `POST /api/mock-carriers/{carrier}/shipments/{shipmentId}/trigger`, `POST …/{carrier}/faults`, `GET …/{carrier}/stats` |
| Rules | `GET /api/rules/seller`, `PUT /api/rules/seller/{merchantId}`, `GET /api/rules/carriers`, `PUT /api/rules/carriers/{code}` |
| Ops | `GET /api/audit-logs`, `GET /api/dashboard`, `GET /api/metrics`, `GET /health`, `GET /ready` |

## Mock carrier external APIs (separate service, port 9000)

| Carrier | Rate | Booking | Actions |
|---|---|---|---|
| FastShip | `POST /fastship/api/v1/rate` | `POST /fastship/api/v1/shipments` | `POST /fastship/api/v1/actions/{reattempt,reschedule,update-phone,update-address,convert-prepaid,rto}` |
| QuickExpress | `POST /quickexpress/rates/check` | `POST /quickexpress/booking/create` | `POST /quickexpress/actions/{reattempt,reschedule,contact-update,address-update,payment-mode,return}` |
| ReliableCourier | `GET /reliablecourier/shipping-options` | `PUT /reliablecourier/orders` | `POST /reliablecourier/actions` |
| Control | `POST /control/trigger`, `POST /control/config`, `GET /control/stats`, `GET /control/shipments` | | |
