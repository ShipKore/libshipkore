from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return " ".join(el.split())


@track_registry.register("ecom-express")
class EcomExpress(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Information Received"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("Pickup Completed"):
            return StatusChoice.InTransit.value
        elif status.startswith("In-Transit"):
            return StatusChoice.InTransit.value
        elif status.startswith("Shipment at"):
            return StatusChoice.InTransit.value
        elif status.startswith("Shipment Delivered"):
            return StatusChoice.Delivered.value
        elif status == "Out for Delivery":
            return StatusChoice.OutForDelivery.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "ecom_express", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.get(
            f"https://ecomexpress.in/tracking/?awb_field={self.waybill}"
        ).text
        # print(self.raw_data, "####")

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_mapper(
                selector.xpath(
                    "/html/body/section/div/div/div[1]/div[2]/div/div[1]/p[4]/span//text()"
                ).get()
            ),
            "substatus": selector.xpath(
                "/html/body/section/div/div/div[1]/div[2]/div/div[1]/p[4]/span//text()"
            ).get(),
            "estimated_date": parse(
                selector.xpath(
                    "/html/body/section/div/div/div[1]/div[2]/div/div[1]/p[1]/span/span//text()"
                )
                .get()
                .strip("hrs")
            ),
            "delivered_date": None,
            "reference_no": selector.xpath(
                "/html/body/section/div/div/div[1]/div[2]/div/div[3]/p/span//text()"
            ).get(),
            "destination": "",
            "receiver_name": "",
        }
        checkpoints = []
        checkpoint_table = selector.xpath(
            "/html/body/section/div/div/div[2]/div/div/div[2]"
        )

        for rows in checkpoint_table.xpath("./div")[::-1]:
            row = rows.xpath("./div/div[2]//text()").getall()
            if row == []:
                break
            checkpoints.append(self._transform_checkpoint(row))

        data["checkpoints"] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        status = get_elem_text(scan[1])
        date = get_elem_text(scan[6].split(": ")[1]).strip("hrs,")

        # parsed_date = parse(date).isoformat()

        checkpoint = {
            "slug": self.provider,
            "location": scan[4],
            "country_name": "India",
            "message": status,
            "submessage": status,
            "country_iso3": "IND",
            "status": self.status_mapper(status),
            "substatus": status,
            "checkpoint_time": parse(date),
            "state": None,
            "zip": None,
        }

        return checkpoint
