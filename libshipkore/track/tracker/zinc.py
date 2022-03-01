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


@track_registry.register("zinc")
class Zinc(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Package arrived"):
            return StatusChoice.InTransit.value
        elif status.startswith("Carrier picked"):
            return StatusChoice.InTransit.value
        elif status.startswith("Package left"):
            return StatusChoice.InTransit.value
        elif status.startswith("In Transit"):
            return StatusChoice.InTransit.value
        elif status.startswith("InTransit"):
            return StatusChoice.InTransit.value
        elif "out for delivery" in status:
            return StatusChoice.OutForDelivery.value
        elif status.startswith("Package delivered"):
            return StatusChoice.Delivered.value
        elif "Delivered" in status:
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "zinc", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.get(
            f"https://www.priceyak.com/v0/async/zinctracking/{self.waybill}"
        ).json()
        # print(self.raw_data, "####")

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": "",
            "location": scan.get("location"),
            "country_name": "United States",
            "message": scan.get("message", ""),
            "submessage": scan.get("message", ""),
            "country_iso3": "US",
            "status": self.status_mapper(scan.get("message", "")),
            "substatus": scan.get("message"),
            "checkpoint_time": parse(scan.get("time")) if scan.get("time") else None,
            "state": None,
            "zip": None,
        }

        return checkpoint

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        waybill_data = self.raw_data
        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_mapper(waybill_data.get("status")),
            "substatus": waybill_data.get("status"),
            "estimated_date": None,
            "reference_no": "",
            "package_type": "",
            "destination": waybill_data.get("destination"),
            "client": "",
            "consignee_address": "",
            "product": "",
            "receiver_name": "",
        }
        checkpoints = []
        for scan in waybill_data.get("history", [{}]):
            checkpoints.append(self._transform_checkpoint(scan))

        data["checkpoints"] = checkpoints

        self.data = data
        return data
