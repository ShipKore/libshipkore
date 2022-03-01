from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import base64

@track_registry.register('pilotfrieght')
class PilotFreight(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith("SHIPMENT INFORMATION SENT TO PILOT"):
            return StatusChoice.InfoReceived.value
        elif status.startswith('WAITING FOR PICKUP'):
            return StatusChoice.InfoReceived.value
        elif status.startswith('DRIVER DISPATCHED'):
            return StatusChoice.InTransit.value
        elif status.startswith("PICKED UP"):
            return StatusChoice.InTransit.value
        elif status.startswith("TENDERED TO CARRIER"):
            return StatusChoice.InTransit.value
        elif "appointment" in status.lower():
            return StatusChoice.InTransit.value
        elif "in transit" in status.lower():
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
        super().__init__(waybill, 'pilotfreight', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        waybill_encoded= (base64.b64encode(self.waybill.encode("ascii"))).decode("ascii")
        self.raw_data = requests.get(
            f'https://wwwapi.pilotdelivers.com/track/{waybill_encoded}/orgzip/0/dstzip/0/custnum/0'
        ).json()
        # print(self.raw_data)

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": scan.get('EventLocation',{}).get('City'),
            "location": scan.get('EventLocation',{}).get('StateProvince'),
            "country_name": "",
            "message": '',
            "submessage": '',
            "country_iso3": "",
            "status": self.status_mapper(scan.get('EventCodeDesc', '')),
            "substatus": scan.get('EventCodeDesc'),
            "checkpoint_time": scan.get('EventDateTime', ''),
            "state": None,
            "zip": None,
        }

        return checkpoint

    '''
    This method will convert self.raw_data to self.data
    '''

    def _transform(self):
        waybill_data = self.raw_data.get('TrackingResponse', [{}])[0].get('TrackingInfo',{})
        checkpoints = []
        checkpoint_data = waybill_data.get('TrackingEventHistory',[{}])
        for scan in checkpoint_data:
            checkpoints.append(self._transform_checkpoint(scan))

        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(checkpoint_data[0].get('EventCodeDesc')),
            'substatus': checkpoint_data[0].get('EventCodeDesc'),
            'estimated_date': waybill_data.get('EstimateDelvDate'),
            'reference_no': '',
            'package_type': '',
            'destination': '',
            'client': '',
            'consignee_address': waybill_data.get('PackageConsignee',{}).get('Address'),
            'product': waybill_data.get('Product'),
            'receiver_name': '',
        }
        

        data['checkpoints'] = checkpoints

        self.data = data
        return data
