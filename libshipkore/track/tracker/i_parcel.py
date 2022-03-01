from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return " ".join(el.split())


@track_registry.register("i-parcel")
class IParcel(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Package details received"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("Received at"):
            return StatusChoice.InTransit.value
        elif status.startswith("An airline delay has occurred"):
            return StatusChoice.InTransit.value
        elif status.startswith("In transit"):
            return StatusChoice.InTransit.value
        elif "in transit" in status.lower():
            return StatusChoice.InTransit.value
        elif "received at" in status.lower():
            return StatusChoice.InTransit.value
        elif "airline" in status.lower():
            return StatusChoice.InTransit.value
        elif "with customs" in status.lower():
            return StatusChoice.InTransit.value
        elif "exported i-parcel" in status.lower():
            return StatusChoice.InTransit.value
        elif "arrived" in status.lower():
            return StatusChoice.InTransit.value
        elif status.startswith("Out for Delivery"):
            return StatusChoice.OutForDelivery.value
        elif "delivered" in status.lower():
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "i-parcel", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.post(
            "https://tracking.i-parcel.com/", data={"TrackingNumber": self.waybill}
        ).text
        # print(self.raw_data, "###")

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        sub_status = selector.xpath('//*[@class="trackingResults"]/div[1]/text()').get()

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_mapper(sub_status),
            "substatus": sub_status,
            "estimated_date": None,
            "delivered_date": None,
            "delivered_time": "",
            "reference_no": "",
            "destination": selector.xpath("/html/body/div[1]/div[2]/b/text()").get(),
            "receiver_name": "",
        }

        checkpoint_data = selector.xpath(
            '//*[@class="trackingResults"]/div[@class="row result"]'
        )
        checkpoints = []

        for rows in checkpoint_data:
            cols = []
            for ele in rows.xpath(".//div"):
                date = ele.xpath(".//span/strong/text()").get()
                if date:
                    cols.append(date)
                else:
                    cols.append(date)
                cols.append(ele.xpath(".//span/text()").get())
                cols = [ele for ele in cols if ele]
            if cols == []:
                break
            checkpoints.append(self._transform_checkpoint(cols))

        data["checkpoints"] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):

        checkpoint = {
            "slug": self.provider,
            "location": "",
            "country_name": "",
            "message": "",
            "submessage": "",
            "country_iso3": "",
            "status": self.status_mapper(scan[-1].strip()),
            "substatus": scan[-1].strip(),
            "checkpoint_time": parse(scan[0] + scan[1][:-3]),
            "state": None,
            "zip": None,
        }

        return checkpoint
