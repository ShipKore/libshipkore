from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse


def get_elem_text(el):
    if el and el.text:
        return el.text.strip()


@track_registry.register('ekart')
class Ekart(BaseTrackService):

    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Shipment Created'):
            return 'InfoReceived'
        elif status.startswith('Dispatched to'):
            return 'InTransit'
        elif status.startswith('Received at'):
            return 'InTransit'
        elif status.startswith('Out For Delivery'):
            return 'OutForDelivery'
        elif status.startswith('Delivered'):
            return 'Delivered'
        elif status.startswith('Pickup Requested'):
            return 'AvailableForPickup'
        elif status.startswith('Out For Pickup'):
            return 'AvailableForPickup'
        elif status.startswith('Picked up'):
            return 'ReverseInTransit'
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'ekart', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.post(
            'https://ekartlogistics.com/ws/getTrackingDetails', json= {'trackingId': f'{self.waybill}'}
        ).json()
        # print(self.raw_data)

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": scan.get('city'),
            "location": scan.get('city'),
            "country_name": "India",
            "message": scan.get('instructions'),
            "submessage": scan.get('instructions'),
            "country_iso3": "IND",
            "status": self.status_mapper(scan.get('statusDetails', '')),
            "substatus": scan.get('statusDetails'),
            "checkpoint_time": scan.get('date', ''),
            "state": None,
            "zip": None,
        }

        return checkpoint

    '''
    This method will convert self.raw_data to self.data
    '''

    def _transform(self):
        waybill_data = self.raw_data
        sub_status= waybill_data['shipmentTrackingDetails'][-1].get('statusDetails')

        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(sub_status),
            'substatus': sub_status,
            'estimated_date': waybill_data.get('expectedDeliveryDate'),
            'shipment_type': waybill_data.get('shipmentType'),
            'destination': waybill_data.get('destinationCity'),
            'client': waybill_data.get('merchantName'),
            'receiver_name': waybill_data.get('receiverName'),
            'receiver_relationship': waybill_data.get('receiverRelationShip')
        }
        checkpoints = []
        for scan in waybill_data.get('shipmentTrackingDetails', [])[::-1]:
            checkpoints.append(self._transform_checkpoint(scan))

        data['checkpoints'] = checkpoints

        self.data = data
        return data
