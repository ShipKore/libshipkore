from datetime import datetime
from ..base import BaseCarrier, carrier_registry
from libshipkore.common.exceptions import ProviderError
from ..models import (
    Cancellation,
    Label,
    PaymentMode,
    Pickup,
    Rate,
    RequestStatus,
    ServiceabilityResult,
    Shipment,
)


@carrier_registry.register("shiprocket")
class Shiprocket(BaseCarrier):
    """
    Shiprocket aggregator API (apidocs.shiprocket.in). Auth, create order,
    pickup and cancel follow the published docs. The response shapes of
    serviceability and AWB assignment are not in the public docs I could
    read and are marked "unverified". NDR, returns and tracking are not
    implemented yet.

    Credentials: email and password of an API user (Settings > API), plus
    optionally pickup_pincode as the default origin for serviceability.
    There is no sandbox: valid credentials act on the live account.
    """

    provider = "shiprocket"
    base_url = "https://apiv2.shiprocket.in/v1/external"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # a token is valid for 10 days; one can be supplied to skip login
        self._token = self.credentials.get("token")

    def _login(self):
        response = self.session.post(
            self.root + "/auth/login",
            json={
                "email": self._credential("email"),
                "password": self._credential("password"),
            },
            timeout=self.timeout,
        )
        try:
            token = response.json().get("token") if response.ok else None
        except ValueError:
            token = None
        if not token:
            raise ProviderError(
                self.provider,
                "login failed",
                status_code=response.status_code,
                body=response.text,
            )
        self._token = token

    def _headers(self):
        if not self._token:
            self._login()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _request(self, method, path, **kwargs):
        try:
            return super()._request(method, path, **kwargs)
        except ProviderError as error:
            if error.status_code != 401:
                raise
        # the token expired or was revoked: log in once more and retry
        self._token = None
        return super()._request(method, path, **kwargs)

    def validate(self, operation, request, **options):
        if operation == "create_shipment":
            unknown = sorted(set(options) - {"courier_id"})
            if unknown:
                raise ValueError(
                    f"shiprocket accepts only the provider option courier_id, got {unknown}"
                )
            consignee = request.consignee
            missing = [
                name for name, value in (
                    ("consignee.email", consignee.email),
                    ("consignee.city", consignee.city),
                    ("consignee.state", consignee.state),
                    ("parcel.length_cm", request.parcel.length_cm),
                    ("parcel.breadth_cm", request.parcel.breadth_cm),
                    ("parcel.height_cm", request.parcel.height_cm),
                ) if value is None
            ]
            if missing:
                raise ValueError(f"shiprocket requires {', '.join(missing)}")
        if operation == "schedule_pickup" and len(request.shipment_ids) != 1:
            raise ValueError("shiprocket schedules one shipment per pickup")

    def _couriers(self, origin, destination, weight_kg, cod):
        # unverified: response shape of the serviceability endpoint
        data = self._request(
            "GET",
            "/courier/serviceability/",
            params={
                "pickup_postcode": origin,
                "delivery_postcode": destination,
                "weight": weight_kg,
                "cod": 1 if cod else 0,
                "is_return": 0,
            },
        )
        return (data.get("data") or {}).get("available_courier_companies") or []

    def _origin(self, origin_pincode):
        origin = origin_pincode or self.credentials.get("pickup_pincode")
        if not origin:
            raise ValueError(
                "shiprocket needs origin_pincode or a pickup_pincode credential"
            )
        return origin

    def serviceability(self, pincode, origin_pincode=None, weight_kg=0.5,
                       cod=False):
        couriers = self._couriers(
            self._origin(origin_pincode), pincode, weight_kg, cod
        )
        return ServiceabilityResult(
            provider=self.provider,
            pincode=pincode,
            serviceable=bool(couriers),
        )

    def rates(self, origin_pincode, destination_pincode, parcel,
              payment_mode, cod_amount=0):
        """One Rate per available courier, cheapest first."""
        couriers = self._couriers(
            origin_pincode,
            destination_pincode,
            parcel.weight_kg,
            payment_mode == PaymentMode.COD,
        )
        rates = []
        for courier in couriers:
            days = str(courier.get("estimated_delivery_days") or "")
            rates.append(Rate(
                provider=self.provider,
                amount=courier["rate"],
                service=courier.get("courier_name"),
                estimated_days=int(days) if days.isdigit() else None,
            ))
        return sorted(rates, key=lambda r: r.amount)

    def create_shipment(self, request, courier_id=None):
        """
        Creates the order, then assigns an AWB. Without courier_id
        Shiprocket picks the courier. The returned reference is the
        Shiprocket shipment id that schedule_pickup needs.
        """
        self.validate("create_shipment", request)
        consignee = request.consignee
        total = request.declared_value
        order = {
            "order_id": request.order_id,
            "order_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "pickup_location": request.pickup_location,
            "billing_customer_name": consignee.name,
            "billing_address": consignee.address,
            "billing_city": consignee.city,
            "billing_pincode": consignee.pincode,
            "billing_state": consignee.state,
            "billing_country": consignee.country,
            "billing_email": consignee.email,
            "billing_phone": consignee.phone,
            "shipping_is_billing": True,
            "order_items": [{
                "name": request.description or "Item",
                "sku": request.order_id,
                "units": request.quantity,
                "selling_price": total / request.quantity,
            }],
            "payment_method": request.payment_mode.value,
            "sub_total": total,
            "length": request.parcel.length_cm,
            "breadth": request.parcel.breadth_cm,
            "height": request.parcel.height_cm,
            "weight": request.parcel.weight_kg,
        }
        if request.invoice_number:
            order["invoice_number"] = request.invoice_number
        created = self._request("POST", "/orders/create/adhoc", json=order)
        shipment_id = created.get("shipment_id")
        if not shipment_id:
            raise ProviderError(
                self.provider,
                created.get("message") or "order not created",
                body=created,
            )
        body = {"shipment_id": shipment_id}
        if courier_id:
            body["courier_id"] = courier_id
        assigned = self._request("POST", "/courier/assign/awb", json=body)
        # unverified: response shape of AWB assignment
        awb = (((assigned.get("response") or {}).get("data") or {})
               .get("awb_code"))
        if not awb:
            raise ProviderError(
                self.provider,
                "order created but no AWB assigned (shipment "
                f"{shipment_id}); retry the assignment",
                body=assigned,
            )
        return Shipment(
            provider=self.provider,
            waybill=str(awb),
            order_id=request.order_id,
            status=created.get("status") or "NEW",
            reference=str(shipment_id),
        )

    def label(self, waybill, reference=None, size=None):
        """
        Needs the Shiprocket shipment id as reference (Shipment.reference).
        Label size is an account setting, so size is ignored.
        """
        if not reference:
            raise ValueError("shiprocket labels need the shipment reference")
        data = self._request(
            "POST",
            "/courier/generate/label",
            json={"shipment_id": [int(reference)]},
        )
        # unverified: the response field name
        url = data.get("label_url")
        if not url:
            raise ProviderError(
                self.provider, f"no label for {waybill}", body=data
            )
        return Label(provider=self.provider, waybill=waybill, url=url)

    def cancel(self, waybill):
        """Bulk and asynchronous: only accepted, not yet done."""
        data = self._request(
            "POST",
            "/orders/cancel/shipment/awbs",
            json={"awbs": [waybill]},
        )
        return Cancellation(
            provider=self.provider,
            waybill=waybill,
            status=RequestStatus.Pending,
            message=data.get("message"),
        )

    def schedule_pickup(self, request):
        """Pickups are per shipment, one shipment id at a time."""
        self.validate("schedule_pickup", request)
        shipment_id = request.shipment_ids[0]
        body = {
            "shipment_id": [int(shipment_id)],
            "pickup_date": [request.pickup_date.isoformat()],
        }
        data = self._request("POST", "/courier/generate/pickup", json=body)
        info = data.get("response") or {}
        if data.get("pickup_status") != 1 or not info:
            raise ProviderError(
                self.provider,
                info.get("data") or data.get("message") or "pickup not booked",
                body=data,
            )
        scheduled = datetime.strptime(
            info["pickup_scheduled_date"], "%Y-%m-%d %H:%M:%S"
        )
        return Pickup(
            provider=self.provider,
            pickup_id=str(info.get("pickup_token_number") or shipment_id),
            warehouse=None,
            pickup_date=scheduled.date(),
            pickup_time=scheduled.time(),
            package_count=1,
        )
