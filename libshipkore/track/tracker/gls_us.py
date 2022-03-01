from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return " ".join(el.split())


@track_registry.register("gls-us")
class GLS_USA(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Package details received"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("Received at"):
            return StatusChoice.InTransit.value
        elif status.startswith("Exported i-Parcel"):
            return StatusChoice.InTransit.value
        elif status.startswith("With Customs"):
            return StatusChoice.InTransit.value
        elif status.startswith("Arrived at destination"):
            return StatusChoice.InTransit.value
        elif status.startswith("An airline delay has occurred"):
            return StatusChoice.InTransit.value
        elif status.startswith("In transit"):
            return StatusChoice.InTransit.value
        elif status.startswith("Out for Delivery"):
            return StatusChoice.OutForDelivery.value
        elif status.lower().startswith("delivered"):
            return StatusChoice.Delivered.value
        elif "Delivered" in status:
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "gls-usa", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.post(
            "https://www.gls-us.com/Tracking", data={"TrackingNumber": self.waybill}
        ).text
        # print(self.raw_data, "###")

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        sub_status = selector.xpath(
            '//*[@id="packagedetails"]/tr[4]/td[2]/span/text()'
        ).get()
        print(sub_status)

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_mapper(sub_status),
            "substatus": sub_status,
            "estimated_date": None,
            "delivered_date": parse(
                selector.xpath(
                    '//*[@id="packagedetails"]/tr[6]/td[2]/span/text()'
                ).get()
            ),
            "delivered_time": "",
            "reference_no": "",
            "destination": selector.xpath(
                '//*[@id="packagedetails"]/tr[3]/td[2]/span/text()'
            ).get(),
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
            "status": self.status_mapper(scan[-1]),
            "substatus": scan[-1],
            "checkpoint_time": parse(scan[0] + scan[1]),
            "state": None,
            "zip": None,
        }

        return checkpoint
