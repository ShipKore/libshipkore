from .common.basetrackservice import track_registry
from .tracker import apc  # noqa: F401

ALTERNATIVE_PROVIDERS = {
    "globegistics": "asendia",
}


def get_track_data(provider: str, waybill: str) -> object:
    if provider in ALTERNATIVE_PROVIDERS:
        provider = ALTERNATIVE_PROVIDERS[provider]

    provider_obj = track_registry.get(provider, waybill)
    return provider_obj.run()


def get_providers() -> list:

    return list(track_registry.keys())
