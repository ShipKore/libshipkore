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

@track_registry.register('lasership')
class LaserShip(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        status = status.lower()
        if status.startswith("we're awaiting receipt"):
            return StatusChoice.InfoReceived.value
        elif "it's way to your lasership facility" in status:
            return StatusChoice.InTransit.value
        elif status.startswith('package received by your local lasership facility'):
            return StatusChoice.InTransit.value
        elif status.startswith("we're preparing your package for delivery"):
            return StatusChoice.InTransit.value
        elif status.startswith('out for delivery'):
            return StatusChoice.OutForDelivery.value
        elif status.startswith('your package has been delivered'):
            return StatusChoice.Delivered.value
        elif 'loaded' in status:
            return StatusChoice.InTransit.value
        elif 'arrived' in status:
            return StatusChoice.InTransit.value
        elif 'order received' in status:
            return StatusChoice.InTransit.value
        elif 'origin scan' in status:
            return StatusChoice.InTransit.value
        elif 'delivered' in status:
            return StatusChoice.Delivered.value
        elif status.startswith('select the camera icon to view delivery photo'):
            return StatusChoice.Delivered.value
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'lasership', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'https://t.lasership.com/Track/{self.waybill}/json'
        ).json()
        # print(self.raw_data, "####")

    '''
    This method will convert self.raw_data to self.data
    '''
    def _transform(self):
        
        
        destination = self.raw_data.get('Destination')
        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(self.raw_data.get('Events', [{}])[0].get('EventLabel')),
            'substatus': self.status_mapper(self.raw_data.get('Events', [{}])[0].get('EventLabel')),
            'estimated_date': parse(self.raw_data.get('EstimatedDeliveryDate')),
            'delivered_date' : parse(self.raw_data.get('EstimatedDeliveryDate')) if StatusChoice.Delivered.value == self.status_mapper(self.raw_data.get('Events', [{}])[0].get('EventLabel')) else None,
            'reference_no' : self.raw_data.get('OrderNumber'),
            'destination' : " ".join(destination.values()),
            'receiver_name': ''
        }

        checkpoints = []

        for row in self.raw_data.get('Events',[]):
            checkpoints.append(self._transform_checkpoint(row))

        data['checkpoints'] = checkpoints
        
        print (data)

        self.data = data

    def _transform_checkpoint(self, scan):

        checkpoint = {
            "slug": self.provider,
            "location": scan['Location'],
            "country_name": scan['Country'],
            "message": scan['EventLongText'],
            "submessage": scan['EventLongText'],
            "country_iso3": scan['Country'],
            "status": self.status_mapper(scan['EventLabel']),
            "substatus": scan['EventLongText'],
            "checkpoint_time": parse(scan['DateTime']),
            "state": scan['State'],
            "zip": scan['PostalCode'],
        }

        return checkpoint