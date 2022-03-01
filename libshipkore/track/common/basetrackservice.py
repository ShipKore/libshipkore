from libshipkore.common.baseservice import BaseService
from class_registry import ClassRegistry
from ..models.model import Track

track_registry = ClassRegistry()


class BaseTrackService(BaseService):
    def _get_data(self):
        return self.__data

    def _set_data(self, value):
        self.__data = Track(**value) if value else None

    data = property(_get_data, _set_data)

    def __init__(self, waybill, provider, *args, **kwargs):
        super().__init__(waybill, provider, *args, **kwargs)
        self.waybill = waybill
        self.provider = provider

    def _fetch(self):
        raise NotImplementedError

    def _transform(self):
        raise NotImplementedError

    def _save(self):
        pass

    def get(self):
        raise NotImplementedError
