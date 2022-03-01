from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import json


@track_registry.register('fedex')
class FedEx(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Shipment information sent'):
            return StatusChoice.InfoReceived
        elif status.startswith('Picked up'):
            return StatusChoice.InTransit
        elif status.startswith('At FedEx'):
            return StatusChoice.InTransit
        elif status.startswith('Left FedEx'):
            return StatusChoice.InTransit
        elif status.startswith('International shipment release'):
            return StatusChoice.InTransit
        elif status.startswith('Operational Delay'):
            return StatusChoice.InTransit
        elif status.startswith('At local FedEx'):
            return StatusChoice.InTransit
        elif status.startswith('In transit'):
            return StatusChoice.InTransit
        elif status.startswith('Arrived at FedEx'):
            return StatusChoice.InTransit
        elif status.startswith('Departed FedEx'):
            return StatusChoice.InTransit
        elif status.startswith('On FedEx vehicle for delivery'):
            return StatusChoice.OutForDelivery
        elif 'Delivered' in status:
            return StatusChoice.Delivered
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'fedex', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''

    def _fetch(self):
        data = {
            "data": json.dumps({
                "TrackPackagesRequest": {
                    "trackingInfoList": [
                        {
                            "trackNumberInfo": {
                                "trackingNumber": self.waybill
                            }
                        }
                    ]
                }
            }),
            "action": 'trackpackages',
            'locale':'en_US',
            'version':1,
            'format':'json'
        }
        print(data)
        self.raw_data = requests.post(
            'https://api.fedex.com/track/v2/shipments',
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            # data=f"data=%7B%22TrackPackagesRequest%22%3A%7B%22appType%22%3A%22WTRK%22%2C%22appDeviceType%22%3A%22DESKTOP%22%2C%22supportHTML%22%3Atrue%2C%22supportCurrentLocation%22%3Atrue%2C%22uniqueKey%22%3A%22%22%2C%22processingParameters%22%3A%7B%7D%2C%22trackingInfoList%22%3A%5B%7B%22trackNumberInfo%22%3A%7B%22trackingNumber%22%3A%22{self.waybill}%22%2C%22trackingQualifier%22%3A%22%22%2C%22trackingCarrier%22%3A%22%22%7D%7D%5D%7D%7D&action=trackpackages&locale=en_US&version=1&format=json",

            data=data,
        ).json()
        # print(self.raw_data)

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": scan.get('scanLocation'),
            "location": scan.get('scanLocation'),
            "country_name": "",
            "message": scan.get('scanDetails'),
            "submessage": scan.get('scanDetails'),
            "country_iso3": "",
            "status": self.status_mapper(scan.get('status', '')),
            "substatus": scan.get('status'),
            "checkpoint_time": str(scan.get('date', '') + 'T' + scan.get('time', '') + scan.get('gmtOffset', '')),
            "state": None,
            "zip": None,
        }

        return checkpoint

    '''
    This method will convert self.raw_data to self.data
    '''

    def _transform(self):
        waybill_data = self.raw_data.get('TrackPackagesResponse', {}).get('packageList', [{}])[0]
        # print(waybill_data)
        print(waybill_data.get('keyStatus', None), "#######")
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(waybill_data.get('keyStatus', None)),
            'substatus': waybill_data.get('keyStatus', None),
            'estimated_date': waybill_data.get('estDeliveryDt'),
            'reference_no': waybill_data.get('trackingQualifier'),
            'package_type': waybill_data.get('packageType'),
            'destination': waybill_data.get('destLocationAddr1'),
            'client': waybill_data.get('clientName'),
            'consignee_address': waybill_data.get('consigneeAddress'),
            'product': waybill_data.get('productName'),
            'receiver_name': waybill_data.get('recipientName'),
        }
        checkpoints = []
        for scan in waybill_data.get('scanEventList', []):
            checkpoints.append(self._transform_checkpoint(scan))

        data['checkpoints'] = checkpoints

        self.data = data
        return data
