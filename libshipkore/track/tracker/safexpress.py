from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return " ".join(el.split())


@track_registry.register("safexpress")
class SafeExpress(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Shipment Created"):
            return StatusChoice.InfoReceived
        if status.startswith("BOOKED"):
            return StatusChoice.InfoReceived
        elif status.startswith("In Transit"):
            return StatusChoice.InTransit
        elif "in-transit" in status.lower():
            return StatusChoice.InTransit
        elif status.startswith("Out For Delivery"):
            return StatusChoice.OutForDelivery
        elif status.startswith("Shipment Delivered"):
            return StatusChoice.Delivered
        elif status == "Shipment Out For Delivery":
            return StatusChoice.OutForDelivery
        elif status == "Shipment Arrived":
            return StatusChoice.InTransit
        elif status == "Shipment Further Connected":
            return StatusChoice.InTransit
        elif status == "Shipment Arrived At Hub":
            return StatusChoice.InTransit
        elif status == "Shipment Picked Up":
            return StatusChoice.InTransit
        elif status == "Online Shipment Booked":
            return StatusChoice.InfoReceived
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "safexpress", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.get(
            f"http://www.safexpress.com/Portal/faces/TrackShipment.jspx?waybl_no_ht={self.waybill}"
        ).text
        # self.checkpoint_data=
        # print(self.raw_data, "####")

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        checkpoint_table = selector.xpath('//*[@id="pt1:pgl9"]/div/table/tr')

        checkpoints = []
        checkpoint_data = []
        for rows in checkpoint_table:
            rows = rows.xpath(".//td//text()").getall()
            row = [ele.strip() for ele in rows]
            row = [ele for ele in row if ele]
            # print(row)
            if row == []:
                continue
            checkpoint_data.append(row)
            checkpoints.append(self._transform_checkpoint(row))

        sub_status = checkpoint_data[0][0]
        status = self.status_mapper(sub_status)
        delivered_date = None
        if status == StatusChoice.Delivered.value:
            delivered_date = checkpoint_data[0][1]

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": status,
            "substatus": sub_status,
            "estimated_date": None,
            "delivered_date": delivered_date,
            "delivered_time": "",
            "reference_no": "",
            "destination": selector.xpath(
                '//*[@id="pt1:pgl16"]/tbody/tr/td[5]/span//text()'
            )
            .get()
            .split(": ")[1],
            "receiver_name": "",
        }

        data["checkpoints"] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        status = get_elem_text(scan[0])
        date = get_elem_text(scan[1])
        parsed_date = parse(date).isoformat()

        checkpoint = {
            "slug": self.provider,
            "location": scan[2],
            "country_name": "India",
            "message": scan[2],
            "submessage": scan[2],
            "country_iso3": "IND",
            "status": self.status_mapper(status),
            "substatus": status,
            "checkpoint_time": parsed_date,
            "state": None,
            "zip": None,
        }

        return checkpoint
