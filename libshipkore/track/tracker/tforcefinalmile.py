from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return ' '.join(el.split())

@track_registry.register('tforcefinalmile')
class TForceFinalMile(BaseTrackService):
    checkpoint_time = None
    
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Manifested By Shipper'):
            return StatusChoice.InfoReceived.value
        elif status.startswith('Received'):
            return StatusChoice.InTransit.value
        elif status.startswith('Delivery'):
            return StatusChoice.InTransit.value
        elif status.startswith('Out For Delivery'):
            return StatusChoice.OutForDelivery.value
        elif status.startswith('Shipment Delivered'):
            return StatusChoice.Delivered.value
        elif 'delivered' in status.lower():
            return StatusChoice.Delivered.value
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'tforcefinalmile', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'https://direct.tfesg.com/finalmiletrack/Track?trackingNumber={self.waybill}'
        ).text
        # print(self.raw_data, "####")

    '''
    This method will convert self.raw_data to self.data
    '''
    def _transform(self):
        selector = parsel.Selector(text = self.raw_data)
        destination_data = selector.xpath('//*[@id="trackingContent"]/div[2]/div/div[1]/div[2]/text()').getall()
        destination_data= [ele.strip() for ele in destination_data if ele]
        destination_data = [ele for ele in destination_data if ele]
        dest = ""
        for ele in destination_data[0].split():
            if ele:
                dest = dest + ele.strip()
        checkpoint_table = selector.xpath('//*[@id="trackingContent"]//div[@class="row listable"]')

        checkpoints = []
        checkpoint_data= []
        for rows in checkpoint_table:
            cols = rows.xpath('./div/span/text()').getall()
            checkpoints.append(self._transform_checkpoint(cols))
            checkpoint_data.append(cols)
        
        sub_status= checkpoint_data[0][0]
        status= self.status_mapper(sub_status)
        delivered_date= None
        if status == StatusChoice.Delivered.value:
            delivered_date = parse(checkpoint_data[0][1])
        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': status,
            'substatus': sub_status,
            'estimated_date': None,
            'delivered_date' : delivered_date,
            'reference_no' : '',
            'destination' : dest,
            'receiver_name': ''
        }
        data['checkpoints'] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        checkpoint_time = None
        try:
            checkpoint_time = parse(scan[1])
            self.checkpoint_time = checkpoint_time
        except:
            checkpoint_time = self.checkpoint_time
                
        checkpoint = {
            "slug": self.provider,
            "location": scan[2] if len(scan) == 3 else None,
            "country_name": "United States",
            "message": '',
            "submessage": '',
            "country_iso3": "US",
            "status": self.status_mapper(scan[0]),
            "substatus": scan[0],
            "checkpoint_time": checkpoint_time,
            "state": None,
            "zip": None,
        }

        return checkpoint