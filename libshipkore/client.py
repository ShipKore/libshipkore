"""
The simple way in: one client for tracking, orders, labels, products and
service types, on top of any provider, with storage behind it.

    shipkore = Shipkore(
        providers={"delhivery": {"credentials": {"api_token": "..."}}},
        storage="sqlite:///shipkore.db",
        files="s3://my-labels/prefix",
    )
    shipkore.save_product(Product(sku="TEE", name="T-shirt", price=499, weight_kg=0.3))
    order = shipkore.create_order("delhivery", "ORD-1", consignee, "Main WH",
                                  items=[{"sku": "TEE", "quantity": 2}])
    shipkore.label("ORD-1")        # PDF copied to the file store
    shipkore.track_order("ORD-1")
"""
import contextlib
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

import requests

from libshipkore.book.models import (
    Label,
    NdrRequest,
    Order,
    OrderItem,
    OrderStatus,
    Parcel,
    PaymentMode,
    PickupRequest,
    Product,
    RequestStatus,
    ShipmentRequest,
)
from libshipkore.common.serialization import to_jsonable
from libshipkore.common.exceptions import (
    DuplicateOrder,
    NotFound,
    ProviderError,
    StorageError,
)
from libshipkore.files import create_file_store
from libshipkore.provider import get_provider
from libshipkore.storage import create_storage
from libshipkore.track.models.model import Track

DELIVERED = ("Delivered", "ReverseDelivered")
MAX_RECORDED_BODY = 100_000


_dump = to_jsonable


class Shipkore:
    """
    providers: {"delhivery": {"credentials": {...}, "sandbox": True}}.
        A provider that is not listed still works for tracking.
    storage: anything create_storage accepts (URL, dict, Storage instance).
    files: anything create_file_store accepts. Without it labels are not
        copied and only the provider's own, possibly expiring, link is kept.
    track_ttl: seconds a stored tracking result is served before the
        provider is asked again. Delivered shipments are never re-fetched.
    record_responses: keep every raw provider API response in the
        "responses" collection as an audit trail.
    """

    def __init__(self, providers=None, storage=None, files=None, sandbox=False,
                 track_ttl=300, label_url_expiry=3600, record_responses=True,
                 session=None):
        self.providers = providers or {}
        self.storage = create_storage(storage)
        self.files = create_file_store(files)
        self.sandbox = sandbox
        self.track_ttl = track_ttl
        self.label_url_expiry = label_url_expiry
        self.record_responses = record_responses
        self.session = session or requests.Session()
        self._carriers = {}
        self._context = ContextVar("shipkore_context", default=None)

    @classmethod
    def from_config(cls, config):
        return cls(**config)

    def close(self):
        self.storage.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # providers -----------------------------------------------------------

    def provider(self, slug):
        """The provider object for slug, built once from the configuration."""
        carrier = self._carriers.get(slug)
        if carrier is None:
            config = self.providers.get(slug, {})
            carrier = get_provider(
                slug,
                credentials=config.get("credentials"),
                sandbox=config.get("sandbox", self.sandbox),
            )
            carrier.session = self.session
            if self.record_responses:
                carrier.recorder = self._record_response
            self._carriers[slug] = carrier
        return carrier

    @contextlib.contextmanager
    def _operation(self, name, order_id=None):
        token = self._context.set({"operation": name, "order_id": order_id})
        try:
            yield
        finally:
            self._context.reset(token)

    def _record_response(self, provider, method, path, status_code, body):
        context = self._context.get() or {}
        record_id = uuid.uuid4().hex
        self.storage.put("responses", record_id, {
            "id": record_id,
            "provider": provider,
            "operation": context.get("operation"),
            "order_id": context.get("order_id"),
            "method": method,
            "path": path,
            "status_code": status_code,
            "body": body[:MAX_RECORDED_BODY],
            "at": self._now().isoformat(),
        })

    def responses(self, order_id=None, provider=None, limit=None):
        """Recorded raw provider responses, newest first."""
        filters = {k: v for k, v in
                   (("order_id", order_id), ("provider", provider)) if v}
        return self.storage.list("responses", filters, limit=limit)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    # stateless lookups ---------------------------------------------------

    def serviceability(self, provider, pincode, origin_pincode=None, **options):
        return self.provider(provider).serviceability(
            pincode, origin_pincode, **options
        )

    def services(self, provider):
        """Service levels (Express, Surface...) the provider offers."""
        return self.provider(provider).services()

    def rates(self, provider, origin_pincode, destination_pincode, parcel,
              payment_mode=PaymentMode.Prepaid, cod_amount=0, **options):
        return self.provider(provider).rates(
            origin_pincode, destination_pincode, parcel, payment_mode,
            cod_amount, **options
        )

    # products ------------------------------------------------------------

    def save_product(self, product):
        product = Product(**product) if isinstance(product, dict) else product
        self.storage.put("products", product.sku, _dump(product))
        return product

    def get_product(self, sku):
        document = self.storage.get("products", sku)
        if document is None:
            raise NotFound(f"no product with sku '{sku}'")
        return Product(**document)

    def list_products(self, limit=None, offset=0):
        return [Product(**d) for d in
                self.storage.list("products", limit=limit, offset=offset)]

    def delete_product(self, sku):
        return self.storage.delete("products", sku)

    # tracking ------------------------------------------------------------

    def track(self, waybill, provider, refresh=False):
        """
        Tracking from the store when it is recent enough, else from the
        provider. The latest result, with all its checkpoints, is kept.
        """
        key = f"{self.provider(provider).provider}:{waybill}"
        cached = self.storage.get("tracking", key)
        if cached and not refresh:
            age = (self._now() - datetime.fromisoformat(cached["fetched_at"])
                   ).total_seconds()
            if age < self.track_ttl or cached["track"]["status"] in DELIVERED:
                return Track(**cached["track"])
        with self._operation("track"):
            track = self.provider(provider).track(waybill)
        if track is None:
            raise NotFound(f"{provider} has no tracking data for {waybill}")
        self.storage.put("tracking", key, {
            "provider": provider,
            "waybill": waybill,
            "fetched_at": self._now().isoformat(),
            "track": _dump(track),
        })
        return track

    # orders --------------------------------------------------------------

    def _load_order(self, order_id):
        document = self.storage.get("orders", order_id)
        return Order(**document) if document else None

    def _save_order(self, order):
        order.updated_at = self._now()
        self.storage.put("orders", order.order_id, _dump(order))
        return order

    def get_order(self, order_id):
        order = self._load_order(order_id)
        if order is None:
            raise NotFound(f"no order '{order_id}'")
        return order

    def list_orders(self, provider=None, status=None, limit=None, offset=0):
        filters = {}
        if provider:
            filters["provider"] = provider
        if status:
            filters["status"] = OrderStatus(status).value
        return [Order(**d) for d in
                self.storage.list("orders", filters, limit, offset)]

    def create_order(self, provider, order_id, consignee, pickup_location,
                     items=None, parcel=None, payment_mode=PaymentMode.Prepaid,
                     cod_amount=0, declared_value=None, description=None,
                     invoice_number=None, **options):
        """
        Book an order with the provider and store it. Items refer to
        catalog products by sku; their prices, weights and names fill in
        the declared value, parcel weight and description unless given.
        Extra options go to the provider (e.g. courier_id for Shiprocket).
        A failed booking is stored with status Failed and the error, and
        can be retried under the same order id; a booked one cannot.
        """
        existing = self._load_order(order_id)
        if existing and existing.status != OrderStatus.Failed:
            raise DuplicateOrder(f"order '{order_id}' is already {existing.status.value}")
        items = [OrderItem(**i) if isinstance(i, dict) else i for i in items or []]
        products = [self.get_product(i.sku) for i in items]
        if declared_value is None:
            declared_value = sum(p.price * i.quantity for p, i in zip(products, items))
        if parcel is None:
            weight = sum(p.weight_kg * i.quantity for p, i in zip(products, items))
            if not weight:
                raise ValueError("give a parcel, or items whose products have a weight")
            parcel = Parcel(weight_kg=weight)
        if description is None and products:
            description = ", ".join(
                f"{p.name} x{i.quantity}" for p, i in zip(products, items)
            )
        carrier = self.provider(provider)
        now = self._now()
        order = Order(
            order_id=order_id,
            provider=carrier.provider,
            status=OrderStatus.Failed,
            consignee=consignee,
            pickup_location=pickup_location,
            parcel=parcel,
            payment_mode=payment_mode,
            cod_amount=cod_amount,
            declared_value=declared_value,
            items=items,
            description=description,
            invoice_number=invoice_number,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        request = ShipmentRequest(
            order_id=order_id,
            consignee=order.consignee,
            pickup_location=pickup_location,
            parcel=order.parcel,
            payment_mode=order.payment_mode,
            cod_amount=cod_amount,
            declared_value=declared_value,
            description=description,
            quantity=sum(i.quantity for i in items) or 1,
            invoice_number=invoice_number,
        )
        try:
            with self._operation("create_shipment", order_id):
                shipment = carrier.create_shipment(request, **options)
        except ProviderError as error:
            order.error = str(error)
            self._save_order(order)
            raise
        order.status = OrderStatus.Booked
        order.waybill = shipment.waybill
        order.reference = shipment.reference
        return self._save_order(order)

    def cancel_order(self, order_id):
        """
        Ask the provider to cancel. Providers that finish asynchronously
        leave the order CancelPending. A refusal is stored on the order
        and raised.
        """
        order = self.get_order(order_id)
        if order.status not in (OrderStatus.Booked, OrderStatus.CancelPending):
            raise ValueError(f"order '{order_id}' is {order.status.value}, not booked")
        with self._operation("cancel", order_id):
            result = self.provider(order.provider).cancel(order.waybill)
        if result.status == RequestStatus.Failed:
            order.error = result.message
            self._save_order(order)
            raise ProviderError(order.provider, result.message or "cancel refused")
        done = result.status in (RequestStatus.Accepted, RequestStatus.Completed)
        order.status = OrderStatus.Cancelled if done else OrderStatus.CancelPending
        order.error = None
        return self._save_order(order)

    def track_order(self, order_id, refresh=False):
        order = self.get_order(order_id)
        track = self.track(order.waybill, order.provider, refresh=refresh)
        order.delivery_status = track.status.value
        self._save_order(order)
        return track

    def schedule_pickup(self, order_id, pickup_date, pickup_time=None):
        order = self.get_order(order_id)
        request = PickupRequest(
            pickup_date=pickup_date,
            warehouse=order.pickup_location,
            pickup_time=pickup_time,
            package_count=1,
            shipment_ids=[order.reference] if order.reference else [],
        )
        with self._operation("schedule_pickup", order_id):
            order.pickup = self.provider(order.provider).schedule_pickup(request)
        self._save_order(order)
        return order.pickup

    def ndr_action(self, order_id, action, **fields):
        order = self.get_order(order_id)
        request = NdrRequest(waybill=order.waybill, action=action, **fields)
        with self._operation("ndr_action", order_id):
            result = self.provider(order.provider).ndr_action(request)
        order.ndr.append(result)
        self._save_order(order)
        return result

    def ndr_status(self, order_id):
        """Refresh the latest NDR request of the order."""
        order = self.get_order(order_id)
        if not order.ndr:
            raise NotFound(f"order '{order_id}' has no NDR request")
        with self._operation("ndr_status", order_id):
            result = self.provider(order.provider).ndr_status(
                order.ndr[-1].request_id
            )
        result.waybill = order.waybill
        order.ndr[-1] = result
        self._save_order(order)
        return result

    # labels --------------------------------------------------------------

    def label(self, order_id, size=None, refresh=False):
        """
        The label for an order. With a file store the PDF is copied there
        once and every later call returns a fresh download link for the
        stored copy. Without one, the provider's link is returned and
        reused until it expires.
        """
        order = self.get_order(order_id)
        if not order.waybill:
            raise ValueError(f"order '{order_id}' has no waybill to label")
        if not refresh:
            cached = self._cached_label(order)
            if cached:
                return cached
        with self._operation("label", order_id):
            label = self.provider(order.provider).label(
                order.waybill, order.reference, size
            )
        now = self._now()
        document = {
            "order_id": order_id,
            "provider": order.provider,
            "waybill": order.waybill,
            "content_type": label.content_type,
            "created_at": now.isoformat(),
            "storage_key": None,
            "url": None,
            "expires_at": None,
        }
        if self.files is not None:
            key = f"labels/{order.provider}/{order.waybill}.pdf"
            content = label.content or self._download(label.url)
            self.files.put(key, content, label.content_type)
            document["storage_key"] = key
            label = label.model_copy(update={
                "url": self.files.url(key, self.label_url_expiry),
                "content": None,
                "storage_key": key,
                "expires_in": self.label_url_expiry,
            })
        else:
            document["url"] = label.url
            if label.expires_in:
                expires = now.timestamp() + label.expires_in
                document["expires_at"] = expires
        self.storage.put("labels", order_id, document)
        return label

    def _cached_label(self, order):
        document = self.storage.get("labels", order.order_id)
        if not document:
            return None
        if document.get("storage_key") and self.files is not None:
            if not self.files.exists(document["storage_key"]):
                return None
            return Label(
                provider=order.provider, waybill=order.waybill,
                url=self.files.url(document["storage_key"], self.label_url_expiry),
                content_type=document["content_type"],
                storage_key=document["storage_key"],
                expires_in=self.label_url_expiry,
            )
        expires_at = document.get("expires_at")
        if document.get("url") and (
            expires_at is None or expires_at > self._now().timestamp()
        ):
            remaining = None if expires_at is None else int(
                expires_at - self._now().timestamp()
            )
            return Label(
                provider=order.provider, waybill=order.waybill,
                url=document["url"], content_type=document["content_type"],
                expires_in=remaining,
            )
        return None

    def _download(self, url):
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as error:
            raise StorageError(f"could not download the label: {error}")
        return response.content
