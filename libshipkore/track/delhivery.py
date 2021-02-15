from .common.basetrackservice import BaseTrackService
import requests


class Delhivery(BaseTrackService):
    STATUS_MAPPER = {
        'WAITING_PICKUP': 'InfoReceived',
        'IN_TRANSIT': 'InTransit',
        'REACHED_DEST_CITY': 'InTransit',
        'OUT_DELIVERY': 'OutForDelivery',
        'DELIVERED': 'Delivered',
        'WAITING_SELF_COLLECT': 'AvailableForPickup',
        'LOST': 'Exception',
        'DELIVERED_SELLER': 'ReverseDelivered',
        'OUT_DELIVERY_SELLER': 'ReverseOutForDelivery',
        'PROD_REPLACED': 'ReverseInTransit',
        'REVERSAL_REACHED_SEL_CITY': 'ReverseInTransit',
    }

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'delhivery', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'https://dlv-api.delhivery.com/v2/track?waybillId={self.waybill}'
        ).json()
        # print(self.raw_data)

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": scan.get('cityLocation'),
            "location": scan.get('scannedLocation'),
            "country_name": "India",
            "message": scan.get('instructions'),
            "submessage": scan.get('instructions'),
            "country_iso3": "IND",
            "status": Delhivery.STATUS_MAPPER.get(scan.get('status', '')),
            "substatus": scan.get('status'),
            "checkpoint_time": scan.get('scanDateTime', '') + '+05:30',
            "state": None,
            "zip": None,
        }

        return checkpoint

    '''
    This method will convert self.raw_data to self.data
    '''

    def _transform(self):
        waybill_data = self.raw_data.get('data', [{}])[0]
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': Delhivery.STATUS_MAPPER.get(waybill_data.get('status', {}).get('status', '')),
            'substatus': waybill_data.get('status', {}).get('status', ''),
            'estimated_date': waybill_data.get('estimatedDate'),
            'reference_no': waybill_data.get('referenceNo'),
            'package_type': waybill_data.get('packageType'),
            'destination': waybill_data.get('destination'),
            'client': waybill_data.get('clientName'),
            'consignee_address': waybill_data.get('consigneeAddress'),
            'product': waybill_data.get('productName'),
            'receiverName': '',
        }
        checkpoints = []
        for scan in waybill_data.get('scans', []):
            checkpoints.append(self._transform_checkpoint(scan))

        data['checkpoints'] = checkpoints

        self.data = data
        return data
