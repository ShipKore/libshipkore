---
description: 'Deal with failed deliveries (non-delivery reports): find affected orders, request another attempt, and check the outcome. Use when the user asks about NDR, failed or undelivered shipments, or re-attempting delivery.'
when_to_use: 'Examples: "Which shipments failed delivery", "ask Delhivery to re-attempt ORD-7", "reschedule the return pickup".'
argument-hint: "[order id]"
disable-model-invocation: true
---

# Handle a failed delivery (NDR)

Acting on an NDR changes a real shipment. Look first, ask the user, and only then act.

$ARGUMENTS

## 1. Find what needs attention

- For one order, call `track_order` with `refresh` set to true. An `AttemptFail` status or an `Exception` whose latest checkpoint talks about a failed attempt, customer unavailable, or refused delivery is an NDR.
- For many: `list_orders` for booked orders (`status` Booked), then `track_order` each. Keep the output short: order id, status, last checkpoint message.

## 2. Check the provider can act

`list_providers`: the provider must support `ndr_action`. Today that is Delhivery, and only two actions work there:

- `Reattempt`: ask for another delivery attempt.
- `PickupReschedule`: reschedule the pickup of a cancelled return shipment.

For any other provider, or another action, tell the user it must be done in the courier's own panel. Do not try other actions: the tool refuses them before anything is sent.

## 3. Ask before you act

Before requesting a reattempt, the customer usually needs to be reachable or the address fixed. Say what the failure was and ask whether the user wants a reattempt. Do not contact customers or change addresses yourself.

## 4. Preview, then wait for approval

Call `ndr_action` with `order_id` and `action`, **without** `confirmation_token`. It sends nothing and returns a preview. Show the user the headline, the summary and every warning, then **stop and wait for an explicit yes**.

Warnings to pass on for Delhivery: a reattempt only works on a Pending package at certain non-delivery codes, it works best late in the evening (after 9 PM) once dispatches are closed, and the outcome is asynchronous.

## 5. Confirm

After approval, call `ndr_action` again with exactly the same arguments plus the `confirmation_token`. The token works once and expires in about ten minutes.

## 6. Check the outcome later

The result comes back as Pending with a request id. Do not poll in a loop. Call `ndr_status` for the order once the provider has had time, and read **both** lists:

- `succeeded`: waybills it applied to.
- `failed`: a map of waybill to the reason, for example "Package in incorrect status".

A batch can partly succeed, so a `Failed` status does not mean nothing worked. If the reason says the package is in the wrong status, the shipment has moved on: run `track_order` again and tell the user.
