from libshipkore.common.baseservice import BaseService
# from geopy.geocoders import Nominatim


class BaseTrackService(BaseService):
    # geolocator = Nominatim(user_agent="shipkore")

    def __init__(self, waybill, provider, *args, **kwargs):
        super().__init__(waybill, provider, *args, **kwargs)
        self.waybill = waybill
        self.provider = provider

    def _transform(self):
        raise NotImplementedError

    def _save(self):
        pass

    def get(self):
        raise NotImplementedError
