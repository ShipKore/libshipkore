from typing import Annotated

from mcp.server.mcpserver.exceptions import ResourceError
from mcp.types import ToolAnnotations
from pydantic import Field

from libshipkore.book.models import (
    Order,
    OrderStatus,
    Parcel,
    PaymentMode,
    Product,
    Rate,
    ServiceabilityResult,
    ServiceType,
)
from libshipkore.common.exceptions import NotFound
from libshipkore.common.models import Model
from libshipkore.provider import list_providers as provider_capabilities
from libshipkore.track.models.model import Track

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
