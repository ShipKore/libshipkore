from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    sentence = ""
    if el:
        for word in el:
            s_word = word.strip()
            sentence += s_word + " "
        return sentence.strip()


@track_registry.register("firstmile")
class FirstMile(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Shipment info received"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("Picked Up"):
            return StatusChoice.InTransit.value
        elif status.startswith("Departed"):
            return StatusChoice.InTransit.value
        elif status.startswith("Accepted"):
            return StatusChoice.InTransit.value
        elif status.startswith("Arrived"):
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
        super().__init__(waybill, "firstmile", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.post(
            f"https://track.firstmile.com/detail.php?n={self.waybill}&tz=Asia/Calcutta",
            verify=False,
        ).text
        # print(self.raw_data, "####")

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        sub_status = selector.xpath(
            '//*[@id="packageDetail"]/div/article/section[1]/section/div/h2/text()'
        ).get()
        sub_status = sub_status.strip() if sub_status else ""
        status = self.status_mapper(sub_status)
        delivered_date = None
        if status == "Delivered":
            delivered_date = selector.xpath(
                '//*[@id="packageDetail"]/div/article/section[1]/section/div/h4/text()'
            ).get()

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": status,
            "substatus": sub_status,
            "estimated_date": None,
            "delivered_date": delivered_date,
            "delivered_time": "",
            "reference_no": "",
            "destination": "",
            "receiver_name": "",
        }

        checkpoint_section = selector.css(".historyWrap>div")

        checkpoints = []
        current_date = None

        for row in checkpoint_section:
            if "dateRow" in row.attrib["class"]:
                current_date = row.xpath("./text()").get()
                continue

            checkpoint_time = parse(current_date + row.css(".date::text").get())
            message = get_elem_text(row.css(".info *::text").getall())
            location = get_elem_text(row.css(".location *::text").getall())

            checkpoint = {
                "slug": self.provider,
                "location": location,
                "country_name": "",
                "message": message,
                "submessage": message,
                "country_iso3": "",
                "status": self.status_mapper(message),
                "substatus": message,
                "checkpoint_time": checkpoint_time,
                "state": None,
                "zip": None,
            }
            checkpoints.append(checkpoint)

        data["checkpoints"] = checkpoints
        self.data = data
