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
            if s_word[0].isalpha():
                sentence = sentence + s_word + " "
        return sentence.strip()


@track_registry.register("epostglobal")
class EpostGlobal(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Data Received"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("Parcel Received"):
            return StatusChoice.InTransit.value
        elif status.startswith("Parcel received"):
            return StatusChoice.InTransit.value
        elif status.startswith("E-File Uploaded"):
            return StatusChoice.InTransit.value
        elif status.startswith("Parcel Processed"):
            return StatusChoice.InTransit.value
        elif status.startswith("Parcel Shipped"):
            return StatusChoice.InTransit.value
        elif status.startswith("In transit"):
            return StatusChoice.InTransit.value
        elif status.startswith("The item"):
            return StatusChoice.InTransit.value
        elif status.startswith("Out for Delivery"):
            return StatusChoice.OutForDelivery.value
        elif "delivered" in status.lower():
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "epost_global", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.post(
            "https://portal.epgshipping.com/ParcelTracker/HomePageTracker",
            data={"trackingNumbers": self.waybill},
        ).text
        # print(self.raw_data, "####")

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        sub_status = selector.xpath(
            '//*[@id="TableParcelTracker"]/tbody/tr[1]/td[2]/text()'
        ).get()
        sub_status = sub_status.strip() if sub_status else ""
        status = self.status_mapper(sub_status)
        delivered_date = None
        delivered_time = None
        if sub_status == StatusChoice.Delivered.value:
            delivered_date = (
                selector.xpath('//*[@id="TableParcelTracker"]/tbody/tr[1]/td[3]/text()')
                .get()
                .split()[0]
            )
            delivered_time = (
                selector.xpath('//*[@id="TableParcelTracker"]/tbody/tr[1]/td[3]/text()')
                .get()
                .split()[1]
            )

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": status,
            "substatus": sub_status,
            "estimated_date": parse(delivered_date + " " + delivered_time)
            if delivered_date
            else None,
            "delivered_date": delivered_date,
            "delivered_time": delivered_time,
            "reference_no": "",
            "destination": selector.xpath(
                '//*[@id="TableParcelTracker"]/tbody/tr[1]/td[5]/text()'
            ).get(),
            "receiver_name": "",
        }

        checkpoints = []
        checkpoints_data = []
        checkpoint_table = selector.xpath(
            '//*[@id="TableParcelTracker"]/tbody/tr[1]/td[7]'
        )
        for row in checkpoint_table.xpath('./div//div[@class="row row-light"]'):
            if row == []:
                continue

            cols = [ele for ele in row.xpath(".//div/text()").getall()]
            cols = [ele for ele in cols if ele]
            if len(cols) != 3:
                cols.append(None)
            checkpoints.append(self._transform_checkpoint(cols))
            checkpoints_data.append(cols)

        data["checkpoints"] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):

        checkpoint = {
            "slug": self.provider,
            "location": scan[2],
            "country_name": "",
            "message": "",
            "submessage": "",
            "country_iso3": "",
            "status": self.status_mapper(scan[1]),
            "substatus": scan[1],
            "checkpoint_time": parse(scan[0]),
            "state": None,
            "zip": None,
        }

        return checkpoint
