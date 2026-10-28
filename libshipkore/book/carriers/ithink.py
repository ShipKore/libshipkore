from libshipkore.common.exceptions import ProviderError
from libshipkore.track.models.model import StatusChoice, Track
from ..base import BaseCarrier, carrier_registry


@carrier_registry.register("ithink")
class IThink(BaseCarrier):
    """
    iThink Logistics (docs.ithinklogistics.com), tracking only so far.

    The tracking request and response below are as documented in the
    "Track Order V3" page. Order creation, rates, pincode checks, NDR and
    cancel are not implemented: their v3 pages were not readable without an
    account, and nothing here guesses them.

    Credentials: access_token and secret_key, both issued by iThink.
    sandbox=True uses their pre-alpha test host.
    """

    provider = "ithink"
    base_url = "https://api.ithinklogistics.com/api_v3"
    sandbox_url = "https://pre-alpha.ithinklogistics.com/api_v3"

    # the status names in the documented status table, to the shared ones
    STATUS_MAPPER = {
        "Manifested": StatusChoice.InfoReceived,
        "Not Picked": StatusChoice.InfoReceived,
        "Picked Up": StatusChoice.InTransit,
        "In Transit": StatusChoice.InTransit,
        "Reached At Destination": StatusChoice.InTransit,
        "Out For Delivery": StatusChoice.OutForDelivery,
        "Undelivered": StatusChoice.AttemptFail,
        "Delivered": StatusChoice.Delivered,
        "RTO Pending": StatusChoice.ReverseInTransit,
        "RTO Processing": StatusChoice.ReverseInTransit,
        "RTO In Transit": StatusChoice.ReverseInTransit,
        "Reached At Origin": StatusChoice.ReverseInTransit,
        "RTO Out For Delivery": StatusChoice.ReverseOutForDelivery,
        "RTO Undelivered": StatusChoice.ReverseInTransit,
        "RTO Delivered": StatusChoice.ReverseDelivered,
        "REV Manifest": StatusChoice.InfoReceived,
        "REV Out for Pick Up": StatusChoice.InfoReceived,
        "REV Picked Up": StatusChoice.ReverseInTransit,
        "REV In Transit": StatusChoice.ReverseInTransit,
        "REV Out For Delivery": StatusChoice.ReverseOutForDelivery,
        "REV Delivered": StatusChoice.ReverseDelivered,
    }

    def track(self, waybill):
        """
        Unverified: the date format of status_date_time (read as ISO-like,
        Indian Standard Time) and which of scan_details is newest (sorted).
        """
        body = {"data": {
            "awb_number_list": waybill,
            "access_token": self._credential("access_token"),
            "secret_key": self._credential("secret_key"),
        }}
        data = self._request("POST", "/order/track.json", json=body)
        entry = (data.get("data") or {}).get(str(waybill)) or {}
        if entry.get("message") != "success":
            raise ProviderError(
                self.provider,
                entry.get("message") or f"no tracking data for {waybill}",
                body=data,
            )
        checkpoints = []
        for scan in entry.get("scan_details") or []:
            checkpoints.append({
                "slug": self.provider,
                "location": scan.get("scan_location"),
                "city": scan.get("scan_location"),
                "country_name": "India",
                "country_iso3": "IND",
                "message": scan.get("remark") or scan.get("status"),
                "submessage": scan.get("status_reason") or None,
                "substatus": scan.get("status"),
                "status": self.STATUS_MAPPER.get(
                    scan.get("status"), StatusChoice.Exception
                ),
                "checkpoint_time": self._time(scan.get("scan_date_time")),
            })
        checkpoints.sort(key=lambda c: c["checkpoint_time"], reverse=True)
        current = entry.get("current_status")
        delivered = (entry.get("order_date_time") or {}).get("delivery_date")
        return Track(
            waybill=str(waybill),
            provider=self.provider,
            status=self.STATUS_MAPPER.get(current, StatusChoice.Exception),
            substatus=current,
            estimated_date=self._time(entry.get("expected_delivery_date")),
            reference_no=(entry.get("order_details") or {}).get("order_number"),
            delivered_date=self._time(delivered),
            checkpoints=checkpoints,
        )

    @staticmethod
    def _time(value):
        value = (value or "").strip()
        if not value or value.startswith("0000"):
            return None
        return value.replace(" ", "T") + ("" if len(value) == 10 else "+05:30")
