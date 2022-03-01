from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
from dateutil.parser import parse


@track_registry.register("spoton")
class SpotonLogistics(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Shipment Created"):
            return StatusChoice.InfoReceived.value
        if status.startswith("Consignment Booked"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("Dispatched to"):
            return StatusChoice.InTransit.value
        elif status.startswith("Shipment forwarded"):
            return StatusChoice.InTransit.value
        elif status.startswith("Received at"):
            return StatusChoice.InTransit.value
        elif status.startswith("Out For Delivery"):
            return StatusChoice.OutForDelivery.value
        elif "Delivered" in status:
            return StatusChoice.Delivered.value
        elif status.startswith("Pickup Requested"):
            return StatusChoice.AvailableForPickup.value
        elif status.startswith("Refused - Delivery"):
            return StatusChoice.AttemptFail.value
        elif "Incomplete Delivery Addres" in status:
            return StatusChoice.AttemptFail.value
        elif "Ready for Delivery" in status:
            return StatusChoice.InTransit.value

        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "spoton_logistics", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.post(
            "https://web1.spoton.co.in/spotonConTracking",
            data={"conNo": {self.waybill}},
        ).json()
        # print(self.raw_data)

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": scan.get("LOCATIONAME"),
            "location": scan.get("LOCATIONAME"),
            "country_name": "India",
            "country_iso3": "IND",
            "status": self.status_mapper(scan.get("STATUSDESC", "")),
            "substatus": scan.get("STATUSDESC", ""),
            "checkpoint_time": parse(
                scan.get("STATUSDATE", "") + " " + scan.get("STATUSTIME", "")
            ),
            "state": None,
            "zip": None,
        }

        return checkpoint

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        waybill_data = self.raw_data.get("ConStatusDetailsOut")[0]
        waybill_detail = self.raw_data.get("ConDetailOut")[0]
        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_mapper(waybill_data.get("CONSTATUSDESC", "")),
            "substatus": waybill_data.get("CONSTATUSDESC", ""),
            "estimated_date": parse(waybill_data.get("ETADate")),
            "reference_no": waybill_detail.get("RefNumber"),
            "destination": waybill_detail.get("Destination"),
            "consignee_address": waybill_data.get("consigneeAddress"),
            "product": waybill_detail.get("ProductDesc"),
            "receiver_name": "",
        }
        checkpoints = []
        for scan in self.raw_data.get("ConStatusGridDetailsOut", [])[::-1]:
            checkpoints.append(self._transform_checkpoint(scan))

        data["checkpoints"] = checkpoints

        self.data = data
        return data
