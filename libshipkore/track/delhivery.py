from .common.basetrackservice import BaseTrackService
import requests


class Delhivery(BaseTrackService):
    STATUS_MAPPER = {
        '': 'Pending',
        'WAITING_PICKUP': 'InfoReceived',
        'IN_TRANSIT': 'InTransit',
        'REACHED_DEST_CITY': 'InTransit',
        'OUT_DELIVERY': 'OutForDelivery',
        '': 'AttemptFail',
        'DELIVERED': 'Delivered',
        'WAITING_SELF_COLLECT': 'AvailableForPickup',
        'LOST': 'Exception',
        '': 'Expired',
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
            "checkpoint_time": scan.get('scanDateTime','')+'+05:30',
            "state": None,
            "zip": None,
        }


        return checkpoint

    '''
    This method will convert self.raw_data to self.data
    { {{#with data.[0]}} "checkpoints": [ {{#each scans }} { "slug": "delhivery", "city": "scan.cityLocation}}", "location": "scan.scannedLocation}}", "country_name": "IND", "message": "scan.instructions}}", "country_iso3": "IND", "status": "scan.status}}", "checkpoint_time": "scan.scanDateTime}}+05:30", "state": null, "zip": null }{{#unless @last}},{{/unless}} {{/each}} ], "origin_country_name":"India", "destination_country_name":"India", "scheduled_delivery_date": "{{estimatedDate}}", "waybill": "", "status": "{{hqStatus}}", "origin_courier_name": "Delhivery", "shipment_type": "{{productType}}" {{/with}} }
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
            'receiverName': '',
            'trackStatus': 'DONE'
        }
        checkpoints = []
        for scan in waybill_data.get('scans', []):
            checkpoints.append(self._transform_checkpoint(scan))

        data['checkpoints'] = checkpoints

        self.data = data
        return data
