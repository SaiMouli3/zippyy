#!/usr/bin/env bash
# End-to-end smoke test against a running stack (default http://localhost:8080). Mirrors the demo scenario.
set -euo pipefail
API=${API:-http://localhost:8080}
SUF=${SUFFIX:-$(date +%s)}
j() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
post() { curl -sS -X POST "$API$1" -H 'Content-Type: application/json' ${3:+-H "$3"} -d "${2:-{\}}"; }

MID="SMOKE-$SUF"
ORDER=$(post /api/orders '{"merchantOrderId":"'$MID'","merchantId":"MRC-100","customer":{"name":"Rahul Sharma","phone":"9876543210","email":"rahul@example.com"},"pickupAddress":{"addressLine1":"15 MG Road","city":"Bengaluru","state":"Karnataka","pincode":"560001"},"deliveryAddress":{"addressLine1":"22 Connaught Place","city":"New Delhi","state":"Delhi","pincode":"110001"},"package":{"weightGrams":1500,"lengthCm":20,"widthCm":15,"heightCm":10},"paymentType":"COD","codAmount":2500,"language":"kn"}' | j "d['orderId']")
echo "order: $ORDER"
RATES=$(post "/api/orders/$ORDER/rates?refresh=true")
echo "$RATES" | j "[(o['carrierCode'],o['serviceCode'],o['totalCharge'],o['estimatedMinDays'],o['estimatedMaxDays']) for o in d['shippingOptions']]"
AMT=$(echo "$RATES" | j "[o['totalCharge'] for o in d['shippingOptions'] if o['carrierCode']=='FASTSHIP'][0]")
post "/api/orders/$ORDER/select-carrier" '{"carrierCode":"FASTSHIP","serviceCode":"FAST-AIR","quotedAmount":'$AMT',"quoteReference":null}' | j "d['status']"
SHIP=$(post "/api/orders/$ORDER/shipment")
echo "$SHIP" | j "(d['trackingNumber'], d['currentStatus'])"
SID=$(echo "$SHIP" | j "d['id']")
for ev in PICKED_UP IN_TRANSIT OUT_FOR_DELIVERY; do
  post "/api/mock-carriers/FASTSHIP/shipments/$SID/trigger" '{"event":"'$ev'"}' | j "('$ev', [x['status'] for x in d['deliveries']])"
done
post "/api/mock-carriers/FASTSHIP/shipments/$SID/trigger" '{"event":"NDR","ndrReason":"CUST_UNAVAILABLE"}' | j "('NDR', [x['status'] for x in d['deliveries']])"
CASE=$(curl -sS "$API/api/ndr/cases?orderId=$ORDER" | j "d['cases'][0]['id']")
echo "case: $CASE"
post "/api/ndr/cases/$CASE/contact" | j "(d['delivered'], d['channel'], d['case']['state'], d['case']['language'])"
post "/api/ndr/cases/$CASE/buyer-reply" '{"text":"Tomorrow evening after 6. Please tell security guard."}' | j "(d['intent']['intent'], d['intent']['preferredDate'], d['intent']['preferredTimeStart'], d['intent']['specialInstruction'], d['decision']['outcome'], d['case']['state'])"
post "/api/mock-carriers/FASTSHIP/shipments/$SID/trigger" '{"event":"OUT_FOR_DELIVERY"}' >/dev/null
post "/api/mock-carriers/FASTSHIP/shipments/$SID/trigger" '{"event":"DELIVERED"}' >/dev/null
curl -sS "$API/api/ndr/cases/$CASE" | j "(d['case']['state'], d['case']['outcome'], [m['direction']+':'+m['originalText'][:70] for m in d['messages']])"
curl -sS "$API/api/orders/$ORDER/tracking" | j "(d['currentStatus'], [e['status'] for e in d['history']])"
curl -sS "$API/api/ndr/cases/$CASE/timeline" | j "[e['eventType'] for e in d['timeline']]"
