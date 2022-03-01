import datetime
from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse
from bs4 import BeautifulSoup


def get_elem_text(el):
    if el:
        el = el.strip()
        return ' '.join(el.split())

@track_registry.register('first-flight')
class FirstFlight(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Arrived'):
            return StatusChoice.InTransit.value
        elif status.startswith('Sent To'):
            return StatusChoice.InTransit.value
        elif status.startswith('With Delivery'):
            return StatusChoice.OutForDelivery.value
        elif status.startswith('Delivered to'):
            return StatusChoice.Delivered.value
        elif status.startswith('Delivered To'):
            return StatusChoice.Delivered.value
        elif 'shipment' in status.lower():
            return StatusChoice.InTransit.value
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'first_flight', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.post(
            f'https://www.firstflight.net/check_track.php', data={"track": {self.waybill},
            "type": "awb"}
        ).text


    '''
    This method will convert self.raw_data to self.data
    '''
    def _transform(self):
        selector = parsel.Selector(text = self.raw_data)
        soup = BeautifulSoup(self.raw_data, 'html.parser')
        sub_status= get_elem_text(selector.xpath('//h4[contains(@class, "status-title")]//text()').get())
        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(sub_status),
            'substatus': sub_status,
            # 'delivered_date' : parse(get_elem_text(selector.xpath('//span[contains(@class, "delivery-date")]//text()').get())).isoformat(),
            # 'delivered_time' : get_elem_text(selector.xpath('//span[contains(@class, "delivery-time right-border")]//text()').get()),
            'destination' : get_elem_text(selector.xpath('//span[contains(@class, "destination")]//text()').get()),
            'receiver_name': sub_status.split('- ')[1] if sub_status.startswith('Delivered to') else ''
        }
        checkpoints = []

        checkpoint_table = soup.find('table').find_all('tr')

        parsed_date = None
        for row in checkpoint_table:
            if row.find_all('th'):
                parsed_date= parse(get_elem_text(row.find_all('th')[0].text))
                
                
            cols = row.find_all('td')
            cols = [ele.text.strip() for ele in cols]
            cols = [ele for ele in cols if ele]
            if len(cols) != 4:
                continue
            cols.append(parsed_date)
            checkpoints.append(self._transform_checkpoint(cols))

        data['checkpoints'] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        status = scan[1]
        date = scan[4]
        time = scan[3].split(':')

        checkpoint = {
            "slug": self.provider,
            "location": scan[2],
            "country_name": "",
            "message": status,
            "submessage": status,
            "country_iso3": "",
            "status": self.status_mapper(status),
            "substatus": status,
            "checkpoint_time": date+datetime.timedelta(hours=int(time[0]), minutes=int(time[1])),
            "state": None,
            "zip": None,
        }

        return checkpoint