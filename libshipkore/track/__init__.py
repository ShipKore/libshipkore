from .delhivery import Delhivery
from .ekart import Ekart


def get_track_data(provider: str, waybill: str) -> object:

    providers = {
        "delhivery": Delhivery,
        "ekart": Ekart,
    }

    provider_obj = providers[provider](waybill)
    return provider_obj.run()
