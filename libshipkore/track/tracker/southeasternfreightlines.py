from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return " ".join(el.split())


@track_registry.register("southeasternfreightlines")
class SoutheasternFreightLines(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("OS&D"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("Shipment Pickup"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("In Transit"):
            return StatusChoice.InTransit.value
        elif status.startswith("Private"):
            return StatusChoice.InTransit.value
        elif status.startswith("Dispatched"):
            return StatusChoice.InTransit.value
        elif status.startswith("Closed"):
            return StatusChoice.InTransit.value
        elif status.startswith("Arrive"):
            return StatusChoice.InTransit.value
        elif status.startswith("Out For Delivery"):
            return StatusChoice.OutForDelivery.value
        elif status.startswith("Shipment Delivered"):
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "southeasternfreightlines", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.post(
            "https://www.sefl.com/Tracing/servlet/TRACING_TRACE_BY_PRO?Type=PN",
            data={"RefNum": self.waybill},
        ).text
        # print(self.raw_data, "####")

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)

        sub_status = (
            selector.xpath('//*[@id="resultsTable"]/tbody/tr[13]/td[4]/text()')
            .get()
            .strip()
        )
        status_content = selector.xpath(
            "//td[contains(text(), 'Status:')]/following-sibling::td[1]/text()"
        ).getall()
        result = [i for i in status_content if i.startswith("ETA:")]

        status = self.status_mapper(sub_status)
        delivered_date = None
        if status == StatusChoice.Delivered.value:
            delivered_date = parse(sub_status.split(" as of ")[1])

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": status,
            "substatus": sub_status,
            "estimated_date": parse(result[0].strip("ETA:")) if result else None,
            "delivered_date": delivered_date,
            "reference_no": "",
            "destination": selector.xpath(
                '//*[@id="resultsTable"]/tbody/tr[10]/td[4]/a/text()'
            ).get(),
            "receiver_name": "",
        }
        checkpoints = []

        checkpoint_table = selector.xpath(
            f'//*[@id="detail{self.waybill}"]/table/tbody/tr'
        )
        for rows in checkpoint_table[::-1]:
            cols = rows.xpath("./td/text()").getall()
            cols = [ele.strip() for ele in cols if ele.strip()]
            print(cols)
            if cols == []:
                break
            checkpoints.append(self._transform_checkpoint(cols))

        data["checkpoints"] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        message = " ".join(scan[2:]) if (len(scan) > 3) else scan[-1]

        checkpoint = {
            "slug": self.provider,
            "location": scan[1],
            "country_name": "",
            "message": message,
            "submessage": "",
            "country_iso3": "",
            "status": self.status_mapper(message),
            "substatus": message,
            "checkpoint_time": parse(scan[0]),
            "state": None,
            "zip": None,
        }

        return checkpoint
