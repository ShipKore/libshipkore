from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
from dateutil.parser import parse


def get_elem_text(el):
    sentence = ""
    if el:
        for word in el:
            s_word = word.strip()
            if s_word[0].isalpha():
                sentence = sentence + s_word + " "
        return sentence.strip()


@track_registry.register("yrc")
class YRC(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("NOW AT"):
            return StatusChoice.InTransit.value
        elif status.startswith("Now on"):
            return StatusChoice.InTransit.value
        elif status.startswith("Out for Delivery"):
            return StatusChoice.OutForDelivery.value
        elif status.startswith("Your package has been delivered"):
            return StatusChoice.Delivered.value
        elif "Delivered" in status:
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "yrc", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.get(
            f"https://my.yrc.com/tools/api/shipments/{self.waybill}",
            headers={
                "Referer": f"https://my.yrc.com/tools/track/shipments?referenceNumber={self.waybill}&referenceNumberType=PRO",
            },
        ).json()
        # print(self.raw_data, "####")

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        waybill_data = self.raw_data.get("shipments", [{}])[0]

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_mapper(waybill_data.get("statusMessage")),
            "substatus": waybill_data.get("statusMessage"),
            "estimated_date": parse(waybill_data.get("dueDate"))
            if waybill_data.get("dueDate")
            else None,
            "delivered_date": parse(waybill_data.get("deliveryDate"))
            if waybill_data.get("deliveryDate")
            else None,
            "reference_no": "",
            "destination": waybill_data.get("destinationCity", "")
            + " "
            + waybill_data.get("destinationState", "")
            + " "
            + waybill_data.get("destinationZip", ""),
            "receiver_name": "",
        }

        checkpoint = {
            "slug": self.provider,
            "location": "",
            "country_name": "Unites States",
            "message": waybill_data.get("statusMessage"),
            "submessage": waybill_data.get("statusMessage"),
            "country_iso3": "US",
            "status": self.status_mapper(waybill_data.get("statusMessage")),
            "substatus": waybill_data.get("statusMessage"),
            "checkpoint_time": parse(waybill_data.get("statusDate"))
            if waybill_data.get("statusDate")
            else None,
            "state": None,
            "zip": None,
        }

        data["checkpoints"] = [checkpoint]

        self.data = data
