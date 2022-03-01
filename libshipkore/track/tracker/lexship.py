from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse
from bs4 import BeautifulSoup
import re

def get_elem_text(el):
    sentence= ""
    if el:
        for word in el:
            s_word = word.strip()
            if s_word[0].isalpha():
                sentence = sentence + s_word + " "
        return sentence.strip()

@track_registry.register('lexship')
class LexShip(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Shipment Created'):
            return StatusChoice.InfoReceived.value
        if status.startswith('Pickup Scheduled'):
            return StatusChoice.InfoReceived.value
        elif status.startswith('Received at'):
            return StatusChoice.InTransit.value
        elif status.startswith('LEX India'):
            return StatusChoice.InTransit.value
        elif status.startswith('Sent for Customs'):
            return StatusChoice.InTransit.value
        elif status.startswith('Customs Cleared'):
            return StatusChoice.InTransit.value
        elif status.startswith('Out For Delivery'):
            return StatusChoice.OutForDelivery.value
        elif status.startswith('Shipment Delivered'):
            return StatusChoice.Delivered.value
        elif 'Delivered' in status:
            return StatusChoice.Delivered.value
        elif status == 'Shipment Out For Delivery':
            return StatusChoice.OutForDelivery.value
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'lexship', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'https://track.lexship.com/track?tracking_id%5B%5D={self.waybill}'
        ).text
        # print(self.raw_data, "####")

    '''
    This method will convert self.raw_data to self.data
    '''
    def _transform(self):
        soup= BeautifulSoup(self.raw_data, 'html.parser')
        soup_data= soup.find('table').find_all('tr')

        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(get_elem_text(soup_data[0].find_all('td')[4].p.span.text.split())),
            'substatus': get_elem_text(soup_data[0].find_all('td')[4].p.span.text.split()),
            'estimated_date': None,
            'delivered_date' : None,
            'delivered_time' : '',
            'reference_no' : '',
            'destination' : get_elem_text(soup_data[0].find_all('td')[3].div.p.find('strong').text.strip().split(',')),
            'receiver_name': ''
        }

        checkpoints = []
        checkpoint_table = soup_data[1].find_all('li')

        for row in checkpoint_table:
            if row == []:
                break
            checkpoints.append(self._transform_checkpoint(row))

        data['checkpoints'] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):

        checkpoint = {
            "slug": self.provider,
            "location": '',
            "country_name": "India",
            "message": scan.span.text.strip(),
            "submessage": scan.span.text.strip(),
            "country_iso3": "IND",
            "status": self.status_mapper(scan.span.text.strip()),
            "substatus": scan.span.text.strip(),
            "checkpoint_time": parse(scan.strong.text.strip()),
            "state": None,
            "zip": None,
        }

        return checkpoint