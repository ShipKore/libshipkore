from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return " ".join(el.split())


@track_registry.register("shyplite")
class Shyplite(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Shipment Booked"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("Picked Up"):
            return StatusChoice.InTransit.value
        elif status.startswith("In Transit"):
            return StatusChoice.InTransit.value
        elif status.startswith("Out For Delivery"):
            return StatusChoice.OutForDelivery.value
        elif status.startswith("Delivered"):
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "shyplite", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.get(f"https://tracklite.in/track/{self.waybill}").text
        # print(self.raw_data, "####")

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        print(
            selector.xpath(
                "/html/body/header/div[2]/div[1]/div/p[3]/time/@datetime"
            ).get()
        )
        sub_status = selector.xpath(
            "/html/body/header/div[2]/div[1]/div/p[1]//text()"
        ).get()
        date_time = None
        if sub_status == "Delivered":
            date_time = parse(
                selector.xpath(
                    "/html/body/header/div[2]/div[1]/div/p[3]/time/@datetime"
                ).get()
            )

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_mapper(sub_status),
            "substatus": sub_status,
            "estimated_date": None,
            "delivered_date_time": date_time,
            "reference_no": "",
            "package_type": "",
            "destination": "",
            "receiver_name": "",
        }
        checkpoints = []

        checkpoint_table = selector.xpath('//*[@id="events"]/div')

        for rows in checkpoint_table:
            if len(rows.xpath(".//div")) > 1:
                rows = rows.xpath(".//div")
                for row in rows:
                    date = row.xpath(".//@datetime").get()
                    row = row.xpath(".//text()").getall()
                    row = [ele.strip() for ele in row]
                    if row == [] or len(row) == 1:
                        continue
                    row.append(date)
                    # print(row)
                    checkpoints.append(self._transform_checkpoint(row))
            else:
                date = rows.xpath(".//@datetime").get()
                row = rows.xpath(".//text()").getall()
                row = [ele.strip() for ele in row]
                row.append(date)
                checkpoints.append(self._transform_checkpoint(row))

        data["checkpoints"] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        status = get_elem_text(scan[2])
        date = get_elem_text(scan[-1])
        parsed_date = parse(date)

        checkpoint = {
            "slug": self.provider,
            "location": scan[4],
            "country_name": "",
            "message": scan[-3],
            "submessage": scan[-3],
            "country_iso3": "",
            "status": self.status_mapper(status),
            "substatus": status,
            "checkpoint_time": parsed_date,
            "state": None,
            "zip": None,
        }

        return checkpoint
