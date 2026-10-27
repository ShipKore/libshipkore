from .base import carrier_registry
from . import carriers  # noqa: F401


def get_carrier(provider: str, credentials: dict = None, sandbox: bool = False):
    return carrier_registry.get(provider, credentials=credentials, sandbox=sandbox)


def get_carriers() -> list:
    return list(carrier_registry.keys())
