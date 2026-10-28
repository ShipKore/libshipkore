from datetime import date, time
from typing import Annotated, Literal

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ResourceError
from mcp.types import ToolAnnotations
from pydantic import Field

from libshipkore.book.models import (
    Address,
    Label,
    NdrAction,
    NdrResult,
    Order,
    OrderItem,
    OrderStatus,
    Parcel,
    PaymentMode,
    Pickup,
    Product,
    Rate,
    ServiceabilityResult,
    ServiceType,
)
from libshipkore.common.exceptions import NotFound
from libshipkore.common.models import Model
from libshipkore.provider import list_providers as provider_capabilities
from libshipkore.track.models.model import Track

from .confirm import Described, Preview, two_step
from .errors import run_blocking

Provider = Annotated[str, Field(description="Provider slug, e.g. delhivery. See list_providers.")]
OrderId = Annotated[str, Field(description="The order id chosen when the order was created.")]
Pincode = Annotated[str, Field(min_length=3, max_length=12, description="Postal code.")]
Limit = Annotated[int, Field(ge=1, le=100, description="Most items to return.")]
Offset = Annotated[int, Field(ge=0, description="Items to skip, for paging.")]

# tools that only read provider or stored data
LOOKUP = ToolAnnotations(read_only_hint=True, open_world_hint=True)
STORED = ToolAnnotations(read_only_hint=True, open_world_hint=False)
# tools that read from a provider and keep the result in local storage
REFRESH = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True,
    open_world_hint=True,
)


# changes something at a provider; reached only through preview then confirm
BOOKS = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False,
    open_world_hint=True,
)
CANCELS = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True,
    open_world_hint=True,
)
# changes only the local catalog
CATALOG = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True,
    open_world_hint=False,
)

Token = Annotated[
    str | None,
    Field(description=(
        "Leave empty for a preview. To perform the action, pass the token from the "
        "preview together with exactly the same other arguments."
    )),
]

# what a provider's own rules mean for the person approving; keyed by provider
NOTES = {
    "delhivery": {
        "schedule_pickup": "Delhivery pickups are per warehouse, not per shipment: one "
                           "request covers every waybill waiting at that warehouse, and "
                           "only one can be active per warehouse per day.",
        "ndr_action": "Delhivery accepts RE-ATTEMPT only for a Pending package at certain "
                      "NSL codes and works best after 9 PM, once dispatches are closed; the "
                      "result is asynchronous, so check ndr_status afterwards.",
    },
    "shiprocket": {
        "cancel_order": "Shiprocket cancels in bulk and asynchronously: the order will show "
                        "CancelPending until it confirms.",
    },
}


class Deleted(Model):
    sku: str
    deleted: bool


class ProviderInfo(Model):
    slug: str
    operations: list[str]
    configured: bool
    sandbox: bool


class RecordedResponse(Model):
    id: str
    provider: str
    operation: str | None = None
    order_id: str | None = None
    method: str
    path: str
    status_code: int
    at: str
    body: str
    truncated: bool = False


def register_read_tools(mcp, kore):
    """Tools that never change anything at a provider."""

    @mcp.tool(title="List providers", annotations=STORED)
    async def list_providers() -> list[ProviderInfo]:
        """
        Every provider and the operations it supports (track, serviceability,
        services, rates, create_shipment, label, cancel, schedule_pickup,
        ndr_action, ndr_status). `configured` is true when the server has
        credentials for it; tracking works without them. Start here.
        """
        def build():
            return [
                ProviderInfo(
                    slug=slug,
                    operations=operations,
                    configured=slug in kore.providers,
                    sandbox=kore.providers.get(slug, {}).get("sandbox", kore.sandbox),
                )
                for slug, operations in provider_capabilities().items()
            ]
        return await run_blocking(build)

    @mcp.tool(title="Check serviceability", annotations=LOOKUP)
    async def check_serviceability(
        provider: Provider,
        pincode: Annotated[Pincode, Field(description="Destination postal code.")],
        origin_pincode: Annotated[
            Pincode | None,
            Field(description="Pickup postal code; some providers (shiprocket) need it."),
        ] = None,
    ) -> ServiceabilityResult:
        """Whether the provider delivers to a postal code. Check this before booking."""
        return await run_blocking(
            kore.serviceability, provider, pincode, origin_pincode
        )

    @mcp.tool(title="List service types", annotations=LOOKUP)
    async def list_service_types(provider: Provider) -> list[ServiceType]:
        """Service levels a provider offers, such as Express and Surface."""
        return await run_blocking(kore.services, provider)

    @mcp.tool(title="Get shipping rates", annotations=LOOKUP)
    async def get_rates(
        provider: Provider,
        origin_pincode: Pincode,
        destination_pincode: Pincode,
        weight_kg: Annotated[float, Field(gt=0, description="Parcel weight in kilograms.")],
        payment_mode: Annotated[
            PaymentMode, Field(description="Prepaid, or COD for cash on delivery.")
        ] = PaymentMode.Prepaid,
        cod_amount: Annotated[
            float, Field(ge=0, description="Cash to collect, for COD only.")
        ] = 0,
        length_cm: Annotated[
            float | None, Field(gt=0, description="Parcel length; improves volumetric pricing.")
        ] = None,
        breadth_cm: Annotated[
            float | None, Field(gt=0, description="Parcel breadth in centimetres.")
        ] = None,
        height_cm: Annotated[
            float | None, Field(gt=0, description="Parcel height in centimetres.")
        ] = None,
    ) -> list[Rate]:
        """
        Price quotes for one parcel. Amounts are estimates and can differ on
        the invoice. Aggregators return one quote per courier, cheapest first.
        """
        parcel = Parcel(
            weight_kg=weight_kg, length_cm=length_cm,
            breadth_cm=breadth_cm, height_cm=height_cm,
        )
        return await run_blocking(
            kore.rates, provider, origin_pincode, destination_pincode, parcel,
            payment_mode, cod_amount,
        )

    @mcp.tool(title="Track a shipment", annotations=LOOKUP)
    async def track_shipment(
        provider: Provider,
        waybill: Annotated[str, Field(description="Waybill / tracking number.")],
        refresh: Annotated[
            bool, Field(description="Skip the stored result and ask the provider again.")
        ] = False,
    ) -> Track:
        """
        Current status and checkpoints of any shipment, with a normalised status
        (InfoReceived, InTransit, OutForDelivery, AttemptFail, Delivered, Exception,
        ...). Works for every provider without credentials. Recent results are
        served from storage; delivered shipments are never re-fetched.
        """
        return await run_blocking(kore.track, waybill, provider, refresh, scraper=True)

    @mcp.tool(title="Track an order", annotations=REFRESH)
    async def track_order(
        order_id: OrderId,
        refresh: Annotated[bool, Field(description="Ask the provider again.")] = False,
    ) -> Track:
        """Track the shipment of a booked order and record its delivery status on the order."""
        return await run_blocking(kore.track_order, order_id, refresh, scraper=True)

    @mcp.tool(title="Get an order", annotations=STORED)
    async def get_order(order_id: OrderId) -> Order:
        """One stored order with its waybill, status, pickup and NDR history."""
        return await run_blocking(kore.get_order, order_id)

    @mcp.tool(title="List orders", annotations=STORED)
    async def list_orders(
        provider: Annotated[str | None, Field(description="Only this provider.")] = None,
        status: Annotated[OrderStatus | None, Field(description="Only this order status.")] = None,
        limit: Limit = 20,
        offset: Offset = 0,
    ) -> list[Order]:
        """Stored orders, most recently changed first."""
        return await run_blocking(kore.list_orders, provider, status, limit, offset)

    @mcp.tool(title="List products", annotations=STORED)
    async def list_products(limit: Limit = 50, offset: Offset = 0) -> list[Product]:
        """The product catalog that orders refer to by sku."""
        return await run_blocking(kore.list_products, limit, offset)

    @mcp.tool(title="Get a product", annotations=STORED)
    async def get_product(sku: Annotated[str, Field(description="Product sku.")]) -> Product:
        """One catalog product: price, weight, dimensions, HSN code."""
        return await run_blocking(kore.get_product, sku)

    @mcp.tool(title="Get recorded provider responses", annotations=STORED)
    async def get_recorded_responses(
        order_id: Annotated[str | None, Field(description="Only calls made for this order.")] = None,
        provider: Annotated[str | None, Field(description="Only this provider.")] = None,
        limit: Limit = 10,
        max_body_chars: Annotated[
            int, Field(ge=0, le=20000, description="Cut each response body to this length.")
        ] = 2000,
    ) -> list[RecordedResponse]:
        """
        The raw responses providers returned, newest first, for finding out why a
        call failed. Bodies are shortened; `truncated` says when.
        """
        def build():
            records = kore.responses(order_id=order_id, provider=provider, limit=limit)
            return [
                RecordedResponse(
                    **{**r, "body": r["body"][:max_body_chars],
                       "truncated": len(r["body"]) > max_body_chars}
                )
                for r in records
            ]
        return await run_blocking(build)


def register_write_tools(mcp, kore, pending, elicit=True):
    """Tools that save data or change something at a provider."""

    def mode(provider):
        sandbox = kore.providers.get(provider, {}).get("sandbox", kore.sandbox)
        return "sandbox" if sandbox else "live"

    def mode_warning(provider):
        if mode(provider) == "sandbox":
            return "Sandbox mode: no real shipment is affected."
        return "Live mode: this acts on the real provider account and may be charged."

    def note(provider, action):
        return NOTES.get(provider, {}).get(action)

    # -- two-step tools ------------------------------------------------------

    @mcp.tool(title="Book an order (preview, then confirm)", annotations=BOOKS)
    async def create_order(
        provider: Provider,
        order_id: Annotated[str, Field(
            description="A unique id for this order, chosen by you; reused if a booking failed.")],
        consignee: Annotated[Address, Field(description="Who the shipment is delivered to.")],
        pickup_location: Annotated[str, Field(
            description="Registered warehouse / pickup location name, exactly as the provider has it.")],
        items: Annotated[list[OrderItem] | None, Field(
            description="Catalog products by sku and quantity; fills in value, weight and description.")] = None,
        parcel: Annotated[Parcel | None, Field(
            description="Weight and size; defaults to the summed weight of the items.")] = None,
        payment_mode: Annotated[PaymentMode, Field(
            description="Prepaid, or COD for cash on delivery.")] = PaymentMode.Prepaid,
        cod_amount: Annotated[float, Field(
            ge=0, description="Cash to collect, for COD only.")] = 0,
        declared_value: Annotated[float | None, Field(
            ge=0, description="Declared goods value; defaults to the items' prices.")] = None,
        description: Annotated[str | None, Field(
            description="Goods description; defaults to the item names.")] = None,
        invoice_number: Annotated[str | None, Field(
            description="Your invoice number, if the provider wants one.")] = None,
        provider_options: Annotated[dict[str, str | int | float | bool] | None, Field(
            description="Provider-specific settings, e.g. courier_id for shiprocket.")] = None,
        confirmation_token: Token = None,
        *,
        ctx: Context,
    ) -> Preview | Order:
        """
        Book a shipment with a provider and store the order. This changes the
        real world, so it takes two calls: the first returns a preview and a
        token and books nothing; show it to the user, and after they approve call
        again with the same arguments plus the token. Run check_serviceability
        first. Returns the booked order with its waybill.
        """
        options = provider_options or {}
        arguments = {
            "provider": provider, "order_id": order_id, "consignee": consignee,
            "pickup_location": pickup_location, "items": items, "parcel": parcel,
            "payment_mode": payment_mode, "cod_amount": cod_amount,
            "declared_value": declared_value, "description": description,
            "invoice_number": invoice_number, "provider_options": options,
        }

        def call(operation):
            return operation(
                provider, order_id, consignee, pickup_location, items=items,
                parcel=parcel, payment_mode=payment_mode, cod_amount=cod_amount,
                declared_value=declared_value, description=description,
                invoice_number=invoice_number, **options,
            )

        def describe():
            order = call(kore.preview_order)
            lines = []
            for item in order.items:
                product = kore.get_product(item.sku)
                lines.append({"sku": item.sku, "name": product.name,
                              "quantity": item.quantity, "unit_price": product.price})
            warnings = [mode_warning(order.provider)]
            if order.payment_mode == PaymentMode.COD:
                warnings.append(f"Cash on delivery: the courier will collect {order.cod_amount:g}.")
                if order.cod_amount != order.declared_value:
                    warnings.append("The COD amount differs from the declared value.")
            elif order.cod_amount:
                warnings.append("cod_amount is set but the payment mode is Prepaid.")
            try:
                prior = kore.get_order(order_id)
                if prior.error:
                    warnings.append(f"An earlier attempt for this order failed: {prior.error}")
            except NotFound:
                pass
            headline = (
                f"Book order {order_id} with {order.provider} for {order.consignee.name} "
                f"({order.consignee.pincode}), declared value {order.declared_value:g}"
                + (f", cash on delivery {order.cod_amount:g}" if order.payment_mode == PaymentMode.COD else "")
                + "?"
            )
            return Described(headline, {
                "provider": order.provider, "mode": mode(order.provider),
                "order_id": order_id, "consignee": order.consignee.model_dump(),
                "pickup_location": order.pickup_location, "items": lines,
                "parcel": order.parcel.model_dump(), "payment_mode": order.payment_mode.value,
                "cod_amount": order.cod_amount, "declared_value": order.declared_value,
                "description": order.description, "provider_options": options,
            }, warnings)

        return await two_step(
            ctx, pending, action="create_order", arguments=arguments,
            token=confirmation_token, describe=describe,
            execute=lambda: call(kore.create_order), elicit=elicit,
        )

    @mcp.tool(title="Cancel an order (preview, then confirm)", annotations=CANCELS)
    async def cancel_order(
        order_id: OrderId,
        confirmation_token: Token = None,
        *,
        ctx: Context,
    ) -> Preview | Order:
        """
        Ask the provider to cancel a booked order. Two calls: a preview first,
        then the same call with the token once the user approves. Providers can
        refuse once a shipment is picked up, and some confirm later, leaving the
        order CancelPending; check get_order afterwards.
        """
        arguments = {"order_id": order_id}

        def describe():
            order = kore.preview_cancel(order_id)
            warnings = [mode_warning(order.provider),
                        "The provider may refuse if the shipment has already been picked up."]
            if order.delivery_status in ("InTransit", "OutForDelivery"):
                warnings.append(
                    f"The shipment is already moving ({order.delivery_status}); cancelling "
                    "may send it back to the sender instead of stopping it.")
            extra = note(order.provider, "cancel_order")
            if extra:
                warnings.append(extra)
            return Described(
                f"Cancel order {order_id} ({order.provider}, waybill {order.waybill})?",
                {"order_id": order_id, "provider": order.provider, "mode": mode(order.provider),
                 "waybill": order.waybill, "status": order.status.value,
                 "delivery_status": order.delivery_status},
                warnings,
            )

        return await two_step(
            ctx, pending, action="cancel_order", arguments=arguments,
            token=confirmation_token, describe=describe,
            execute=lambda: kore.cancel_order(order_id), elicit=elicit,
        )

    @mcp.tool(title="Schedule a pickup (preview, then confirm)", annotations=BOOKS)
    async def schedule_pickup(
        order_id: OrderId,
        pickup_date: Annotated[date, Field(description="Pickup date, YYYY-MM-DD.")],
        pickup_time: Annotated[time | None, Field(
            description="Pickup time, HH:MM:SS; some providers (delhivery) require it.")] = None,
        confirmation_token: Token = None,
        *,
        ctx: Context,
    ) -> Preview | Pickup:
        """
        Ask the provider to collect a booked order. Two calls: preview, then the
        same call with the token once the user approves. The provider may assign
        a different slot than requested; the result shows the slot it chose.
        """
        arguments = {"order_id": order_id, "pickup_date": pickup_date,
                     "pickup_time": pickup_time}

        def describe():
            order, request = kore.preview_pickup(order_id, pickup_date, pickup_time)
            warnings = [mode_warning(order.provider)]
            extra = note(order.provider, "schedule_pickup")
            if extra:
                warnings.append(extra)
            when = f"{pickup_date}" + (f" at {pickup_time}" if pickup_time else "")
            return Described(
                f"Schedule a pickup for order {order_id} ({order.provider}) on {when}?",
                {"order_id": order_id, "provider": order.provider, "mode": mode(order.provider),
                 "pickup_location": order.pickup_location, "pickup_date": pickup_date.isoformat(),
                 "pickup_time": pickup_time.isoformat() if pickup_time else None,
                 "waybill": order.waybill},
                warnings,
            )

        return await two_step(
            ctx, pending, action="schedule_pickup", arguments=arguments,
            token=confirmation_token, describe=describe,
            execute=lambda: kore.schedule_pickup(order_id, pickup_date, pickup_time),
            elicit=elicit,
        )

    @mcp.tool(title="Act on a failed delivery (preview, then confirm)", annotations=BOOKS)
    async def ndr_action(
        order_id: OrderId,
        action: Annotated[NdrAction, Field(
            description="Reattempt delivery, or PickupReschedule for a cancelled return pickup.")],
        confirmation_token: Token = None,
        *,
        ctx: Context,
    ) -> Preview | NdrResult:
        """
        Act on a non-delivery report (NDR), such as asking for another delivery
        attempt. Two calls: preview, then the same call with the token once the
        user approves. The provider processes it asynchronously: use ndr_status
        with the order to see the outcome.
        """
        arguments = {"order_id": order_id, "action": action}

        def describe():
            order, request = kore.preview_ndr_action(order_id, action)
            warnings = [mode_warning(order.provider)]
            extra = note(order.provider, "ndr_action")
            if extra:
                warnings.append(extra)
            return Described(
                f"Apply {action.value} to order {order_id} ({order.provider}, "
                f"waybill {order.waybill})?",
                {"order_id": order_id, "provider": order.provider, "mode": mode(order.provider),
                 "waybill": order.waybill, "action": action.value,
                 "delivery_status": order.delivery_status},
                warnings,
            )

        return await two_step(
            ctx, pending, action="ndr_action", arguments=arguments,
            token=confirmation_token, describe=describe,
            execute=lambda: kore.ndr_action(order_id, action), elicit=elicit,
        )

    # -- changes that are safe to repeat or local ----------------------------

    @mcp.tool(title="Get an order's NDR status", annotations=REFRESH)
    async def ndr_status(order_id: OrderId) -> NdrResult:
        """
        Refresh the latest NDR request of an order from the provider. Check both
        `succeeded` and `failed`: a batch can partly succeed.
        """
        return await run_blocking(kore.ndr_status, order_id)

    @mcp.tool(title="Get a shipping label", annotations=REFRESH)
    async def get_label(
        order_id: OrderId,
        size: Annotated[Literal["A4", "4R"] | None, Field(
            description="Paper size where the provider lets you choose: A4, or 4R for label printers.")] = None,
        refresh: Annotated[bool, Field(description="Fetch a new label even if one is stored.")] = False,
    ) -> Label:
        """
        A link to the PDF label of a booked order. With a file store configured
        the PDF is copied there once and the link is a fresh download link; without
        one it is the provider's own link, which can expire (`expires_in`, in
        seconds). Never returns the PDF itself.
        """
        return await run_blocking(kore.label, order_id, size, refresh)

    @mcp.tool(title="Save a product", annotations=CATALOG)
    async def save_product(
        product: Annotated[Product, Field(description="The catalog entry to save.")],
        overwrite: Annotated[bool, Field(
            description="Replace an existing product with the same sku.")] = False,
    ) -> Product:
        """Add a product to the catalog. Refuses to replace an existing sku unless overwrite is true."""
        def save():
            try:
                kore.get_product(product.sku)
            except NotFound:
                pass
            else:
                if not overwrite:
                    raise ValueError(
                        f"product '{product.sku}' already exists; pass overwrite=true to replace it")
            return kore.save_product(product)
        return await run_blocking(save)

    @mcp.tool(title="Delete a product", annotations=CATALOG)
    async def delete_product(
        sku: Annotated[str, Field(description="Product sku to remove from the catalog.")],
    ) -> Deleted:
        """Remove a product from the catalog. Orders already booked keep their own copy of its details."""
        deleted = await run_blocking(kore.delete_product, sku)
        return Deleted(sku=sku, deleted=deleted)


def register_resources(mcp, kore):
    """The same stored data as addressable, read-only resources."""

    @mcp.resource("shipkore://providers", mime_type="application/json",
                  title="Providers and their operations")
    def providers_resource() -> str:
        import json
        return json.dumps(provider_capabilities(), indent=2)

    @mcp.resource("shipkore://orders/{order_id}", mime_type="application/json",
                  title="A stored order")
    def order_resource(order_id: str) -> str:
        try:
            return kore.get_order(order_id).model_dump_json(indent=2)
        except NotFound as error:
            raise ResourceError(str(error))

    @mcp.resource("shipkore://products/{sku}", mime_type="application/json",
                  title="A catalog product")
    def product_resource(sku: str) -> str:
        try:
            return kore.get_product(sku).model_dump_json(indent=2)
        except NotFound as error:
            raise ResourceError(str(error))
