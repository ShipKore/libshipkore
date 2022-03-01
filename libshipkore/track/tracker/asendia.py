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

@track_registry.register('asendia-usa')
class AsendiaUSA(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Shipment Information Received"):
            return StatusChoice.InfoReceived.value
        elif 'parcel processed' in status.lower():
            return StatusChoice.InTransit.value
        elif 'manifested for outbound' in status.lower():
            return StatusChoice.InTransit.value
        elif 'shipment departed' in status.lower():
            return StatusChoice.InTransit.value
        elif 'shipment arrived' in status.lower():
            return StatusChoice.InTransit.value
        elif status.startswith('Processed by'):
            return StatusChoice.InTransit.value
        elif status.startswith("Sorted by"):
            return StatusChoice.InTransit.value
        elif status.startswith("Departed"):
            return StatusChoice.InTransit.value
        elif status.startswith("Dispatched"):
            return StatusChoice.InTransit.value
        elif status.startswith("Shipment Dispatched"):
            return StatusChoice.InTransit.value
        elif status.startswith('Out for Delivery'):
            return StatusChoice.OutForDelivery.value
        elif status.startswith('Delivered'):
            return StatusChoice.Delivered.value
        elif 'Delivered' in status:
            return StatusChoice.Delivered.value
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'asendia-usa', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'https://a1reportapi.asendiaprod.com/api/A1/TrackingBranded/Tracking?trackingKey=AE654169-0B14-45F9-8498-A8E464E13D26&trackingNumber={self.waybill}',
            headers= {
                'authorization': 'Basic Q3VzdEJyYW5kLlRyYWNraW5nQGFzZW5kaWEuY29tOjJ3cmZzelk4cXBBQW5UVkI=',
                'x-asendiaone-apikey': '32337AB0-45DD-44A2-8601-547439EF9B55'
            }
        ).json()
        # print(self.raw_data, "####")

    '''
    This method will convert self.raw_data to self.data
    '''
    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": scan.get('eventLocationDetails',{}).get('city', ''),
            "location": scan.get('eventLocationDetails',{}).get('addressLine1', ''),
            "country_name": scan.get('eventLocationDetails',{}).get('countryName', ''),
            "message": '',
            "submessage": '',
            "country_iso3": scan.get('eventLocationDetails',{}).get('countryIso2', ''),
            "status": self.status_mapper(scan.get('eventDescription', '')),
            "substatus": scan.get('eventDescription', ''),
            "checkpoint_time": parse(scan.get('eventOn', '')),
            "state": scan.get('eventLocationDetails',{}).get('province', ''),
            "zip": scan.get('eventLocationDetails',{}).get('postalCode', ''),
        }
        return checkpoint

    '''
    This method will convert self.raw_data to self.data
    '''

    def _transform(self):
        waybill_data = self.raw_data
        sub_status= waybill_data.get('trackingBrandedDetail', [])[0].get('eventDescription', '')
        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(sub_status),
            'substatus': sub_status,
            'estimated_date': None,
            'reference_no': waybill_data.get('trackingBrandedSummary', {}).get('trackingNumberCustomer', ''),
            'package_type': waybill_data.get('trackingBrandedSummary', {}).get('service', ''),
            'destination': waybill_data.get('trackingBrandedSummary', {}).get('destinationCountry', ''),
            'client': '',
            'consignee_address': '',
            'product': '',
            'receiver_name': '',
        }

        checkpoints = []
        for scan in waybill_data.get('trackingBrandedDetail', []):
            checkpoints.append(self._transform_checkpoint(scan))
        

        data['checkpoints'] = checkpoints

        self.data = data
        return data