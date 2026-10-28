---
description: 'Find where a shipment is and explain it. Use when the user asks about a package, parcel, waybill, AWB, tracking number or order status, or whether something was delivered.'
when_to_use: 'Examples: "Where is my package", "track AWB 123", "has order ORD-5 been delivered", "why is my shipment stuck".'
---

# Track a shipment

Tracking is read-only and works for every provider without credentials.

## 1. Work out what to look up

- A **libshipkore order id** (the user booked it here): call `track_order` with `order_id`. It also records the delivery status on the order.
- A **waybill / AWB** plus a courier: call `track_shipment` with `provider` and `waybill`.
- A waybill with **no courier named**: ask which courier. Do not guess from the number's shape. If the user is unsure, call `list_providers` and offer the ones with `track`.

## 2. Read the result

- `status` is normalised across couriers: `InfoReceived`, `InTransit`, `OutForDelivery`, `AttemptFail`, `Delivered`, `AvailableForPickup`, `Exception`, `ReverseInTransit`, `ReverseOutForDelivery`, `ReverseDelivered`.
- `Exception` is also what an unrecognised courier status becomes. Read the latest checkpoint `message` and `substatus` instead of reporting "exception" alone.
- **Checkpoint order differs by courier.** Some list newest first, some oldest first. Sort by `checkpoint_time` yourself and never assume the first item is the latest. Some times are date-only.
- `estimated_date` is the courier's estimate, when it gives one.

## 3. Answer briefly

Give: current status in plain words, the latest checkpoint (what, where, when), and the estimated delivery if known. Add history only if asked.

## 4. When it looks wrong or stale

- Results are kept for about five minutes. If the user says it should have changed, call again with `refresh` set to true. Delivered shipments are never re-fetched.
- An error saying the page "may have changed" means the courier changed its site or API. Say so; do not retry in a loop. Offer to check the waybill or try another route.
- An error saying the provider could not be reached is temporary. Try once more later.
- Unknown provider: the error suggests close names. Use `list_providers` to confirm the exact slug.

## 5. Offer next steps only when relevant

- `AttemptFail` on an order booked through libshipkore: offer the `handle-ndr` skill.
- Needs a label or cancelling: those are `get_label` and the two-step `cancel_order`; do not run them without the user asking.
