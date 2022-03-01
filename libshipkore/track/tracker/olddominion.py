from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return ' '.join(el.split())

@track_registry.register('olddominion-freightline')
class OldDominionFreightLine(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Shipment Pickup'):
            return StatusChoice.InfoReceived.value
        elif status.startswith('In Transit'):
            return StatusChoice.InTransit.value
        elif status.startswith('Out For Delivery'):
            return StatusChoice.OutForDelivery.value
        elif status.startswith('Delivered'):
            return StatusChoice.Delivered.value
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'olddominion-freightline', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'https://www.odfl.com/Trace/standardResult.faces?pro={self.waybill}'
        ).text

    '''
    This method will convert self.raw_data to self.data
    '''
    def _transform(self):
        selector = parsel.Selector(text = self.raw_data)
        
        rows = selector.css('#traceResult\:detailedTrView fieldset .trRow.row')
        data_dict = {}
        for row in rows:
            if len(row.css('div').getall())!=3:
                continue
            
            key = row.css('div')[1].css('label::text').get().strip()
            value = row.css('div')[2].css('::text').get().strip()
            data_dict[key] = value
                
        
        
        sub_status= data_dict.get('Status')
        status= self.status_mapper(sub_status)
        delivered_date= None
        if status == StatusChoice.Delivered.value:
            delivered_date = parse(data_dict.get('Delivery Date (Estimated)'))
        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': status,
            'substatus': sub_status,
            'estimated_date': parse(data_dict.get('Delivery Date (Estimated)')),
            'delivered_date' : delivered_date,
            'reference_no' : '',
            'destination' : data_dict.get('Destination'),
            'receiver_name': '',
            'consignee_address': data_dict.get('Destination'),
            'checkpoints': []
        }

        self.data = data