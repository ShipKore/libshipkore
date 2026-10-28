---
description: 'Book a shipment end to end with a courier, then get its label and schedule pickup. Use only when the user asks to ship, book or create an order.'
when_to_use: 'Examples: "Ship this order with Delhivery", "book a Shiprocket pickup for ORD-12", "create a shipment to Bengaluru".'
argument-hint: "[order details]"
disable-model-invocation: true
---

# Ship an order

This books a real shipment and can cost money. Follow the steps in order, never skip the approval step, and never invent order data.

$ARGUMENTS

## 1. Gather what is needed (ask for anything missing)

- **Courier** (or compare them in step 3), and a unique **order id**.
- **Consignee**: name, phone, address, pincode; also city, state and **email** (Shiprocket requires all three).
- **Pickup location**: the registered warehouse name, spelled exactly as the courier has it. Delhivery treats case and spaces as significant.
- **What is in it**: catalog `items` by sku and quantity, or an explicit `parcel` (weight in kg; Shiprocket also needs length, breadth and height in cm).
- **Payment**: Prepaid, or COD with the `cod_amount` to collect.

Never make up an address, phone number, email or warehouse name. If something is unclear, ask.

## 2. Check the setup

Call `list_providers`. The chosen provider must support `create_shipment` and be `configured`; if it is not, stop and point to the `setup-libshipkore` skill. Credentials belong in the server's config file: never ask the user to type a key into the chat.

For items by sku, `get_product` each one. If a product is missing, offer `save_product`.

## 3. Check it can be delivered and priced

1. `check_serviceability` for the destination pincode (pass `origin_pincode` too; Shiprocket needs it). Embargoed or non-serviceable: stop and say so.
2. `get_rates` with the origin, destination, weight and payment mode. Delhivery gives an estimate; Shiprocket returns one quote per courier. If the user has not chosen a courier, present the options and let them choose. For a specific Shiprocket courier, pass its id as the `courier_id` entry in `provider_options`.

## 4. Preview, then wait for approval

Call `create_order` **without** `confirmation_token`. It books nothing and returns a preview.

Show the user the preview in full: the headline, the summary (consignee, items, value, weight, mode) and every warning. The warnings matter: live mode, cash on delivery, an earlier failed attempt.

**Stop and wait for the user to say yes.** Do not treat silence, an earlier instruction, or your own judgement as approval. If they want a change, make a new preview with the changed arguments.

## 5. Confirm

After explicit approval, call `create_order` again with **exactly the same arguments** plus the `confirmation_token`. A changed argument is refused. The token works once and expires in about ten minutes; if it has expired, preview again and ask again. The client may also ask the user directly; that is expected.

On success you get the order with its `waybill`. A booking that failed is stored as `Failed` with the reason and can be retried under the same order id. If you get "already Booked", use `get_order` rather than booking again.

## 6. After booking, offer (do not assume)

- **Label**: `get_label`; `size` is `A4` or `4R` for label printers. The link may expire, so give it promptly.
- **Pickup**: `schedule_pickup` is two-step too: preview, approval, confirm. Delhivery needs `pickup_time` and books per warehouse (one request covers every waybill waiting there, one active per day). Shiprocket books per shipment.
- Report the waybill and how to track it (`track_order`).

## Provider notes

- **Delhivery**: order ids must be under 50 characters and avoid `& % # ; \`. The account needs wallet balance to book.
- **Shiprocket**: there is no sandbox, so everything acts on the live account.
- The mode in the preview says `live` or `sandbox`. Say which one it is.

## When something fails

Read the error: it says what to change. For a rejection from the courier, `get_recorded_responses` for the order shows the raw reply. Do not retry in a loop, and do not edit arguments to make an error go away without telling the user.
