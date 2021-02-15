from .delhivery import Delhivery
from .ekart import Ekart

PROVIDERS = {
    "delhivery": Delhivery,
    "ekart": Ekart,
}


def get_track_data(provider: str, waybill: str) -> object:
    provider_obj = PROVIDERS[provider](waybill)
    return provider_obj.run()


def get_providers() -> list:
    return list(PROVIDERS.keys())
