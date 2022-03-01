from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel
from dateutil.parser import parse


def get_elem_text(el):
    if el:
        el = el.strip()
        return ' '.join(el.split())

@track_registry.register('bluedart')
class Bluedart(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Shipment Created'):
            return StatusChoice.InfoReceived.value
        elif status.startswith('In Transit'):
            return StatusChoice.InTransit.value
        elif status.startswith('Out For Delivery'):
            return StatusChoice.OutForDelivery.value
        elif status.startswith('Shipment Delivered'):
            return StatusChoice.Delivered.value
        elif status == 'Shipment Out For Delivery':
            return StatusChoice.OutForDelivery.value
        elif status == 'Shipment Arrived':
            return StatusChoice.InTransit.value
        elif status == 'Shipment Further Connected':
            return StatusChoice.InTransit.value
        elif status == 'Shipment Arrived At Hub':
            return StatusChoice.InTransit.value
        elif status == 'Shipment Picked Up':
            return StatusChoice.InTransit.value
        elif status == 'Online Shipment Booked':
            return StatusChoice.InfoReceived.value
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'bluedart', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'http://bluedart.in/?{self.waybill}'
        ).text
        # print(self.raw_data, "####")

    '''
    This method will convert self.raw_data to self.data
    '''
    def _transform(self):
        selector = parsel.Selector(text = self.raw_data)
        keys = selector.xpath(f'//*[@id="SHIP{self.waybill}"]/div[1]/table/tbody/tr/th/text()').getall()
        selector.xpath(f'//*[@id="SHIP{self.waybill}"]/div[1]/table/tbody/tr/td/img').remove()
        values = selector.xpath(f'//*[@id="SHIP{self.waybill}"]/div[1]/table/tbody/tr/td/text()').getall()
        data = {get_elem_text(keys[i]): get_elem_text(values[i]) for i in range(len(keys))}
        # print(data)
        
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(data['Status']),
            'substatus': data['Status'],
            'estimated_date': parse(data.get('Expected Date of Delivery'), ''),
            'delivered_date' : data.get('Date of Delivery'),
            'delivered_time' : data.get('Time of Delivery'),
            'reference_no' : data.get('Reference No'),
            'destination' : data.get('To'),
            'receiver_name': data.get('Recipient')
        }
        checkpoints = []
        # //*[@id="SCAN75413355371"]/div/table/tbody/tr[1]/td[1]
        # print(selector.xpath(f'//*[@id="SCAN{self.waybill}"]/div/table/tbody/tr//text()').getall())
        selector.xpath(f'//*[@id="SCAN{self.waybill}"]/div/table/tbody//tr/td[@align="right"]').remove()

        checkpoint_table = selector.xpath(f'//*[@id="SCAN{self.waybill}"]/div/table/tbody')
        # for rows in checkpoint_table.xpath('.//tr'):
        #     # for td in rows.xpath('.//td'):
        #     #     print(td. xpath('.//text()').get())
        #     print(rows.xpath('.//td//text()').getall())

        for rows in checkpoint_table.xpath('.//tr'):
            row = rows.xpath('.//td//text()').getall()
            if row == []:
                break
            checkpoints.append(self._transform_checkpoint(row))

        data['checkpoints'] = checkpoints

        self.data = data

    def _transform_checkpoint(self, scan):
        status = get_elem_text(scan[1])
        date = get_elem_text(scan[2])
        parsed_date = parse(date)

        checkpoint = {
            "slug": self.provider,
            "location": scan[0],
            "country_name": "India",
            "message": status,
            "submessage": status,
            "country_iso3": "IND",
            "status": self.status_mapper(status),
            "substatus": status,
            "checkpoint_time": parsed_date,
            "state": None,
            "zip": None,
        }

        return checkpoint