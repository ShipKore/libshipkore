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

@track_registry.register('shreetirupati')
class STCS(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Shipment Created'):
            return StatusChoice.InfoReceived
        elif status.startswith('In Transit'):
            return StatusChoice.InTransit
        elif status.startswith('Out For Delivery'):
            return StatusChoice.OutForDelivery
        elif status.startswith('Shipment Delivered'):
            return StatusChoice.Delivered
        elif status == 'Shipment Out For Delivery':
            return StatusChoice.OutForDelivery
        elif status == 'Shipment Arrived':
            return StatusChoice.InTransit
        elif status.startswith('Received'):
            return StatusChoice.InTransit
        elif status == 'Shipment Further Connected':
            return StatusChoice.InTransit
        elif status == 'Shipment Arrived At Hub':
            return StatusChoice.InTransit
        elif status == 'Shipment Picked Up':
            return StatusChoice.InTransit
        elif status == 'Online Shipment Booked':
            return StatusChoice.InfoReceived
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'shreetirupati', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'http://www.shreetirupaticourier.net/frm_doctrackweb.aspx?docno={self.waybill}'
        ).text
        # print(self.raw_data)

    '''
    This method will convert self.raw_data to self.data
    '''
    def _transform(self):
        selector = parsel.Selector(text = self.raw_data)
        soup = BeautifulSoup(self.raw_data, 'html.parser')
        status = selector.xpath('//*[@id="lblStatus"]//text()').get()
        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'destination' : selector.xpath('//*[@id="txtToCenter"]//text()').get(),
            'status': self.status_mapper(status)
        }
        checkpoints = []
        checkpoint_table = soup.find('table', id='tblTrack').find_all('tr')
        

        for row in reversed(checkpoint_table[1:]):
            if row == []:
                break
            checkpoints.append(self._transform_checkpoint(row.find_all('td')))

        data['checkpoints'] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        location_list= scan[2].text.split(' ')

        for i in range(len(location_list)):
            if location_list[i] in ['To:', 'At:']:
                location = location_list[i+1]
                if len(location_list) > 4:
                    location += location_list[i+2] if location_list[i+2] not in ['To:', 'At:', 'From:'] else ''
        date = scan[1].text.strip()
        parsed_date = parse(date)

        checkpoint = {
            "slug": self.provider,
            "location": location,
            "country_name": "India",
            "country_iso3": "IND",
            "checkpoint_time": parsed_date,
            "state": None,
            "zip": None,
            "status": StatusChoice.InTransit.value,
            "message": " ".join(location_list)
        }

        return checkpoint