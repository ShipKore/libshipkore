from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice
import parsel


def get_elem_text(el):
    if el and el.text:
        return el.text.strip()

@track_registry.register('professional-couriers')
class ProfessionalCouriers(BaseTrackService):
    def status_mapper(self, status):
        """
        docstring
        """
        if status.startswith('Bag Dispatched'):
            return 'InTransit'
        elif status.startswith('Dispatched'):
            return 'InTransit'
        elif status.startswith('Received'):
            return 'InTransit'
        elif status.startswith('Delivered'):
            return 'Delivered'
        else:
            return 'Exception'

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, 'professional_couriers', *args, **kwargs)

    '''
    This method will populate self.raw_data
    '''
    def _fetch(self):
        self.raw_data = requests.get(
            f'https://tpcglobe.com/track-info.aspx?id={self.waybill}'
        ).text
        print(self.raw_data)

    '''
    This method will convert self.raw_data to self.data
    '''