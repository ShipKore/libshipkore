import json
from datetime import date, time
from ..base import BaseCarrier, carrier_registry
from libshipkore.common.exceptions import ProviderError
from ..models import (
    Cancellation,
    Label,
    NdrAction,
    NdrResult,
    Pickup,
    PaymentMode,
    Rate,
    RequestStatus,
    ServiceabilityResult,
    ServiceType,
    Shipment,
)


@carrier_registry.register("delhivery")
class Delhivery(BaseCarrier):
    """
    Delhivery B2C express API, written against the specs served by the
    Delhivery developer-portal MCP (one.delhivery.com/developer-portal).
    Not yet exercised against staging or production.

    Tokens are static and environment specific: a staging token does not
    work on production. Rate limits are per IP, e.g. 750 requests/5 min on
    most endpoints, 50/5 min on rates; exceeding them returns 403 (or 429
    on shipment creation), so pause about 30s before retrying.
    """

    provider = "delhivery"
    base_url = "https://track.delhivery.com"
    sandbox_url = "https://staging-express.delhivery.com"

    NDR_ACTIONS = {
        NdrAction.Reattempt: "RE-ATTEMPT",
        NdrAction.PickupReschedule: "PICKUP_RESCHEDULE",
    }

    def _headers(self):
        token = self._credential("api_token")
        return {"Authorization": f"Token {token}", "Accept": "application/json"}

    def validate(self, operation, request, **options):
        if operation == "create_shipment" and options:
            raise ValueError(f"delhivery takes no provider options, got {sorted(options)}")
        if operation == "schedule_pickup" and not (
            request.warehouse and request.pickup_time and request.package_count
        ):
            raise ValueError(
                "delhivery pickups need warehouse, pickup_time and package_count"
            )
        if operation == "ndr_action" and request.action not in self.NDR_ACTIONS:
            self._unsupported(f"ndr_action {request.action.value}")

    def serviceability(self, pincode, origin_pincode=None):
        data = self._request(
            "GET", "/c/api/pin-codes/json/", params={"filter_codes": pincode}
        )
        codes = data.get("delivery_codes") or []
        if not codes:
            return ServiceabilityResult(
                provider=self.provider, pincode=pincode, serviceable=False
            )
        entry = codes[0].get("postal_code", {})
        if isinstance(entry, list):
            entry = entry[0] if entry else {}
        # a blank remark means serviceable; "Embargo" is a temporary block
        remark = entry.get("remark") or ""
        serviceable = remark == ""

        def flag(key):
            return entry[key] == "Y" if key in entry else None

        return ServiceabilityResult(
            provider=self.provider,
            pincode=pincode,
            serviceable=serviceable,
            prepaid=flag("pre_paid"),
            cod=flag("cod"),
            pickup=flag("pickup"),
            remark=remark or None,
        )

    def services(self):
        # the billing modes the charges API accepts (md = E or S)
        return [
            ServiceType(provider=self.provider, code="E", name="Express",
                        mode="Express"),
            ServiceType(provider=self.provider, code="S", name="Surface",
                        mode="Surface"),
        ]

    def rates(self, origin_pincode, destination_pincode, parcel,
              payment_mode, cod_amount=0, mode="E"):
        """
        Tentative charges, subject to change on the invoice. cod_amount is
        ignored: the API prices by payment type, not by amount. mode is
        "E" (express) or "S" (surface).
        """
        params = {
            "md": mode,
            "ss": "Delivered",
            "o_pin": int(origin_pincode),
            "d_pin": int(destination_pincode),
            "cgm": int(parcel.weight_kg * 1000),
            "pt": "COD" if payment_mode == PaymentMode.COD else "Pre-paid",
        }
        for key, value in (("l", parcel.length_cm), ("b", parcel.breadth_cm),
                           ("h", parcel.height_cm)):
            if value is not None:
                params[key] = int(value)
        data = self._request("GET", "/api/kinko/v1/invoice/charges/.json",
                             params=params)
        if isinstance(data, dict):
            data = [data]
        if not data or "total_amount" not in data[0]:
            raise ProviderError(self.provider, "no rate returned", body=data)
        return [
            Rate(provider=self.provider, amount=row["total_amount"],
                 service="Express" if mode == "E" else "Surface")
            for row in data
        ]

    def create_shipment(self, request):
        """
        A failure whose message says the package "might have been partially
        saved" may still have created it; look it up before retrying.
        """
        shipment = {
            "name": request.consignee.name,
            "add": request.consignee.address,
            "pin": request.consignee.pincode,
            "city": request.consignee.city,
            "state": request.consignee.state,
            "country": request.consignee.country,
            "phone": request.consignee.phone,
            "order": request.order_id,
            "payment_mode": "Pickup" if request.is_reverse
            else request.payment_mode.value,
            "cod_amount": request.cod_amount,
            "total_amount": request.declared_value,
            "products_desc": request.description,
            "quantity": str(request.quantity),
            "weight": request.parcel.weight_kg * 1000,
            "shipment_length": request.parcel.length_cm,
            "shipment_width": request.parcel.breadth_cm,
            "shipment_height": request.parcel.height_cm,
            "waybill": request.waybill,
            "seller_inv": request.invoice_number,
            "ewbn": request.e_waybill,
        }
        payload = {
            "shipments": [{k: v for k, v in shipment.items() if v is not None}],
            "pickup_location": {"name": request.pickup_location},
        }
        data = self._request(
            "POST",
            "/api/cmu/create.json",
            data={"format": "json", "data": json.dumps(payload)},
        )
        packages = data.get("packages") or []
        package = packages[0] if packages else {}
        remarks = [r for r in package.get("remarks") or [] if r]
        if not data.get("success") or package.get("status") != "Success":
            reason = "; ".join(remarks) or data.get("rmk") \
                or "shipment not created"
            raise ProviderError(self.provider, reason, body=data)
        return Shipment(
            provider=self.provider,
            waybill=package["waybill"],
            order_id=request.order_id,
            status=package["status"],
            remarks=remarks,
        )

    def label(self, waybill, reference=None, size=None):
        """
        A signed PDF link from the packing-slip API. It lapses after 24
        hours, so download it or ask again. size is "A4" (the default) or
        "4R" for label printers.
        """
        if size not in (None, "A4", "4R"):
            raise ValueError("delhivery label size must be 'A4' or '4R'")
        params = {"wbns": waybill, "pdf": "true"}
        if size:
            params["pdf_size"] = size
        data = self._request("GET", "/api/p/packing_slip", params=params)
        packages = data.get("packages") or []
        link = packages[0].get("pdf_download_link") if packages else None
        if not link:
            raise ProviderError(
                self.provider, f"no label for {waybill}", body=data
            )
        return Label(
            provider=self.provider, waybill=waybill, url=link, expires_in=86400
        )

    def cancel(self, waybill):
        """
        Only Manifested, In Transit and Pending shipments (Scheduled for
        reverse pickups) can be cancelled. An in-transit shipment is
        rerouted to origin, not removed.
        """
        data = self._request(
            "POST",
            "/api/p/edit",
            json={"waybill": waybill, "cancellation": "true"},
        )
        accepted = bool(data.get("status"))
        return Cancellation(
            provider=self.provider,
            waybill=waybill,
            status=RequestStatus.Accepted if accepted else RequestStatus.Failed,
            message=data.get("remark") or data.get("error"),
        )

    def schedule_pickup(self, request):
        """
        Pickups are per warehouse, not per waybill, and one request per
        warehouse per day can be active at a time.
        """
        self.validate("schedule_pickup", request)
        data = self._request(
            "POST",
            "/fm/request/new/",
            json={
                "pickup_location": request.warehouse,
                "pickup_date": request.pickup_date.isoformat(),
                "pickup_time": request.pickup_time.isoformat(),
                "expected_package_count": request.package_count,
            },
        )
        if "pickup_id" not in data:
            raise ProviderError(self.provider, "no pickup_id", body=data)
        return Pickup(
            provider=self.provider,
            pickup_id=str(data["pickup_id"]),
            warehouse=request.warehouse,
            pickup_date=date.fromisoformat(
                data.get("pickup_date") or request.pickup_date.isoformat()
            ),
            pickup_time=time.fromisoformat(
                data.get("pickup_time") or request.pickup_time.isoformat()
            ),
            package_count=data.get(
                "expected_package_count", request.package_count
            ),
            center=data.get("incoming_center_name"),
        )

    def ndr_action(self, request):
        """
        Asynchronous: the result carries a request id to poll with
        ndr_status. RE-ATTEMPT needs a Pending package at one of a few
        NSL codes and works best after 9 PM once dispatches are closed.
        """
        self.validate("ndr_action", request)
        act = self.NDR_ACTIONS[request.action]
        data = self._request(
            "POST",
            "/api/p/update",
            json={"data": [{"waybill": request.waybill, "act": act}]},
        )
        if not data.get("request_id"):
            raise ProviderError(self.provider, "no NDR request id", body=data)
        return NdrResult(
            provider=self.provider,
            waybill=request.waybill,
            request_id=str(data["request_id"]),
            status=RequestStatus.Pending,
            message=data.get("message"),
        )

    def ndr_status(self, request_id):
        data = self._request(
            "GET",
            f"/api/cmu/get_bulk_upl/{request_id}",
            params={"verbose": "true"},
        )
        outcome = str(data.get("status", "")).lower()
        if outcome == "success":
            status = RequestStatus.Completed
        elif outcome == "failure":
            status = RequestStatus.Failed
        else:
            status = RequestStatus.Pending
        return NdrResult(
            provider=self.provider,
            waybill=None,
            request_id=str(request_id),
            status=status,
            message=data.get("remark"),
            succeeded=[w["waybill"] for w in data.get("success_wbns") or []],
            failed={
                w["waybill"]: w.get("message", "")
                for w in data.get("failed_wbns") or []
            },
        )
