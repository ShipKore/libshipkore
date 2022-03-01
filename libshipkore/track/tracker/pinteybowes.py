from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice


def get_elem_text(el):
    sentence = ""
    if el:
        for word in el:
            s_word = word.strip()
            if s_word[0].isalpha():
                sentence = sentence + s_word + " "
        return sentence.strip()


@track_registry.register("pitney-bowes")
class PitneyBowes(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("HRPGBAE"):
            return StatusChoice.InTransit.value
        elif status.startswith("Processing"):
            return StatusChoice.InTransit.value
        elif status.startswith("Customs"):
            return StatusChoice.InTransit.value
        elif status.startswith("In Transit"):
            return StatusChoice.InTransit.value
        elif status.startswith("Out for Delivery"):
            return StatusChoice.OutForDelivery.value
        elif status.startswith("Delivered"):
            return StatusChoice.Delivered.value
        elif "Delivered" in status:
            return StatusChoice.Delivered.value
        elif "preparing" in status.lower():
            return StatusChoice.InTransit.value
        elif "uploaded" in status.lower():
            return StatusChoice.InTransit.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "pinteybowes", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.post(
            "https://api.shipment.co/api/search/packages/search-by-tracking-number",
            json={"trackingNumbers": [self.waybill]},
            headers={"x-tenant-id": "RALVsUZS"},
        ).json()
        # print(self.raw_data, "####")

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": scan.get("city"),
            "location": scan.get("city"),
            "message": scan.get("message"),
            "submessage": scan.get("formattedMessage"),
            "status": self.status_mapper(scan.get("eventDescription", "")),
            "substatus": scan.get("eventDescription"),
            "checkpoint_time": scan.get("isoDateTime", ""),
            "state": scan.get("state", ""),
            "zip": scan.get("postalCode", ""),
        }

        return checkpoint

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        waybill_data = self.raw_data.get("packages", [{}])[0]
        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_mapper(waybill_data.get("status")),
            "substatus": waybill_data.get("status"),
            "estimated_date": None,
            "reference_no": "",
            "package_type": "",
            "destination": waybill_data.get("shipmentAddress", {}).get("state"),
            "client": "",
            "consignee_address": waybill_data.get("shipmentAddress", {}).get("state"),
            "product": waybill_data.get("shipmentAddress", {}).get("city"),
            "receiver_name": "",
        }
        checkpoints = []
        for scan in waybill_data.get("trackingEvents", [{}]):
            checkpoints.append(self._transform_checkpoint(scan))

        data["checkpoints"] = checkpoints

        self.data = data
        return data
