from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel


def get_elem_text(el):
    if el:
        el = el.strip()
        return " ".join(el.split())


@track_registry.register("spee-dee")
class SpeeDee(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("SHIPMENT INFORMATION SENT TO PILOT"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("WAITING FOR PICKUP"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("DRIVER DISPATCHED"):
            return StatusChoice.InTransit.value
        elif status.startswith("PICKED UP"):
            return StatusChoice.InTransit.value
        elif status.startswith("TENDERED TO CARRIER"):
            return StatusChoice.InTransit.value
        elif status.startswith("In transit"):
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
        super().__init__(waybill, "spee-dee", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.post(
            f"https://packages.speedeedelivery.com/track_shipment.php?barcodes={self.waybill}"
        ).text
        # print(self.raw_data, "###")

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        sub_status = selector.xpath(
            '//*[@id="frameBody"]/table/tbody/tr[1]/td[2]/strong/text()'
        ).get()
        status = self.status_mapper(sub_status)
        delivered_date = None
        delivere_time = None
        if status == "Delivered":
            delivered_date = (
                selector.xpath('//*[@id="frameBody"]/table/tbody/tr[1]/td[4]/text()')
                .get()
                .split()[0]
            )
            delivere_time = (
                selector.xpath('//*[@id="frameBody"]/table/tbody/tr[1]/td[4]/text()')
                .get()
                .split()[1]
            )

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": status,
            "substatus": sub_status,
            "estimated_date": "",
            "delivered_date": delivered_date,
            "delivered_time": delivere_time,
            "reference_no": "",
            "destination": "",
            "receiver_name": "",
        }

        checkpoint_data = selector.xpath('//*[@id="frameBody"]/table/tbody/tr')
        # print(checkpoint_data)
        checkpoints = []

        for rows in checkpoint_data:

            cols = [ele.xpath(".//text()").get() for ele in rows.xpath(".//td")]
            print(cols)
        data["checkpoints"] = checkpoints
        return data

    def _transform_checkpoint(self, scan):

        checkpoint = {
            "slug": self.provider,
            "location": "",
            "country_name": "United States",
            "message": "",
            "submessage": "",
            "country_iso3": "US",
            "status": self.status_mapper(scan[-1]),
            "substatus": scan[-1],
            "checkpoint_time": scan[0] + scan[1],
            "state": None,
            "zip": None,
        }

        return checkpoint
