from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
from dateutil.parser import parse


@track_registry.register('saia-freight')
class SaiaLTLFrieght(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("Pickup"):
            return StatusChoice.InTransit.value
        elif status.startswith('In Transit'):
            return StatusChoice.InTransit.value
        elif status.startswith('Depart from'):
            return StatusChoice.InTransit.value
        elif "arrived at" in status.lower():
            return StatusChoice.InTransit.value
        elif "pickup" in status.lower():
            return StatusChoice.AvailableForPickup.value
        elif status.startswith("Unload Trailer"):
            return StatusChoice.InTransit.value
        elif status.startswith("Load Trailer"):
            return StatusChoice.InTransit.value
        elif status.startswith('Delivery Appointment'):
            return StatusChoice.InTransit.value
        elif status.startswith('Departed from'):
            return StatusChoice.InTransit.value
        elif "delivery" in status.lower():
            return StatusChoice.OutForDelivery.value
        elif status.startswith('Your package has been delivered'):
            return StatusChoice.Delivered.value
        elif 'Delivered' in status:
            return StatusChoice.Delivered.value
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'saia-freight', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'https://www.saia.com/api/v1/tracking/find-full-details?proNumber={self.waybill}'
        ).json()
        # print(self.raw_data)

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": scan.get('city'),
            "location": scan.get('scannedLocation'),
            "country_name": "United States",
            "message": scan.get('activity'),
            "submessage": '',
            "country_iso3": "US",
            "status": self.status_mapper(scan.get('activity', '')),
            "substatus": scan.get('activity'),
            "checkpoint_time": parse(scan.get('date', '') +' '+ scan.get('time', '')),
            "state": scan.get('state', ''),
            "zip": None,
        }

        return checkpoint

    '''
    This method will convert self.raw_data to self.data
    '''

    def _transform(self):
        waybill_data = self.raw_data
        print (waybill_data.get('deliveryInformation', {}).get('expectedDeliveryDate'))
        deliveryInformation = waybill_data.get('deliveryInformation', {})
        estimated_date = deliveryInformation.get('deliveryDate') or deliveryInformation.get('expectedDeliveryDate')
        estimated_time = deliveryInformation.get('deliveryTime') or deliveryInformation.get('expectedDeliveryTime')
        estimated_time = estimated_time.get('to')
        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(waybill_data.get('shipmentInformation', {}).get('status', '')),
            'substatus': waybill_data.get('shipmentInformation', {}).get('status', ''),
            'estimated_date': parse(estimated_date +' '+ estimated_time),
            'reference_no': '',
            'package_type': waybill_data.get('shipmentInformation', {}).get('type', ''),
            'destination': waybill_data.get('consignee', {}).get('city', ''),
            'client': waybill_data.get('consignee', {}).get('name', ''),
            'consignee_address': waybill_data.get('addressLine1'),
            'product': '',
            'receiver_name': waybill_data.get('consignee', {}).get('name'),
        }
        checkpoints = []
        for scan in waybill_data.get('history', []):
            checkpoints.append(self._transform_checkpoint(scan))

        data['checkpoints'] = checkpoints

        self.data = data
        return data
