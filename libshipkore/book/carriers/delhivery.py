import json
from ..base import BaseCarrier, carrier_registry
from libshipkore.common.exceptions import ProviderError
from ..models import (
    Cancellation,
    NdrAction,
    NdrResult,
    Pickup,
    PaymentMode,
    Rate,
    RequestStatus,
    ServiceabilityResult,
    Shipment,
)


@carrier_registry.register("delhivery")
class Delhivery(BaseCarrier):
    """
    Delhivery express API. Paths and the staging host come from
    delhivery-express-api-doc.readme.io. The auth header format and the
    response field names marked "unverified" are not stated in the public
    docs and must be checked against staging with real credentials.
    """

    provider = "delhivery"
    base_url = "https://track.delhivery.com"
    sandbox_url = "https://staging-express.delhivery.com"

    NDR_ACTIONS = {
        NdrAction.Reattempt: "RE-ATTEMPT",
        NdrAction.Defer: "DEFER_DLV",
        NdrAction.EditDetails: "EDIT_DETAILS",
    }

    def _headers(self):
        # unverified: documented only inside the logged-in developer portal
        token = self._credential("api_token")
        return {"Authorization": f"Token {token}", "Accept": "application/json"}

    def serviceability(self, pincode):
        data = self._request(
            "GET", "/c/api/pin-codes/json/", params={"filter_codes": pincode}
        )
        codes = data.get("delivery_codes") or []
        if not codes:
            return ServiceabilityResult(
                provider=self.provider, pincode=pincode, serviceable=False
            )
        entry = codes[0].get("postal_code", {})
        prepaid = entry.get("pre_paid") == "Y"
        cod = entry.get("cod") == "Y"
        return ServiceabilityResult(
            provider=self.provider,
            pincode=pincode,
            serviceable=prepaid or cod,
            prepaid=prepaid,
            cod=cod,
            pickup=entry.get("pickup") == "Y",
        )

    def rates(self, origin_pincode, destination_pincode, parcel,
              payment_mode, cod_amount=0):
        # unverified: path and response shape of "Calculate Shipping Cost"
        data = self._request(
            "GET",
            "/api/kinko/v1/invoice/charges/.json",
            params={
                "md": "E",
                "ss": "Delivered",
                "o_pin": origin_pincode,
                "d_pin": destination_pincode,
                "cgm": int(parcel.weight_kg * 1000),
                "pt": "COD" if payment_mode == PaymentMode.COD else "Pre-paid",
                "cod": cod_amount,
            },
        )
        if isinstance(data, dict):
            data = [data]
        if not data or "total_amount" not in data[0]:
            raise ProviderError(self.provider, "no rate returned", body=data)
        return [
            Rate(provider=self.provider, amount=row["total_amount"])
            for row in data
        ]

    def create_shipment(self, request):
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
            "quantity": request.quantity,
            "weight": request.parcel.weight_kg * 1000,
            "shipment_length": request.parcel.length_cm,
            "shipment_width": request.parcel.breadth_cm,
            "shipment_height": request.parcel.height_cm,
            "waybill": request.waybill,
            "invoice_reference": request.invoice_number,
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
        if not data.get("success") or package.get("status") != "Success":
            reason = (
                "; ".join(package.get("remarks") or [])
                or data.get("rmk")
                or "shipment not created"
            )
            raise ProviderError(self.provider, reason, body=data)
        return Shipment(
            provider=self.provider,
            waybill=package["waybill"],
            order_id=request.order_id,
            status=package["status"],
            remarks=package.get("remarks") or [],
        )

    def cancel(self, waybill):
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
            message=data.get("error") or data.get("message"),
        )

    def schedule_pickup(self, request):
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
            raise ProviderError(
                self.provider, data.get("message") or "no pickup_id", body=data
            )
        return Pickup(
            provider=self.provider,
            pickup_id=str(data["pickup_id"]),
            warehouse=request.warehouse,
            pickup_date=request.pickup_date,
            pickup_time=request.pickup_time,
            package_count=request.package_count,
        )

    def ndr_action(self, request):
        entry = {"waybill": request.waybill, "act": self.NDR_ACTIONS[request.action]}
        if request.action == NdrAction.Defer:
            entry["action_data"] = {"deferred_date": request.deferred_date.isoformat()}
        elif request.action == NdrAction.EditDetails:
            details = {
                "name": request.name,
                "phone": request.phone,
                "add": request.address,
            }
            entry["action_data"] = {k: v for k, v in details.items() if v}
        data = self._request("POST", "/api/p/update", json={"data": [entry]})
        # unverified: the docs promise a UPL id but not the field name
        request_id = data.get("request_id") or data.get("upl_id")
        if not request_id:
            raise ProviderError(self.provider, "no NDR request id", body=data)
        return NdrResult(
            provider=self.provider,
            waybill=request.waybill,
            request_id=str(request_id),
            status=RequestStatus.Pending,
        )

    def ndr_status(self, request_id):
        # unverified: path and response shape of "Get NDR status"
        data = self._request(
            "GET",
            f"/api/cmu/get_bulk_upl/{request_id}",
            params={"verbose": "true"},
        )
        state = str(data.get("status", "")).lower()
        if state in ("completed", "success"):
            status = RequestStatus.Completed
        elif state == "failed":
            status = RequestStatus.Failed
        else:
            status = RequestStatus.Pending
        return NdrResult(
            provider=self.provider,
            waybill=data.get("waybill", ""),
            request_id=str(request_id),
            status=status,
            message=data.get("message"),
        )
