from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return ' '.join(el.split())

@track_registry.register('gati-kwe')
class GatiKWE(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Shipment Created'):
            return StatusChoice.InfoReceived.value
        elif status.startswith('Shipment Forwarded'):
            return StatusChoice.InTransit.value
        elif status.startswith('Out For Delivery'):
            return StatusChoice.OutForDelivery.value
        elif status.startswith('Shipment Reached @ Delivery Center'):
            return StatusChoice.Delivered.value
        elif 'shipment' in status.lower():
            return StatusChoice.InTransit.value
        elif 'departed' in status.lower():
            return StatusChoice.InTransit.value
        elif 'received' in status.lower():
            return StatusChoice.InTransit.value
        elif 'out for next' in status.lower():
            return StatusChoice.InTransit.value
        elif status.startswith('Shipment Reached'):
            return StatusChoice.InTransit.value
        elif 'in transit' in status.lower():
            return StatusChoice.InTransit.value
        elif 'delivered' in status.lower():
            return StatusChoice.Delivered.value
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'gati-kwe', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.post(
            'https://www.gatikwe.com/OurTrack/DktTrack.php',
            data= {'status' : 'status_docket', 'track1' : 'Submit', 'docket_id' : f'{self.waybill}'},
            verify=False
        ).text
        # print(self.raw_data, "####")

    '''
    This method will convert self.raw_data to self.data
    '''
    def _transform(self):
        selector = parsel.Selector(text = self.raw_data)
        
        sub_status = selector.css('.status-heading::text').get().strip()
        status= self.status_mapper(sub_status)
        reciever_name= selector.xpath(f'//*[@id="docketDetails-{self.waybill}"]/div/ul/li[4]/div/div/p/text()[2]').get()
        if reciever_name:
            reciever_name= reciever_name.split(': ')[1].strip()
        delivery_date= None
        delivery_time= None
        if status == StatusChoice.Delivered.value:
            delivery_date= selector.xpath(f'//*[@id="docketDetails-{self.waybill}"]/div/ul/li[4]/div/div/p//text()').get().strip().split()[1].split(',')[0]
            delivery_time= selector.xpath(f'//*[@id="docketDetails-{self.waybill}"]/div/ul/li[4]/div/div/p//text()').get().strip().split()[2]
        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': status,
            'substatus': sub_status,
            'estimated_date': None,
            'delivered_date' : delivery_date,
            'delivered_time' : delivery_time,
            'reference_no' : '',
            'package_type' : '',
            'destination' : selector.xpath(f'//*[@id="dataSurface-217552432"]/td[4]//text()').get(),
            'receiver_name': reciever_name
        }
        checkpoints = []

        checkpoint_table = selector.xpath(f'//*[@id="dkt-table-{self.waybill}"]/tr')
        # print(checkpoint_table)

        for rows in checkpoint_table:
            rows = rows.xpath('.//td//text()').getall()
            row = [ele.strip() for ele in rows]
            row= [ele for ele in row if ele]
            if row == []:
                continue
            checkpoints.append(self._transform_checkpoint(row))

        data['checkpoints'] = checkpoints

        self.data = data

    
    def _transform_checkpoint(self, scan):
        status = get_elem_text(scan[3])
        date = get_elem_text(scan[0])
        parsed_date = parse(date)

        checkpoint = {
            "slug": self.provider,
            "location": scan[2],
            "country_name": "",
            "message": status,
            "submessage": status,
            "country_iso3": "",
            "status": self.status_mapper(status),
            "substatus": status,
            "checkpoint_time": parsed_date,
            "state": None,
            "zip": None,
        }

        return checkpoint
