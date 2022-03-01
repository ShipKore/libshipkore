from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel

# from dateutil.parser import parse


def get_elem_text(el):
    sentence = ""
    if el:
        for word in el:
            s_word = word.strip()
            if s_word[0].isalpha():
                sentence = sentence + s_word + " "
        return sentence.strip()


@track_registry.register("rl-carriers")
class RLCarriers(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Picked Up"):
            return StatusChoice.InTransit.value
        elif status.startswith("Departed"):
            return StatusChoice.InTransit.value
        elif status.startswith("Accepted"):
            return StatusChoice.InTransit.value
        elif status.startswith("Arrived"):
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
        super().__init__(waybill, "rl-carriers", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.post(
            " https://www.rlcarriers.com/freight/shipping/shipment-tracing?source=web",
            data={
                " https://www.rlcarriers.com/freight/shipping/shipment-tracing?source=web": self.waybill
            },
        ).text
        # print(self.raw_data, "####")

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        sub_status = selector.xpath(
            '//*[@id="result-container"]/h4/span[3]/text()'
        ).get()
        print(sub_status)
        # sub_status = sub_status.strip() if sub_status else ''

        # soup= BeautifulSoup(self.raw_data, 'html.parser')
        # soup_data= soup.find('table').find_all('tr')

        # checkpoints = []
        # checkpoints_data= []
        # checkpoint_table = soup_data
        # for row in checkpoint_table:
        #     if row == []:
        #         continue
        #     cols= row.find_all('td')
        #     cols = [ele.text.strip() for ele in cols]
        #     cols = [ele for ele in cols if ele]
        #     if len(cols) != 3:
        #         continue
        #     checkpoints.append(self._transform_checkpoint(cols))
        #     checkpoints_data.append(cols)
        # delivered_date = None
        # delivered_time = None
        # if sub_status == 'Delivered':
        #     delivered_date= checkpoints_data[0][0].split(' at ')[0]
        #     delivered_time= checkpoints_data[0][0].split(' at ')[1]
        # data = {
        #     'waybill': self.waybill,
        #     'provider': self.provider,
        #     'status': self.status_mapper(sub_status),
        #     'substatus': sub_status,
        #     'estimated_date': '',
        #     'delivered_date' : delivered_date,
        #     'delivered_time' : delivered_time,
        #     'reference_no' : '',
        #     'destination' : '',
        #     'receiver_name': ''
        # }

        # data['checkpoints'] = checkpoints

        # self.data = data

    def _transform_checkpoint(self, scan):

        checkpoint = {
            "slug": self.provider,
            "location": scan[2],
            "country_name": "Unites States",
            "message": "",
            "submessage": "",
            "country_iso3": "US",
            "status": self.status_mapper(scan[1]),
            "substatus": scan[1],
            "checkpoint_time": scan[0],
            "state": None,
            "zip": None,
        }

        return checkpoint
