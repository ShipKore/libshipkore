from common.baseservice import BaseService
# from geopy.geocoders import Nominatim

class BaseTrackService(BaseService):
    # geolocator = Nominatim(user_agent="shipkore")

    def __init__(self, waybill, provider, *args, **kwargs):
        super().__init__(waybill, provider, *args, **kwargs)
        self.waybill = waybill
        self.provider = provider

    def _transform(self):
        # with open(f"services/transforms/{provider}.jsonnet") as f:
        #     self.data = transform(f.read(), self.raw_data)
        raise NotImplementedError

    def _save(self):
        # track = Track(**self.data)
        # fire_db = Firebase()
        # fire_db.save('Track', track)
        pass

    def get(self):
        # fire_db = Firebase()
        # return fire_db.get('Track', f'{self.provider}_{self.waybill}')
        raise NotImplementedError
