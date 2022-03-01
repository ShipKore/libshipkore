from re import S
from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse



def get_elem_text(el):
    if el:
        return el.strip()

@track_registry.register('dtdc')
class DTDCIndia(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if 'pick up' in status.lower():
            return StatusChoice.InfoReceived.value
        if 'softdata upload' in status.lower():
            return StatusChoice.InfoReceived.value
        if 'booked' in status.lower():
            return StatusChoice.InfoReceived.value
        elif 'booked & dispatch' in status.lower():
            return StatusChoice.InTransit.value
        elif 'in transit' in status.lower():
            return StatusChoice.InTransit.value
        elif 'received at' in status.lower():
            return StatusChoice.InTransit.value
        elif 'at destination' in status.lower():
            return StatusChoice.InTransit.value
        elif 'processed & forwarded' in status.lower():
            return StatusChoice.InTransit.value
        elif 'out for delivery' in status.lower():
            return StatusChoice.OutForDelivery.value
        elif 'delivered' in status:
            return StatusChoice.Delivered.value   
        else:
            return StatusChoice.Exception.value

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'dtdc', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'https://tracking.dtdc.com/ctbs-tracking/customerInterface.tr?submitName=showCITrackingDetails&cType=Consignment&cnNo={self.waybill}'
        ).text
        self.checkpoint_data= requests.post(
            f'https://tracking.dtdc.com/ctbs-tracking/customerInterface.tr?submitName=getLoadMovementDetails&cnNo={self.waybill}'
        ).json()
        # print(self.raw_data)
        # print(self.checkpoint_data)

    '''
    This method will convert self.raw_data to self.data
    '''

    def _transform(self):
        selector = parsel.Selector(text = self.raw_data)
        sub_status= get_elem_text(selector.xpath('//*[@id="lsSt"]/text()').get())
        if not sub_status:
            sub_status= get_elem_text(selector.xpath('//*[@id="lsSt"]/b/font/text()').get())
        delivered_date= None
        if sub_status == 'Successfully Delivered':
            delivered_date= selector.xpath('//*[@id="lstStausDt"]//text()[1]').get() + selector.xpath('//*[@id="lstStausDt"]//text()[2]').get()

        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(sub_status),
            'substatus': sub_status,
            'delivered_date' : delivered_date,
            'reference_no' : get_elem_text(selector.xpath('//*[@id="refNumber"]//text()').get()),
            'destination' : get_elem_text(selector.xpath('//*[@id="main"]/div/div/div/span[1]/div/div[3]/table[2]/tbody/tr[1]/td[4]/text()').get()),
            'receiver_name': get_elem_text(selector.xpath('//*[@id="rcverDtls"]/table/tbody/tr[1]/td[2]//text()').get())
        }
        
        checkpoints = []
        checkpoint_table = self.checkpoint_data
        # print(checkpoint_table)

        for row in checkpoint_table:
            if row == []:
                break
            checkpoints.append(self._transform_checkpoint(row))

        data['checkpoints'] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": scan.get('dest'),
            "location": scan.get('dest'),
            "country_name": "India",
            "message": scan.get('instructions'),
            "submessage": scan.get('instructions'),
            "country_iso3": "IND",
            "status": self.status_mapper(scan.get('deliveryStatus', '')),
            "substatus": scan.get('activityType'),
            "checkpoint_time": parse(scan.get('dateWithNoSuffix', '')),
            "state": None,
            "zip": None,
        }

        return checkpoint