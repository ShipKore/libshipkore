"""
One entry point for every provider and every operation.

    provider = get_provider("delhivery", credentials={"api_token": "..."})
    provider.capabilities        # {"track", "rates", "label", ...}
    provider.track("1234567890")
    provider.create_shipment(request)
    provider.label(shipment.waybill, shipment.reference)
"""
from libshipkore.book.base import BaseCarrier, TrackOnlyCarrier, carrier_registry
from libshipkore.common.exceptions import UnknownProvider
from libshipkore.track import ALTERNATIVE_PROVIDERS, track_registry
from libshipkore import book  # noqa: F401  (registers the carriers)


def get_provider(provider: str, credentials: dict = None,
                 sandbox: bool = False) -> BaseCarrier:
    provider = ALTERNATIVE_PROVIDERS.get(provider, provider)
    if provider in carrier_registry.keys():
        return carrier_registry.get(
            provider, credentials=credentials, sandbox=sandbox
        )
    if provider in track_registry.keys():
        return TrackOnlyCarrier(
            provider, credentials=credentials, sandbox=sandbox
        )
    raise UnknownProvider(f"unknown provider '{provider}'")


def list_providers() -> dict:
    """Every provider with the operations it supports."""
    slugs = set(carrier_registry.keys()) | set(track_registry.keys())
    return {
        slug: sorted(get_provider(slug).capabilities) for slug in sorted(slugs)
    }
