from .common.basetrackservice import BaseTrackService
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse

def get_elem_text(el):
    if el and el.text:
        return el.text.strip()


class Ekart(BaseTrackService):
    
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Shipment Created'):
            return 'InfoReceived'
        elif status.startswith('Dispatched to'):
            return 'InTransit'
        elif status.startswith('Received at'):
            return 'InTransit'
        elif status.startswith('Out For Delivery'):
            return 'OutForDelivery'
        elif status.startswith('Delivered'):
            return 'Delivered'
        elif status.startswith('Pickup Requested'):
            return 'AvailableForPickup'
        elif status.startswith('Out For Pickup'):
            return 'AvailableForPickup'
        elif status.startswith('Picked up'):
            return 'ReverseInTransit'
        else:
            return 'Exception'


    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'delhivery', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'https://www.ekartlogistics.com/track/{self.waybill}'
        ).text
        # print(self.raw_data)

    def _transform_checkpoint(self, scan):
        status = get_elem_text(scan.find(attrs={"data-title":"Status"}))
        date = get_elem_text(scan.find(attrs={"data-title":"Date"}))+' , '+get_elem_text(scan.find(attrs={"data-title":"Time"}))+"+5:30"
        parsed_date = parse(date).isoformat()

        print (get_elem_text(scan.find(attrs={"data-title":"Status"})))

        checkpoint = {
            "slug": self.provider,
            "location": get_elem_text(scan.find(attrs={"data-title":"Place"})),
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

    '''
    This method will convert self.raw_data to self.data
    { "origin_courier_name": "Ekart", "origin_country_name": "India", "destination_country_name": "India", "scheduled_delivery_date": "{{scheduled_delivery_date}}", "waybill": "{{waybill}}", "status": "{{status}}", "state": "", "zip": ""{{#if checkpoints}}, "checkpoints": [ {{#each checkpoints}} { "slug": "ekart", "city": "{{this.city}}", "location": "{{this.location}}", "country_name": "India", "message": "{{this.message}}", "country_iso3": "IND", "status": "{{this.status}}", "checkpoint_time": "{{this.checkpoint_time}}" }{{#unless @last}},{{/unless}} {{/each}} ] {{/if}} }
    '''

    def _transform(self):
        soup = BeautifulSoup(self.raw_data, 'html.parser')
        tables = soup.find_all('div',id='no-more-tables')

        status = get_elem_text(tables[0].find("td", attrs={"data-title": "Current Status"}))
        data = {
            'waybill': self.waybill,
            'provider': self.provider,
            'status': self.status_mapper(status),
            'substatus': status,
            'estimated_date': get_elem_text(tables[0].find("td", attrs={"data-title": "Promised Delivery Date"})) or get_elem_text(tables[0].find("td", attrs={"data-title": "Delivered On"})),
            'client': soup.find(text="Merchant name :").parent.next_sibling.strip(),
            'receiverName': get_elem_text(tables[0].find("td", attrs={"data-title": "Received By"}))
        }
        checkpoints = []
        for scan in tables[1].find_all('tr')[1:]:
            checkpoints.append(self._transform_checkpoint(scan))

        data['checkpoints'] = checkpoints

        self.data = data
