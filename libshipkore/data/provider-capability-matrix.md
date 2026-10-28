# India provider capability matrix (research, 2026-10-27)

Legend: **Y** = confirmed on an official doc page I read in a browser. **Y\*** = listed by a third party (ClickPost, Openleaf, Base, EasyEcom) only. **?** = not found. **N** = docs checked, absent.
Second pass: Delhivery, Shiprocket, Blue Dart and NimbusPost were read in the browser (sidebar trees, endpoint pages, raw doc source). Columns for DTDC, Xpressbees, Ekart, iThink, ClickPost and Shipway are unchanged from the first pass.

## Tier 1: direct carriers

| Capability | Delhivery | Blue Dart | DTDC | Xpressbees | Ekart |
|---|---|---|---|---|---|
| Official docs | delhivery-express-api-doc.readme.io (public) + ucp.delhivery.com/developer-portal (login) | developer.dhl.com, Blue Dart APIs (India region) | none public found | none public found | none public found |
| Prod base URL | Y: `https://track.delhivery.com` | Y: `https://apigateway.bluedart.com/in/transportation/<api>/v1/` (waybill example paths also show `apigateway.bluedart.com/waybill/...`; verify) | ? | ? | ? |
| Sandbox | Y: `https://staging-express.delhivery.com` (same paths as prod) | ?: changelog says a sandbox URL was added; none printed on the page | ? | ? | ? |
| Auth | Y (Delhivery MCP docs): static `Authorization: Token <token>`, no expiry, separate token per environment; Bulk Waybill takes `token` as a query param | Y: consumer key/secret -> Authenticator API -> JWT, sent as `JWTToken` header; body also carries `Profile` (`LoginID`, `LicenceKey`, `Api_type`); app approval needed | Y\*: API key + client number + secret/token | Y\*: username/password -> token | Y\*: merchant code + token (+ location code) |
| Rate limit | Y: per IP per 5 min: 750 default (tracking), 50 rates, 4500 serviceability, 4000 pickup, 12,200 cancel, 20,000 create; 403 (429 on create) when exceeded, pause ~30s | ? | ? | ? | ? |
| Serviceability | Y: `GET /c/api/pin-codes/json/` (prepaid/COD flags) | Y: Location Finder (by pincode, product, sub-product) + Master Download (pincode master) | ? | ? | ? |
| Rate / cost | Y: Calculate Shipping Cost + Invoice Shipping Charge APIs | N: Transit Time Finder gives delivery date, not price | ? | ? | ? |
| Book | Y: `POST /api/cmu/create.json` (forward and reverse via `package_type`); Fetch Waybill, Bulk Waybill (`/waybill/api/{fetch,bulk}/json/`) | Y: Generate Waybill, Import Data (multi), Update E-Waybill | Y\* | Y\* | Y\* |
| Label | Y: Generate Shipping Label, Packing Slip | ? (`PDFOutputNotRequired` flag in Waybill request) | Y\* | ? | Y\* |
| Pickup | Y: `POST /fm/request/new/` (time, date, warehouse, qty -> `pickup_id`) | Y: Registration for Pickup (returns token no.) + Pickup Cancellation (needs token no. + registration date) | Y\* | ? | ? |
| Cancel | Y: `POST /api/p/edit` with `"cancellation": "true"` (statuses Manifested, In Transit, Pending, Open, Scheduled) | Y: Cancel Waybill, before in-scan | Y\* | Y\* | Y\* |
| Edit order | Y: Edit Order API | partial: Update E-Waybill only | ? | ? | ? |
| NDR | Y: async `POST /api/p/update` (max 1000 per call); current portal docs list only RE-ATTEMPT and PICKUP_RESCHEDULE (the older readme.io mirror also showed DEFER_DLV and EDIT_DETAILS, now treated as unsupported); returns `request_id` (UPL id); `GET /api/cmu/get_bulk_upl/{id}?verbose=true` gives `status` Success/Failure plus `success_wbns` / `failed_wbns` (partial success possible) | N: not in the India API catalog | Y\* | Y\* | Y\* |
| Returns | Y: reverse pickups via Order Creation (`package_type` = Pickup); Reverse Pickups page documents the status flow | N: no returns API in catalog (waybill has a `Returnadds` RTO address block) | ? | Y\* | Y\* |
| Webhooks | Y: "Tracking via PUSH API" (client supplies endpoint + auth header; Delhivery sends a test scan; needs a live waybill) | N: none in catalog | Y\* via aggregator | Y\* | ? |
| Tracking | Y: `GET /api/v1/packages/` | Y: Shipment Tracking (Shipment Detail, Shipment Status) | Y\* | Y\* | Y\* |
| Other | Client Warehouse create/edit, Shipping charge | Transit Time Finder, Product/Sub-product master | ? | AWB series API, EDD | EDD |
| Already in libshipkore | yes | yes | yes (HTML scrape) | no | yes |

Notes: Delhivery is the most complete direct API, covers every stage, and has a public staging host. Blue Dart covers booking, pickup, serviceability, transit time and tracking, but has no NDR, returns or webhooks in its published catalog.

## Tier 2: aggregators / orchestrators

| Capability | Shiprocket | iThink Logistics | NimbusPost | ClickPost | Shipway |
|---|---|---|---|---|---|
| Official docs | apidocs.shiprocket.in (Postman-hosted, public) | docs.ithinklogistics.com | documenter.getpostman.com/view/SWE6beC7 (public) | docs.clickpost.ai | none public found |
| Base URL | Y: `https://apiv2.shiprocket.in/v1/external/`; serviceability for blocked pincodes on `serviceability.shiprocket.in` | Y: staging `pre-alpha.ithinklogistics.com/api_v2/`; prod host not shown | ?: not printed on the intro or endpoint list I could read | ? | ? |
| Sandbox | N: docs say valid credentials "affect the real-time data in your Shiprocket account" | Y: staging | ? | ? | ? |
| Auth | Y: API user (Settings > API) -> `POST /auth/login` (email+password) -> JWT Bearer, valid 10 days; `POST /auth/logout` exists; API user can be scoped by module and buyer-detail access | Y: `access_token` + `secret_key` in JSON body | Y: `NP-API-KEY` header (Settings > API > Generate API Key) | ? | ? |
| Rate limit | Y?: HTTP 429 is documented; no number given | ? | Y: 10 req/s | ? | ? |
| Serviceability / rates | Y: `GET /courier/serviceability/` (rates, ETD, ids; `is_return` flag) | Y: Check Pincode | partial: List All Couriers only | ? | ? |
| Book | Y: `POST /orders/create/adhoc`, then assign AWB | Y: Sync Order (max 25/request) | Y: Create Custom Order, Create Autoship Order, Ship an Order, Create New Shipment | Y: Order Creation v3.1 | ? |
| Label / manifest / invoice | Y: Labels, Manifests, Invoice folder | Y | Y: Generate Shipping Label | ? | ? |
| Pickup | Y: `POST /courier/generate/pickup` (one shipment_id per call; future dates via `pickup_date`) | ? | Y: Pickup Request | ? | ? |
| Cancel | Y: `POST /orders/cancel/shipment/awbs` (up to 2000 AWBs, before "Out for Pickup"; async) | Y?: `order/cancel.json` in a sample only | Y: Cancel Order, Cancel Shipment | ? | ? |
| NDR | Y: Get All NDR Shipments, Get Specific NDR Shipment, Action NDR | ? | N: not in public docs | Y: NDR Action Update | ? |
| Returns / exchange | Y: Create Return Order, Create Exchange Order, Update Return Order, Get All Return Orders, Generate AWB for Return Shipment | ? | N | Y: Return Webhooks | ? |
| Webhooks | Y: tracking push set in panel (Settings > API > Webhooks), POST JSON, optional `x-api-key` token, URL must return 200 and must not contain "shiprocket", "kartrocket", "sr" or "kr" | ? | N | Y | ? |
| Tracking | Y: by AWB + tracking folder | Y | Y: by shipment and by AWB | Y | ? |
| Cross-border | Y: International folder (KYC, bank details, create/update order, serviceability, AWB, manifest, pickup) | ? | ? | ? | ? |
| Extras | Warehouse/pickup addresses, Sense RTO-score + address APIs, official MCP server (`bfrs/shiprocket-mcp`) | Warehouse, state/city lookups | Warehouse create/list | ? | ? |
| Already in libshipkore | no (Pickrr tracker only) | no | no | no | no |

## Also checked

- **Amazon Shipping** (developer-docs.shipping.amazon.com): Shipping API v2 with rates, purchase shipment, one-click shipment, tracking, documents, cancel, access points, NDR feedback (India only). Dynamic sandbox; default 5 req/s, burst 15. India marketplace coverage not confirmed.
- **Not found at all**: Shadowfax, India Post, Ecom Express (likely merged into Delhivery), Shyplite, Shipway API.

## Findings that affect design

1. **Cancel is not uniform.** Delhivery cancels through the edit endpoint with a flag, Blue Dart has separate waybill and pickup cancels, Shiprocket cancels by AWB in bulk and asynchronously. The cancel interface should return an "accepted/pending" state, not just success.
2. **NDR is async at Delhivery** (UPL id plus a status poll). Model NDR actions as a request with a pollable result.
3. **Shiprocket has no sandbox**, and its token expires after 10 days. Tests must use recorded fixtures, and auth needs refresh handling.
4. **Webhook styles differ**: Delhivery pushes to a client endpoint it configures by arrangement, Shiprocket via a panel setting. Webhook handling should be a normaliser from provider payload to the existing `Track`/`Checkpoint` models, not a registration API.
5. **Blue Dart gives no rates**, only transit time. The rate model needs optional price.
6. **Auth shapes vary**: JWT exchange (Blue Dart, Shiprocket), static header key (NimbusPost), secrets in body (iThink), query token (Delhivery bulk waybill). `BaseService._auth` must stay provider-specific.

## Implementation status (2026-10-28)

- **Delhivery**: `libshipkore/book/carriers/delhivery.py`, written against the specs from Delhivery's developer-portal MCP (`https://mcp-client-integration.delhivery.com/mcp`, configured in `.mcp.json`). Serviceability, rates, create (forward/reverse), cancel, pickup, NDR action and status. Not yet run against staging. Not done: labels, tracking webhook, edit order.
- **Shiprocket**: `libshipkore/book/carriers/shiprocket.py`. Login with cached token and one re-login on 401, serviceability and rates, create order + AWB assignment, cancel (async), pickup. The serviceability and AWB-assignment response shapes are reconstructed, not documented publicly. NDR, returns and tracking are not implemented (endpoints known, request bodies not read). No sandbox exists.
- Lesson from the second carrier: serviceability needs an origin as well as a destination, and pickups are per shipment (Shiprocket) or per warehouse (Delhivery), so the shared models carry both forms.

## Remaining unverified

- Delhivery: everything above is from docs, not a live call.
- Blue Dart: sandbox URL, rate limits, whether `apigateway.bluedart.com/waybill/...` or `/in/transportation/waybill/v1/` is the live path.
- NimbusPost: base URL and endpoint payloads (endpoint pages load lazily and did not render for me).
- Shiprocket: numeric rate limit; NDR and return request payloads (endpoints are confirmed, bodies not read).
- DTDC, Xpressbees, Ekart, iThink pickup/NDR/webhooks, ClickPost auth, Shipway: need provider-supplied docs.

## Third pass: what was readable, and what is built

- **iThink v3 tracking** (docs.ithinklogistics.com/doc-track-order/3, public): `POST https://api.ithinklogistics.com/api_v3/order/track.json`, staging `https://pre-alpha.ithinklogistics.com/api_v3/...`, secrets in the body, up to 10 AWBs, full response and status table shown. Built (`book/carriers/ithink.py`, tracking only). The earlier note above says `api_v2` for staging; the v3 page shows `api_v3`. Order, rate, pincode and NDR v3 pages were not readable without an account.
- **Shiprocket tracking**: `GET /courier/track/awb/{awb}`, path taken from Shiprocket's own MCP server source (github.com/bfrs/shiprocket-mcp). The response shape is not in the public page (Postman-rendered, sections not readable), so the parser is marked unverified. The scan fields match the documented webhook. NDR and returns: no request body seen; not built.
- **Blue Dart** (developer.dhl.com): request bodies for Generate Waybill, Register Pickup and Cancel Pickup are readable (JWT in a `JWTToken` header, `Profile` / `profile` with `Api_type`, `LicenceKey`, `LoginID`, dates as `/Date(ms)/`). Not readable: the Authenticator endpoint, every response shape, the sandbox URL, and which waybill path is live (`/in/transportation/waybill/v1/` vs `/waybill/GenerateWayBill`). Tracking is `GET .../tracking/v1` with query parameters and `format=xml`. Not built: writing it would mean guessing auth and every response.

