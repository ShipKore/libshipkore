from datetime import datetime
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


@track_registry.register("apc")
class APCPostalLogistics(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Parcel Data Received"):
            return StatusChoice.InfoReceived.value
        elif "en route" in status.lower():
            return StatusChoice.InTransit.value
        elif status.startswith("Parcel Order"):
            return StatusChoice.InTransit.value
        elif status.startswith("Departed"):
            return StatusChoice.InTransit.value
        elif status.startswith("Processed"):
            return StatusChoice.InTransit.value
        elif status.startswith("Shipment"):
            return StatusChoice.InTransit.value
        elif status.startswith("In-Transit"):
            return StatusChoice.InTransit.value
        elif status.startswith("Out for Delivery"):
            return StatusChoice.OutForDelivery.value
        elif status.startswith("Delivered"):
            return StatusChoice.Delivered.value
        elif "Delivered" in status:
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "apc", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.get(
            f"https://api2.apc-pli.com/api/tracking/{self.waybill}",
            headers={"authorization": "Basic MTIxMjo1MkpkWWVjXiYw"},
        ).json()
        # print(self.raw_data, "####")

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": "",
            "location": scan.get("location"),
            "country_name": scan.get("countryCode"),
            "message": scan.get("description"),
            "submessage": "",
            "country_iso3": scan.get("countryCode"),
            "status": self.status_mapper(scan.get("description", "")),
            "substatus": scan.get("description"),
            "checkpoint_time": datetime.strptime(
                scan.get("date", ""), "%m.%d.%Y %I:%M:%S %p"
            ),  # 02.05.2022 01:27:00 PM
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
            "status": self.status_mapper(
                waybill_data.get("events", [{}])[0].get("description")
            ),
            "substatus": waybill_data.get("events", [{}])[0].get("description"),
            "estimated_date": datetime.strptime(
                waybill_data.get("estimatingDeliveryTime"), "%m.%d.%Y %I:%M:%S %p"
            )
            if waybill_data.get("estimatingDeliveryTime")
            else None,
            "reference_no": waybill_data.get("trackingReference1"),
            "package_type": "",
            "destination": waybill_data.get("shipToAddress"),
            "client": "",
            "consignee_address": waybill_data.get("shipToAddress"),
            "product": waybill_data.get("serviceName"),
            "receiver_name": "",
        }

        checkpoints = []
        for scan in waybill_data.get("events", [{}]):
            checkpoints.append(self._transform_checkpoint(scan))

        data["checkpoints"] = checkpoints

        self.data = data
        return data
