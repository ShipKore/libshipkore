from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return " ".join(el.split())


@track_registry.register("shreenandancourier")
class ShreeNandanCourier(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Shipment Created"):
            return StatusChoice.InfoReceived.value
        elif status.startswith("Shipment Forwarded"):
            return StatusChoice.InTransit.value
        elif status.startswith("Out For Delivery"):
            return StatusChoice.OutForDelivery.value
        elif status.startswith("Shipment Reached"):
            return StatusChoice.InTransit.value
        elif "DELIVERED" in status:
            return StatusChoice.Delivered.value
        else:
            return "Exception"

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "shreenandancourier", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.get(
            f"http://shreenandancourier.com/TrackingInfo.aspx?cn={self.waybill}"
        ).text
        # print(self.raw_data, "####")

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        sub_status = selector.xpath(
            '//*[@id="content_DeliveryStatusLabel"]//text()'
        ).get()
        date_time = (
            selector.xpath('//*[@id="content_DeliveryDateLabel"]//text()').get().strip()
        )
        print("date_time")
        print(date_time)
        # date= None
        # time= None
        # if date_time:
        #     date = [' '.join(date_time.split()[i: i + 3]) for i in range(0, len(date_time.split()), 3)][0]
        #     time= [' '.join(date_time.split()[i: i + 3]) for i in range(0, len(date_time.split()), 3)][1]

        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_mapper(sub_status)
            if sub_status.strip()
            else StatusChoice.InTransit,
            "substatus": sub_status,
            "estimated_date": None,
            "delivered_date": parse(date_time) if date_time else None,
            # 'delivered_time' : time,
            "reference_no": "",
            "package_type": selector.xpath(
                '//*[@id="content_ConsignmentTypeLabel"]//text()'
            ).get(),
            "destination": selector.xpath(
                '//*[@id="content_DestinationCenterLabel"]//text()'
            ).get(),
            "receiver_name": "",
        }
        checkpoints = []

        checkpoint_table = selector.xpath('//*[@id="content_TravelInfoGridView"]/tr')

        for rows in checkpoint_table:
            rows = rows.xpath(".//td//text()").getall()
            row = [ele.strip() for ele in rows]
            row = [ele for ele in row if ele]
            # print(row)
            if row == []:
                continue
            checkpoints.append(self._transform_checkpoint(row))

        data["checkpoints"] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        status = get_elem_text(scan[2])
        date = get_elem_text(scan[0])
        parsed_date = parse(date)

        checkpoint = {
            "slug": self.provider,
            "location": scan[3],
            "country_name": "India",
            "message": status,
            "submessage": status,
            "country_iso3": "IND",
            "status": self.status_mapper(status),
            "substatus": status,
            "checkpoint_time": parsed_date,
            "state": None,
            "zip": None,
        }

        return checkpoint
