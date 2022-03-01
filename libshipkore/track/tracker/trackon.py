from requests.api import head
from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return ' '.join(el.split())

@track_registry.register('trackon')
class TrackOn(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('S/MENT BOOKED'):
            return StatusChoice.InfoReceived
        elif status.startswith('PROCESSING'):
            return StatusChoice.InTransit 
        elif status.startswith('S/MENT ARRIVED'):
            return StatusChoice.InTransit
        elif status.startswith('IN TRANSIT'):
            return StatusChoice.InTransit
        elif status.startswith('OUT FOR DELIVERY'):
            return StatusChoice.OutForDelivery
        elif 'DELIVERED' in  status:
            return StatusChoice.Delivered
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'trackon', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.post(
            'https://trackon.in/Tracking/t1/SingleTracking',
            headers= {'Referer' : 'https://trackon.in/'},
            data= {'awbSingleTrackingId': self.waybill}
            
        ).text
        # print(self.raw_data, "####")

    '''
    This method will convert self.raw_data to self.data
    '''
    def _transform(self):
        selector = parsel.Selector(text = self.raw_data)
        checkpoint_table= selector.xpath('//div[@id="divtrackStatus"]/table/tbody/tr')
        
        checkpoints= []
        checkpoint_data= []
        for rows in checkpoint_table:
            rows = rows.xpath('.//td//text()').getall()
            row = [ele.strip() for ele in rows]
            row= [ele for ele in row if ele]
            # print(row)
            if row == []:
                continue
            checkpoint_data.append(row)
            checkpoints.append(self._transform_checkpoint(row))
        
        sub_status= checkpoint_data[0][3]
        status= self.status_mapper(sub_status)
        delivered_date_time = None
        
        if status == StatusChoice.Delivered.value:
            delivered_date_time= parse(checkpoint_data[0][0])
            # if delivered_date_time:
            #     delivered_date= delivered_date_time.split()[0]
            #     delivered_time= delivered_date_time.split()[1]

        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': status,
            'substatus': sub_status,
            'estimated_date': None,
            'delivered_date' : delivered_date_time,
            'reference_no' : checkpoint_data[0][1],
            'destination' : '',
            'receiver_name': ''
        }

        data['checkpoints'] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        status = get_elem_text(scan[3])
        date = get_elem_text(scan[0])
        parsed_date = parse(date)
        location= scan[5] if len(scan) > 5 else None

        checkpoint = {
            "slug": self.provider,
            "location": location,
            "country_name": "India",
            "message": scan[2],
            "submessage": scan[2],
            "country_iso3": "IND",
            "status": self.status_mapper(status),
            "substatus": status,
            "checkpoint_time": parsed_date,
            "state": None,
            "zip": None,
        }

        return checkpoint