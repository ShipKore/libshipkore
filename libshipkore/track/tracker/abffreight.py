from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import datetime


@track_registry.register("abffreight")
class ABF(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        print(status)
        if status.startswith("YOUR SHIPMENT HAS BEEN TRANSFERRED"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("Out for Delivery"):
            return StatusChoice.OutForDelivery.value
        elif status.startswith("Delivered"):
            return StatusChoice.Delivered.value
        elif "in transit" in status.lower():
            return StatusChoice.InTransit.value
        elif "shipment is on " in status.lower():
            return StatusChoice.InTransit.value
        elif "delivered" in status.lower():
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "abffreight", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.get(
            f"https://www.abfs.com/xml/tracexml.asp?mid=MOBILEABF&refnum={self.waybill}"
        ).json()
        # print(self.raw_data)

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": "",
            "location": "",
            "country_name": "",
            "message": "",
            "submessage": "",
            "country_iso3": "",
            "status": self.status_mapper(scan.get("longstatus", "")),
            "substatus": scan.get("longstatus"),
            "checkpoint_time": datetime.date.today(),
            "state": None,
            "zip": None,
        }

        return checkpoint

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        waybill_data = self.raw_data.get("shipments", [{}])[0]

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_mapper(waybill_data.get("longstatus", "")),
            "substatus": waybill_data.get("longstatus"),
            "estimated_date": waybill_data.get("expecteddeldate"),
            "reference_no": "",
            "package_type": "",
            "destination": "",
            "client": "",
            "consignee_address": "",
            "product": "",
            "receiver_name": "",
        }

        checkpoints = []
        checkpoints.append(self._transform_checkpoint(waybill_data))

        data["checkpoints"] = checkpoints
        self.data = data
        return data
