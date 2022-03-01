from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return " ".join(el.split())


@track_registry.register("shreeanjanicourier")
class ShreeAnjaniCourier(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Shipment Created"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("IN DELIVERY PROCESS"):
            return StatusChoice.InTransit.value
        elif status.startswith("Out For Delivery"):
            return StatusChoice.OutForDelivery.value
        elif status.startswith("DELIVERED ON"):
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "shreeanjanicourier", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.get(
            f"http://anjanicourier.in/Doc_Track.aspx?No={self.waybill}"
        ).text
        # print(self.raw_data, "####")

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        sub_status = selector.xpath('//*[@id="lblStatus"]//text()').get()
        status = self.status_mapper(sub_status)
        delivered_date = None
        if status == StatusChoice.Delivered.value:
            delivered_date = parse(sub_status.split("ON ")[1])

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": status,
            "substatus": sub_status,
            "estimated_date": None,
            "delivered_date": delivered_date,
            "reference_no": "",
            "destination": selector.xpath('//*[@id="lblToCenter"]//text()').get(),
            "receiver_name": "",
        }
        checkpoints = []
        checkpoint = []

        checkpoint_table = selector.xpath('//*[@id="EntryTbl"]/tr')

        for rows in checkpoint_table:
            row = rows.xpath(".//text()").getall()
            row = [ele.strip() for ele in row]
            row = [ele for ele in row if ele]
            if row == []:
                break
            checkpoint.append(row)

        row_count = 0
        for i in range(int(len(checkpoint) / 2)):
            row = [checkpoint[row_count][0], checkpoint[row_count + 1][0]]
            row_count += 2
            checkpoints.append(self._transform_checkpoint(row))

        data["checkpoints"] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        date = get_elem_text(scan[1].split(" -> ")[1])
        parsed_date = parse(date)

        checkpoint = {
            "slug": self.provider,
            "location": scan[0].split(" -> ")[0],
            "country_name": "India",
            "message": scan[0],
            "submessage": scan[0],
            "country_iso3": "IND",
            "status": StatusChoice.InTransit,
            "substatus": "",
            "checkpoint_time": parsed_date,
            "state": None,
            "zip": None,
        }

        return checkpoint
