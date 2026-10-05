# UI → API → Code Flow Guide

For every screen (tab) of the app: **what you see, which button does what, which file's function runs, which API is
called, which backend function answers it, which database tables are touched, and what comes back on screen.**

Line numbers (`file:line`) refer to the code at the time of writing; if they drift, search for the function name.

**Contents**
1. [How a click travels (the common path)](#1-how-a-click-travels-the-common-path)
2. [Click-by-click: "Create order & get rates"](#2-click-by-click-create-order--get-rates)
3. [Tab: Dashboard](#3-tab-dashboard)
4. [Tab: Create Order](#4-tab-create-order)
5. [Page: Shipping Rates (opened after Create Order)](#5-page-shipping-rates)
6. [Tab: Shipment Tracking](#6-tab-shipment-tracking)
7. [Tab: Mock Carrier Control](#7-tab-mock-carrier-control)
8. [Tab: NDR Cases (list)](#8-tab-ndr-cases-list)
9. [Page: NDR Case Detail](#9-page-ndr-case-detail)
10. [Master table: every button → API → function](#10-master-table)
11. [What refreshes automatically (polling)](#11-polling)

---

## 1. How a click travels (the common path)

```
React page (frontend/src/pages/X.tsx)
   │  calls  api(path, method, body)            frontend/src/api.ts:11   (fetch + JSON + error handling)
   ▼
Browser sends  http://localhost:3000/api/...    (Docker)   or   http://localhost:5173/api/...   (npm run dev)
   │  nginx (frontend/nginx.conf)  /  Vite dev proxy (frontend/vite.config.ts)  forwards /api/* to the API on :8000
   ▼
FastAPI  backend/app/main.py
   │  1. RequestIdMiddleware (logs.py) gives the request an ID, e.g. req-3f2a…, echoed in the X-Request-ID response header
   │  2. the route function validates the body with a pydantic model (schemas.py) → 422 if invalid
   │  3. the route calls ONE service function (backend/app/services/*.py)
   ▼
Service function
   │  opens a DB transaction:  with db.conn() as c:   (db.py)   → reads/writes PostgreSQL
   │  may call carriers through an adapter (carriers/*.py) → CarrierAdapter.call → HTTP to the mock carrier
   │  may use Redis (rates.py only)
   │  raises ApiError(status, message) for expected failures
   ▼
Route returns  out(data)  (util.py) = camelCase JSON   (or ApiError → {"error": "..."} with that HTTP status)
   ▼
api.ts parses it  →  page stores it in React state  →  the screen re-renders
   (if the response is an error, api.ts throws ApiError(message); the page catches it and shows it in the red <ErrorBox>)
```

`useFetch(path, pollMs)` (`frontend/src/ui.tsx:49`) is the helper pages use for **GET** data: it loads once, and re-loads every `pollMs` milliseconds if given.
Buttons that **change** something call `api(...)` directly with `POST`.

---

## 2. Click-by-click: "Create order & get rates"

This is the first thing a user does. It is really **two pages and 3 API calls**.

### Part 1 – the button on the Create Order tab

| # | Where | What happens |
|---|---|---|
| 1 | `frontend/src/pages/CreateOrder.tsx:55` | The button `Create order & get rates` is `type="submit"`, so the form's `onSubmit={submit}` runs. |
| 2 | `CreateOrder.tsx:22` `submit(e)` | `preventDefault`, set `busy=true` (button shows "Creating…"), clear old error/duplicate notice. |
| 3 | `CreateOrder.tsx:25` | Calls **`api('/api/orders', 'POST', {...})`**. Numbers are converted with `Number(...)` (`weightGrams`, `lengthCm`, `widthCm`, `heightCm`); `codAmount` is sent as 0 when payment is PREPAID. |
| 4 | `frontend/src/api.ts:11` `api()` | `fetch('/api/orders', {method:'POST', body: JSON})`. |
| 5 | `backend/app/main.py:98` `create_order(body: OrderIn)` | FastAPI first validates the JSON against `OrderIn` (`schemas.py`): phone = 10 digits, pincodes = 6 digits, grams/dimensions > 0, paymentMode COD/PREPAID. Invalid → HTTP 422 and the page shows the field errors. |
| 6 | `backend/app/services/orders.py:32` `create_order(data)` | Default merchant if missing → COD needs `codAmount>0` → insert merchant if new → **if `(merchantId, merchantOrderId)` already exists: `_replay` (line 22)** returns the existing order (duplicate) or raises 409 if the details differ → otherwise `INSERT INTO orders` with id `'ZPY-ORD-' || nextval('order_seq')` → `db.audit(... "ORDER_CREATED")` → log line `ORDER_CREATED`. |
| 7 | `main.py:98-100` | Returns **HTTP 201** (new) or **HTTP 200** (duplicate) with the order JSON plus `duplicate: true/false`. |
| 8 | `CreateOrder.tsx:28` | `if (o.duplicate) setDup(o)` → shows the yellow *Duplicate protection* box with a link; **else `nav('/orders/ZPY-ORD-10002/rates')`**. |

Database tables touched in Part 1: `merchants` (insert if new), `orders` (insert), `audit_logs` (insert).

Example request / response:
```json
POST /api/orders
{ "merchantId":"MRC-100", "merchantOrderId":"SHOP-5001", "customerName":"Rahul Sharma", "phone":"9876543210",
  "address":"12 MG Road, Connaught Place, New Delhi", "pickupPincode":"560001", "deliveryPincode":"110001",
  "weightGrams":1500, "lengthCm":20, "widthCm":15, "heightCm":10, "paymentMode":"COD", "codAmount":2500 }

201 →
{ "id":"ZPY-ORD-10002", "merchantId":"MRC-100", "merchantOrderId":"SHOP-5001", "customerName":"Rahul Sharma",
  "weightGrams":1500, "lengthCm":20, "widthCm":15, "heightCm":10, "paymentMode":"COD", "codAmount":2500.0,
  "status":"CREATED", "selectedCarrier":null, "selectedService":null, "quotedPrice":null, "duplicate":false, ... }
```

### Part 2 – the Rates page opens and fetches the rates automatically

`App.tsx:34` maps the route `/orders/:id/rates` to `pages/Rates.tsx`. **No second click is needed**; as soon as the page mounts it makes two requests:

| # | Where | API call | Purpose |
|---|---|---|---|
| 9 | `Rates.tsx:9` `useFetch('/api/orders/{id}')` | **`GET /api/orders/{id}`** → `main.py:110 get_order` → `orders.order_detail` (`orders.py:70`) | Loads the order (for the subtitle line, and later to know which carrier is selected / whether a shipment exists). Tables read: `orders`, `shipments`. |
| 10 | `Rates.tsx:21` `useEffect(() => fetchRates(), [id])` → `fetchRates` (`Rates.tsx:16`) | **`POST /api/orders/{id}/rates`** | Fetches the rates. |

(In development, React StrictMode runs effects twice, so you may see the rates call twice; the backend locks the order row while storing quotes, so this is safe.)

What the backend does for `POST /api/orders/{id}/rates` – `main.py:126 post_rates` → **`rates.get_rates(order_id, refresh=False)`** (`services/rates.py:110`):

| Step | Code | What |
|---|---|---|
| a | `rates.py:110-112` | Load the order from `orders` (404 if unknown). |
| b | `rates.py:32` `cache_key(order)` | Build `zippy:rates:{merchantId}:{pickup}:{delivery}:{weightGrams}:{L}:{W}:{H}:{COD/PREPAID}:{codAmount}`. |
| c | `rates.py:38` `_cache_get(key)` | Redis `GET`. **HIT** → copy cached quotes into this order's `shipping_quotes` (`_store_quotes`, line 95) and return `cached:true`. **MISS** → continue. **Redis down** → log `CACHE_UNAVAILABLE`, continue. |
| d | `rates.py:68` `_fetch_all(order)` | Starts 3 threads, one per adapter in `carriers/registry.py: ADAPTERS`, waits at most `CARRIER_TIMEOUT_MS + 1 s`. |
| e | each adapter's `get_rates(order)` (`carriers/fastship.py`, `quickexpress.py`, `reliable.py`) | Builds that carrier's own request format and calls **`CarrierAdapter.call`** (`carriers/base.py:65`) which does the HTTP call with timeout + logging. |
| f | mock carrier endpoints (`mock_carriers/router.py`) | `POST /mock/fastship/rates` (line 71) · `POST /mock/quickexpress/rates` (101) · `GET /mock/reliable/rates` (131). Each answers in its own format. |
| g | adapter `normalize_rates` | Converts to the common `NormalizedRate`: `{carrier, carrierName, service, serviceName, price, etaMinDays, etaMaxDays}`. |
| h | `rates.py:68-92` | Successes → `rates[]`; failures (timeout / HTTP error / unreachable) → `errors[]`. If **all** failed → HTTP 502 with details. |
| i | `rates.py:95` `_store_quotes` | Delete + insert this order's rows in `shipping_quotes` (skipped if a shipment already exists). Also `audit_logs` `RATES_FETCHED`. |
| j | `rates.py:52` `_cache_set` | Redis `SET` with TTL **300 s** (complete) or **60 s** (partial). |
| k | `main.py:126` | Returns `{rates, errors, partial, cached, cacheStatus, cacheKey}`. |

The three carrier calls in detail (the same order: 1.5 kg, 20×15×10 cm, 560001 → 110001, COD):

| Carrier | Request the adapter sends | Raw reply | After normalization |
|---|---|---|---|
| FastShip | `POST /mock/fastship/rates` `{origin,destination,weightGrams,dimensions{lengthCm,widthCm,heightCm},cod,codAmount}` | `{"service":"FAST-AIR","price":182.9,"etaDays":2}` | FASTSHIP · Fast Air · 182.90 · 2–2 days |
| QuickExpress | `POST /mock/quickexpress/rates` `{from_pin,to_pin,weight_grams,dimensions_cm{l,w,h},payment_mode,cod_value}` | `{"product":"EXPRESS","payable":197.06,"deliveryEstimate":3}` | QUICKEXPRESS · Express · 197.06 · 2–3 days |
| ReliableCourier | `GET /mock/reliable/rates?pickup=560001&drop=110001&wt=1.5&l=20&b=15&h=10` | `{"options":[{"code":"RC-SURFACE","amount":159.3,"days":5}]}` | RELIABLECOURIER · Surface · 159.30 · 4–5 days |

Response to the browser:
```json
{ "rates":[ {"carrier":"FASTSHIP","carrierName":"FastShip","service":"FAST-AIR","serviceName":"Fast Air","price":182.9,"etaMinDays":2,"etaMaxDays":2},
            {"carrier":"QUICKEXPRESS", ... "price":197.06,"etaMinDays":2,"etaMaxDays":3},
            {"carrier":"RELIABLECOURIER", ... "price":159.3,"etaMinDays":4,"etaMaxDays":5} ],
  "errors":[], "partial":false, "cached":false, "cacheStatus":"MISS",
  "cacheKey":"zippy:rates:MRC-100:560001:110001:1500:20:15:10:COD:2500" }
```

What is then drawn on screen (`Rates.tsx`): see [section 5](#5-page-shipping-rates).

---

## 3. Tab: Dashboard

* **Sidebar link:** "Dashboard" → route `/` (`App.tsx:32`) → `frontend/src/pages/Dashboard.tsx`.
* **API:** `GET /api/dashboard` (`Dashboard.tsx:5`, polled **every 4 s**) → `main.py:87 get_dashboard` → `services/dashboard.py:4 summary()`.
* **Tables read:** `orders`, `shipments`, `ndr_cases`.
* **What `summary()` returns:**
  `totals {orders, shipments, inTransit, delivered, ndrCases}` · `recentShipments` (5 most recently updated, with customer name) · `recentNdr` (5 newest NDR cases).
  *"In transit"* counts shipments whose status is `PICKED_UP`, `IN_TRANSIT` or `OUT_FOR_DELIVERY`.
* **What you see**
  * Five number cards: **Total Orders · Shipments · In Transit · Delivered · NDR Cases** (shows `–` until data arrives).
  * **Recent shipments** table: Order (link → `/orders/{id}/tracking`), Customer, Carrier, Status badge.
  * **Recent NDR cases** table: Case (link → `/ndr/{id}`), Order, Reason, Status badge; "No NDR cases yet" if empty.
* **Buttons:** none; only links.

---

## 4. Tab: Create Order

* **Sidebar link:** "Create Order" → `/orders/new` → `pages/CreateOrder.tsx`.
* **API on open:** none (static, prefilled form: Rahul Sharma, 560001 → 110001, 1500 g, 20×15×10 cm, COD ₹2500; Merchant ID `MRC-100`; Merchant order ID auto-generated `SHOP-####` at `CreateOrder.tsx:10`).
* **Fields shown:** Merchant ID, Merchant order ID, Customer name, Phone, Delivery address, Pickup pincode, Delivery pincode, Weight (g), Length / Width / Height (cm), Payment (COD/PREPAID), COD amount (only when COD).
* **Button `Create order & get rates`** → full trace in [section 2](#2-click-by-click-create-order--get-rates): `POST /api/orders` → `orders.create_order`.
* **Results on screen**
  * New order → automatically navigates to the **Shipping Rates** page.
  * Same *Merchant order ID* submitted again → stays on the page and shows *"Duplicate protection: order ZPY-ORD-… already exists for merchant order ID … — no new order was created. Continue with ZPY-ORD-…"* (the API returned `duplicate:true`).
  * Same ID with different details (e.g. other weight) → HTTP 409, red error box: *merchantOrderId '…' was already used for order … with different details*.
  * Invalid input (e.g. phone not 10 digits) → red error box with `phone: …` messages (from FastAPI's 422, formatted in `api.ts:19`).
* **Tip:** to create another real order change the *Merchant order ID* (or clear it – then no idempotency check is applied).

---

## 5. Page: Shipping Rates

* **How you get here:** after creating an order (automatic), or via the *Continue with …* link in the duplicate notice. Route `/orders/:id/rates` → `pages/Rates.tsx`. It has no sidebar link.
* **APIs called**

| When | Call | Backend |
|---|---|---|
| Page opens | `GET /api/orders/{id}` (`Rates.tsx:9`) | `main.py:110` → `orders.order_detail` |
| Page opens | `POST /api/orders/{id}/rates` (`Rates.tsx:16-21`) | `main.py:126` → `rates.get_rates` (traced in section 2) |
| Click **Refresh rates** | `POST /api/orders/{id}/rates?refresh=true` (`Rates.tsx:49`) | same, `refresh=True` skips the Redis lookup and re-queries all carriers, then overwrites the cache |
| Click **Select Carrier** on a card | `POST /api/orders/{id}/select-carrier` body `{carrier, service}` (`Rates.tsx:23-27`), then re-loads the order (`reload()`) | `main.py:144` → `rates.select_carrier` (`rates.py:144`) |
| Click **Create Shipment** | `POST /api/orders/{id}/shipment` (`Rates.tsx:28-32`), then `nav('/orders/{id}/tracking')` | `main.py:153` → `shipments.create_shipment` (`shipments.py:13`) |
| Change the **Sort by** dropdown | **no API call** – sorting happens in the browser (`Rates.tsx:35-36`) | – |

* **What you see (top to bottom)**
  1. Title *Shipping rates · ZPY-ORD-…* and a subtitle: customer · `560001 → 110001` · weight in g · L×W×H cm · payment (+ COD amount).
  2. **One amber banner per failed carrier**, e.g. *"QuickExpress failed (TIMEOUT, 3012 ms): QuickExpress did not respond within 3000 ms. Showing the other carriers."* (from `errors[]`).
  3. A row with the **Refresh rates** button, a small **cache label** and the **Sort by** dropdown.
     Cache label meanings: *Served from Redis cache* (HIT) · *Live from carriers (cache miss)* · *Live from carriers (refreshed)* · *Live from carriers (Redis unavailable — caching skipped)*; plus *· partial result* when a carrier failed.
  4. The full **cache key** in small grey text (so you can see that changing weight/pincode/payment changes the key).
  5. **One card per carrier**: carrier name, service name, big **₹ price**, ETA (`2 days` or `2–3 days`), a green *Cheapest* tag on the lowest price, and a **Select Carrier** button.
     Sort options: *Price (low→high)* (default), *Delivery time (fastest)*, *Carrier name*.
  6. After selecting: that card gets an indigo ring and its button reads **Selected ✓**; the other cards stay clickable (you can change your mind until a shipment exists).
  7. Bottom: **Create Shipment** button (disabled until a carrier is selected) and, once selected, *Selected: FastShip ₹182.90*.
* **What the select-carrier call does** (`rates.select_carrier`): checks the carrier exists, locks the order, refuses if a shipment already exists, finds the stored quote in `shipping_quotes`, rejects a client-sent price that differs from the stored one (409 *Quoted amount cannot be modified*), then updates `orders` (`selected_carrier`, `selected_service`, `quoted_price`, status `CARRIER_SELECTED`) and writes an audit row. The UI never sends a price – the server uses its own stored quote.
* **What the create-shipment call does** (`shipments.create_shipment`): locks the order; calls the selected adapter's `create_shipment` over HTTP (FastShip `POST /shipments`, QuickExpress `POST /bookings`, ReliableCourier `POST /consignments`); inserts a `shipments` row (tracking number like `FST725470278`), the first `shipment_events` row (`SHIPMENT_CREATED`), sets the order to `SHIPPED`, audit row. On carrier failure → 502 and the red error box shows *"FastShip failed to create the shipment: …"*; nothing is saved.
  Success → browser goes to the **Tracking** page for this order, and the button here would read *Shipment created*.

---

## 6. Tab: Shipment Tracking

* **Sidebar link:** "Shipment Tracking" → `/tracking` → `pages/Tracking.tsx` (no order selected) – shows the **picker**.
  Clicking an order in the picker, the Dashboard, or finishing *Create Shipment* goes to `/orders/{id}/tracking` (same component with an `id`).

**A. Picker (no order chosen)**
* API: `GET /api/shipments` (`Tracking.tsx:7`, every 4 s) → `main.py:165 list_shipments` → `shipments.list_shipments` (`shipments.py:55`; joins `shipments` + `orders`).
* Shows a table *Select a shipment*: Order (link), Customer, Carrier, Tracking number, Status badge.

**B. Tracking of one order**
* API: `GET /api/orders/{id}/tracking?includeRaw=true` (`Tracking.tsx:21`, **every 3 s**) → `main.py:160 get_tracking` → `shipments.tracking` (`shipments.py:41`).
  Tables read: `orders`, `shipments`, `shipment_events` (ordered by id). With `includeRaw=true` each event also carries `raw` (carrier's original payload) and `normalized` (Zippy's interpretation).
  404 *"No shipment for this order yet"* if the order was never shipped (shown in the red box).
* Response shape: `{orderId, carrier, service, trackingNumber, carrierShipmentId, shipmentId, currentStatus, statusHistory:[{status, reason, eventId, occurredAt, raw, normalized}]}`.
* **What you see**
  * Title *Tracking · ZPY-ORD-…* and subtitle *FastShip · FST725470278*.
  * **Progress** card: current status badge and a checklist `Shipment Created → Picked Up → In Transit → Out For Delivery → Delivered`; steps already reached are green dots; if an NDR happened an extra red line *Delivery attempt failed (NDR)* appears.
  * **Status history** card: every event in order, with status badge, NDR reason if any, timestamp, and (except the first) an expandable **raw / normalized** block showing the carrier payload and the normalized event side by side.
  * A link *Open Mock Carrier Control →* (navigates to `/mock-control`).
* The page re-polls every 3 s, so pressing buttons on Mock Carrier Control makes new history entries appear without reloading.
* **Buttons that call APIs:** none (only navigation).

---

## 7. Tab: Mock Carrier Control

Stands in for the carriers' systems: you press a button, the "carrier" sends a real webhook to Zippy.

* **Sidebar link:** "Mock Carrier Control" → `/mock-control` → `pages/MockControl.tsx`.
* **APIs on open (polled):**
  * `GET /api/shipments` (every 3 s) → `shipments.list_shipments` → fills the shipment dropdown.
  * `GET /api/webhook-quarantine` (every 4 s) → `main.py:194 quarantine` → `shipments.list_quarantine` (`shipments.py:145`) → fills the quarantine table.
* **What you see**
  * **Shipment** card: dropdown *ORDER · Carrier · TRACKING · Status* (defaults to the newest shipment), the current status badge, five buttons **Pickup · In Transit · Out For Delivery · Trigger NDR (red) · Delivered**, a **Resend last webhook (duplicate)** button, and an **NDR reason** dropdown (Customer Unavailable, Customer Refused, Address Issue, Phone Unreachable, COD Not Ready).
  * **Webhooks sent** card: the last 6 webhooks – a line like `POST /api/webhooks/fastship → HTTP 200 · processed · NDR-1003`, an explanatory message if any, and the exact payload sent in **that carrier's own format**.
  * **Webhook quarantine** table (below): When · Carrier · Tracking · Reason badge (`Unknown Tracking Number`, `Invalid Transition`, `Unparseable Payload`) · Detail (`DELIVERED → PICKED_UP`).

### What a button click does (all five status buttons)

```
MockControl.tsx:17 fire(status)
  └─ api('/api/mock/{fastship|quickexpress|reliable}/{trackingNumber}/event', 'POST', {status, reason?})      (MockControl.tsx:23)
       └─ mock_carriers/router.py:203  send_event()     ← the "carrier"
            ├─ build_webhook() (router.py:179) → payload in THAT carrier's format, e.g.
            │     FastShip       {"trackingNumber":"FST…","status":"OFD","eventId":"8ed7…"}
            │     QuickExpress   {"awb":"QXP…","id":"9f2c…","event":{"code":"OUT_FOR_DELIVERY"}}
            │     Reliable       {"reference":"RLC…","seq":"17","state":"Out For Delivery"}
            │     (NDR adds reasonCode / event.reason / undeliveredCode)
            └─ HTTP POST  {WEBHOOK_BASE_URL}/api/webhooks/{slug}    (a real HTTP call back into the same API)
                 └─ main.py:187 webhook()  →  shipments.handle_webhook(slug, payload)   (shipments.py:71)
```

`handle_webhook` – the decision tree, with the HTTP code the carrier receives:

| Check | Result | HTTP | DB effect |
|---|---|---|---|
| Adapter can't parse the payload | `UNPARSEABLE_PAYLOAD` | 400 | row in `webhook_quarantine` |
| No shipment with that carrier + tracking number | `UNKNOWN_TRACKING_NUMBER` | 202 | quarantine row; **no shipment created** |
| Same carrier+tracking+status+eventId already stored | `{"status":"duplicate"}` | 200 | nothing |
| Status change not allowed by `transitions.py` (e.g. `DELIVERED → PICKED_UP`) | `INVALID_TRANSITION` | 202 | quarantine row; shipment unchanged |
| Otherwise | `{"status":"processed", "shipmentStatus":…, "ndrCaseId":…}` | 200 | `shipment_events` row (raw + normalized), `shipments.status` updated, `orders.status`=DELIVERED on delivery, and for **NDR** a new row in `ndr_cases` (reason, attempt = previous cases + 1) + audit `NDR_CREATED` |

Back in the browser `fire()` receives `{sent, webhookStatus, webhookResponse}`, prepends it to the *Webhooks sent* list (`MockControl.tsx:25`), and reloads the shipments and quarantine lists.

* **Pickup / In Transit / Out For Delivery / Delivered** → event with status `PICKED_UP / IN_TRANSIT / OUT_FOR_DELIVERY / DELIVERED`.
* **Trigger NDR** → status `NDR` plus the chosen reason; the response contains the new case id (e.g. `NDR-1003`), which then shows on the NDR Cases tab.
* **Resend last webhook (duplicate)** (`MockControl.tsx:42`) → sends the **same status with the same event id** as the last one. Zippy answers `duplicate` and no new history row appears.
* Allowed order: Pickup → In Transit → Out For Delivery → (NDR → Out For Delivery →) Delivered. Pressing something illegal (e.g. *Pickup* after *Delivered*) is accepted by the mock but **quarantined** by Zippy: you'll see `HTTP 202 · quarantined (INVALID_TRANSITION)` in *Webhooks sent* and a row in the quarantine table.

---

## 8. Tab: NDR Cases (list)

* **Sidebar link:** "NDR Cases" → `/ndr` → `pages/NdrList.tsx`.
* **API:** `GET /api/ndr` (`NdrList.tsx:5`, every 3 s) → `main.py:199 list_ndr` → `ndr.list_cases` (`ndr.py:35`; joins `ndr_cases`, `orders`, `shipments`).
* **What you see:** a table with **Case ID** (link, e.g. `NDR-1003`) · **Order** · **Customer** · **Carrier** · **Reason** · **Attempt N** · **Status** badge (`Open`, `Needs Approval`, `Action Submitted`, `Carrier Accepted`, `Resolved`, `Action Failed`). Empty state: *No NDR cases. Trigger one from Mock Carrier Control.*
* **Buttons:** none; clicking the Case ID opens the detail page.
* New rows appear here only after **Trigger NDR** on the Mock Carrier Control tab (the webhook creates the case).

---

## 9. Page: NDR Case Detail

* **How you get here:** click a Case ID (NDR list or dashboard). Route `/ndr/:id` → `pages/NdrDetail.tsx`.
* **API on open:** `GET /api/ndr/{id}` (`NdrDetail.tsx:8`, re-polled every 5 s) → `main.py:208 get_ndr` → `ndr.case_detail` (`ndr.py:44`).
  Returns the case + customer + shipment info + `lastIntent`, `lastDecision`, `messages[]`, `actions[]`, `audit[]` (tables: `ndr_cases`, `orders`, `shipments`, `conversation_messages`, `carrier_actions`, `audit_logs`).
* Every action button uses `run(path, body)` (`NdrDetail.tsx:13`): `POST /api/ndr/{id}/{path}`; the response is the **updated case**, which replaces the page state immediately (no waiting for the poll).

**Layout – three columns**

1. **Left:** *Case* (status badge, reason, attempt number) · *Customer* (name, phone, address, pincode, COD ₹ amount) · *Shipment* (carrier, tracking number, shipment status).
2. **Middle:** *Buyer conversation (simulated WhatsApp)* – chat bubbles: white = **Agent**, green = **Buyer**, with timestamps. Underneath:
   * before contact: the button **Contact Buyer**;
   * after contact: a text box ("Type as buyer, e.g. *Yes tomorrow evening after 6*") and **Send** (Enter also sends). Disabled once the case is `ACTION_SUBMITTED / CARRIER_ACCEPTED / RESOLVED`.
3. **Right:** *AI intent → rules → action* · *Carrier actions* (only after a reattempt) · *Audit trail* (event names with times).

**Buttons, one by one**

| Button | Frontend | API | Backend | What changes |
|---|---|---|---|---|
| **Contact Buyer** | `NdrDetail.tsx:68` → `run('contact')` | `POST /api/ndr/{id}/contact` | `main.py:214` → `ndr.contact_buyer` (`ndr.py:58`) | Inserts an **Agent** message *"Hi Rahul, your parcel could not be delivered today because we couldn't reach you at the delivery address. Would you like us to attempt delivery again?"* (text depends on the NDR reason); audit `BUYER_CONTACTED`. Calling it twice does not add a second message. |
| **Send** (buyer message) | `NdrDetail.tsx:18` `send()` → `run('message', {message})` | `POST /api/ndr/{id}/message` | `main.py:221` → `ndr.buyer_message` (`ndr.py:89`) | 1) stores the **Buyer** message, audit `BUYER_MESSAGE_RECEIVED`; 2) `ai/intent.py: MockIntentExtractor.extract` → intent, date, time, confidence, audit `INTENT_EXTRACTED`; 3) `rules.py: evaluate` → decision `ALLOWED / REQUIRES_APPROVAL / NEEDS_CLARIFICATION / NO_ACTION`; 4) saves `last_intent` + `last_decision` on the case (status → `NEEDS_APPROVAL` if approval is required, else `OPEN`); 5) stores an **Agent** reply, e.g. *"Thanks! I've noted your request for tomorrow (After 6 PM). I'll check this with the carrier and update you once they respond."* The right panel now fills in. **It does not promise delivery.** |
| **Request Reattempt** | `NdrDetail.tsx:89` → `run('reattempt')` – **enabled only if** the decision is `ALLOWED` **and** status is `OPEN` or `ACTION_FAILED` | `POST /api/ndr/{id}/reattempt` | `main.py:232` → `ndr.reattempt` (`ndr.py:114`) | See below. |

**What `reattempt` does (three stages)**
1. *Validate & record "submitted"* – re-runs the rules on the stored intent (it does not trust the stored decision); if not allowed → HTTP 409 (red box shows *Rules engine does not allow an automatic reattempt*). Otherwise: `carrier_actions` row `ACTION_SUBMITTED`, case → `ACTION_SUBMITTED`, **Agent message: "Your reattempt request has been submitted to the carrier."**, audit `CARRIER_ACTION_SUBMITTED`.
2. *Call the carrier* via the adapter: FastShip `POST /mock/fastship/ndr-action` · QuickExpress `POST /mock/quickexpress/ndr/{awb}/reattempt` · ReliableCourier `POST /mock/reliable/consignments/{ref}/redeliver` (each answers in its own format; the adapter turns it into `ACCEPTED` / `REJECTED`).
3. *Record the outcome* –
   **Accepted:** action `CARRIER_ACCEPTED` → case `CARRIER_ACCEPTED` → **Agent message "The carrier has accepted the reattempt request."** → audit `CARRIER_ACTION_ACCEPTED` → case `RESOLVED`.
   **Rejected / error / timeout:** action `REJECTED`, case `ACTION_FAILED`, Agent message *"The carrier could not confirm the reattempt yet. Our team will follow up with you."* (the word "accepted" is never written), button becomes usable again.

**The right panel in detail**
* *Extracted intent:* e.g. `RESCHEDULE_DELIVERY`, `Date: tomorrow`, `Time: After 6 PM`, `Confidence: 95%` (from `last_intent`).
* *Rules engine:* a badge (`Allowed` / `Requires Approval` / `Needs Clarification`), bullet reasons (e.g. *Same address and phone*, *Reschedule within 2 days*) and *Reattempt on 2026-10-06*.
* If the decision is not `ALLOWED`, a note says *Automatic reattempt is not permitted for this request*, and the button stays disabled.
* *Carrier actions:* badge (`Carrier Accepted`) and the carrier's message (*Reattempt scheduled*).
* *Audit trail:* `NDR_CREATED, BUYER_CONTACTED, BUYER_MESSAGE_RECEIVED, INTENT_EXTRACTED, CARRIER_ACTION_SUBMITTED, CARRIER_ACTION_ACCEPTED`.

**Things to try in the chat and what you will see**

| Buyer types | Intent | Rules outcome | Effect |
|---|---|---|---|
| `Yes tomorrow evening after 6` | RESCHEDULE_DELIVERY | Allowed | Request Reattempt works → accepted → Resolved |
| `come tomorrow` / `payment ready` | RESCHEDULE_DELIVERY / COD_READY | Allowed | same |
| `come on friday` | RESCHEDULE_DELIVERY | Requires Approval (more than 2 days away) | button disabled, status *Needs Approval* |
| `cancel this order` / `I don't want it` | CANCEL_ORDER / REFUSE_ORDER | Requires Approval | blocked |
| `my address is wrong` | ADDRESS_CORRECTION | Requires Approval | blocked |
| `hello` | UNKNOWN | Needs Clarification | agent asks which day/time suits |

After Resolved, go to **Mock Carrier Control** and press **Out For Delivery** then **Delivered** (a shipment in `NDR` may go to Out For Delivery again or straight to Delivered); the Tracking tab then shows the full history.

---

## 10. Master table

| Screen | Button / action | Frontend function (file:line) | API | Route fn (`main.py`) | Service fn | Main tables |
|---|---|---|---|---|---|---|
| Dashboard | (auto, 4 s) | `useFetch` `Dashboard.tsx:5` | `GET /api/dashboard` | `get_dashboard` :87 | `dashboard.summary` | orders, shipments, ndr_cases |
| Create Order | **Create order & get rates** | `submit` `CreateOrder.tsx:22` | `POST /api/orders` | `create_order` :98 | `orders.create_order` :32 | merchants, orders, audit_logs |
| Rates | (page opens) | `useFetch` `Rates.tsx:9` | `GET /api/orders/{id}` | `get_order` :110 | `orders.order_detail` :70 | orders, shipments |
| Rates | (page opens) / **Refresh rates** | `fetchRates` `Rates.tsx:16` | `POST /api/orders/{id}/rates[?refresh=true]` | `post_rates` :126 | `rates.get_rates` :110 → adapters → mock carriers | orders, shipping_quotes, audit_logs, Redis |
| Rates | **Select Carrier** | `select` `Rates.tsx:23` | `POST /api/orders/{id}/select-carrier` | `select_carrier` :144 | `rates.select_carrier` :144 | shipping_quotes, orders, audit_logs |
| Rates | **Create Shipment** | `ship` `Rates.tsx:28` | `POST /api/orders/{id}/shipment` | `create_shipment` :153 | `shipments.create_shipment` :13 → adapter → mock carrier | orders, shipments, shipment_events, audit_logs |
| Rates | Sort by | `setSort` (browser only) | – | – | – | – |
| Tracking (picker) | (auto, 4 s) | `Picker` `Tracking.tsx:7` | `GET /api/shipments` | `list_shipments` :165 | `shipments.list_shipments` :55 | shipments, orders |
| Tracking | (auto, 3 s) | `useFetch` `Tracking.tsx:21` | `GET /api/orders/{id}/tracking?includeRaw=true` | `get_tracking` :160 | `shipments.tracking` :41 | shipments, shipment_events |
| Mock Control | (auto) | `MockControl.tsx:9-10` | `GET /api/shipments`, `GET /api/webhook-quarantine` | `list_shipments`, `quarantine` :194 | `list_shipments`, `list_quarantine` :145 | shipments, webhook_quarantine |
| Mock Control | **Pickup / In Transit / Out For Delivery / Trigger NDR / Delivered / Resend** | `fire` `MockControl.tsx:17` | `POST /api/mock/{slug}/{tracking}/event` → *(mock carrier calls)* `POST /api/webhooks/{slug}` | `send_event` (`router.py:203`) → `webhook` :187 | `build_webhook`, then `shipments.handle_webhook` :71 | shipment_events, shipments, orders, ndr_cases, webhook_quarantine, audit_logs |
| NDR Cases | (auto, 3 s) | `useFetch` `NdrList.tsx:5` | `GET /api/ndr` | `list_ndr` :199 | `ndr.list_cases` :35 | ndr_cases, orders, shipments |
| NDR Detail | (page opens, 5 s) | `useFetch` `NdrDetail.tsx:8` | `GET /api/ndr/{id}` | `get_ndr` :208 | `ndr.case_detail` :44 | ndr_cases, conversation_messages, carrier_actions, audit_logs |
| NDR Detail | **Contact Buyer** | `run('contact')` :68 | `POST /api/ndr/{id}/contact` | `contact` :214 | `ndr.contact_buyer` :58 | conversation_messages, audit_logs |
| NDR Detail | **Send** | `send` :18 | `POST /api/ndr/{id}/message` | `message` :221 | `ndr.buyer_message` :89 → `extractor.extract`, `rules.evaluate` | conversation_messages, ndr_cases, audit_logs |
| NDR Detail | **Request Reattempt** | `run('reattempt')` :89 | `POST /api/ndr/{id}/reattempt` | `reattempt` :232 | `ndr.reattempt` :114 → adapter → mock carrier | carrier_actions, ndr_cases, conversation_messages, audit_logs |

---

## 11. Polling

| Screen | Polls | Every |
|---|---|---|
| Dashboard | `/api/dashboard` | 4 s |
| Shipment Tracking (picker) | `/api/shipments` | 4 s |
| Shipment Tracking (one order) | `/api/orders/{id}/tracking?includeRaw=true` | 3 s |
| Mock Carrier Control | `/api/shipments` · `/api/webhook-quarantine` | 3 s · 4 s |
| NDR Cases | `/api/ndr` | 3 s |
| NDR Detail | `/api/ndr/{id}` | 5 s |
| Create Order, Shipping Rates | nothing (rates are fetched once per visit, or on *Refresh rates*) | – |

Because the tabs poll, you can keep Mock Carrier Control open in one browser tab and Shipment Tracking / NDR Cases in another and watch the
changes appear by themselves a few seconds after each webhook.

---

*For the backend internals behind each function (locking, caching, idempotency, state machines) see [`CODEBASE_GUIDE.md`](CODEBASE_GUIDE.md).*
