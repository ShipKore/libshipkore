"""Tests for the unified provider interface."""

import pytest

from libshipkore import provider as provider_module
from libshipkore.book.base import BaseCarrier, OPERATIONS, TrackOnlyCarrier
from libshipkore.common.exceptions import UnknownProvider, UnsupportedOperation
from libshipkore.provider import get_provider, list_providers


def test_booking_carrier_exposes_every_operation_it_implements():
    delhivery = get_provider("delhivery", credentials={"api_token": "t"})
    assert delhivery.capabilities == {
        "track", "serviceability", "services", "rates", "create_shipment",
        "label", "cancel", "schedule_pickup", "ndr_action", "ndr_status",
    }


def test_capabilities_reflect_what_is_implemented():
    shiprocket = get_provider("shiprocket")
    assert shiprocket.capabilities == {
        "serviceability", "rates", "create_shipment", "label", "cancel",
        "schedule_pickup",
    }


def test_tracking_only_provider_uses_the_same_interface():
    dtdc = get_provider("dtdc")
    assert isinstance(dtdc, TrackOnlyCarrier) and isinstance(dtdc, BaseCarrier)
    assert dtdc.provider == "dtdc"
    assert dtdc.capabilities == {"track"}
    with pytest.raises(UnsupportedOperation):
        dtdc.create_shipment(None)


def test_alias_resolves_like_track():
    assert get_provider("globegistics").provider == "asendia-usa"


def test_unknown_provider():
    with pytest.raises(UnknownProvider) as error:
        get_provider("nope-at-all")
    assert "Did you mean" not in str(error.value)  # nothing is close


def test_a_mistyped_provider_is_corrected_in_the_error_itself():
    with pytest.raises(UnknownProvider, match=r"unknown provider 'delhivry'\. Did you mean delhivery\?"):
        get_provider("delhivry")
    with pytest.raises(UnknownProvider, match="shiprocket"):
        get_provider("shiprockt")
    with pytest.raises(UnknownProvider, match="globegistics"):  # aliases are offered too
        get_provider("globegistic")


def test_every_registered_provider_has_one_consistent_surface():
    listing = list_providers()
    assert {"delhivery", "shiprocket", "dtdc", "fedex"} <= set(listing)
    for slug, capabilities in listing.items():
        assert capabilities, slug
        assert set(capabilities) <= set(OPERATIONS), slug
        provider = get_provider(slug)
        for operation in OPERATIONS:
            assert callable(getattr(provider, operation)), (slug, operation)


MINIMAL_ARGS = {
    "track": ("1",),
    "serviceability": ("1",),
    "services": (),
    "rates": ("1", "2", None, None),
    "create_shipment": (None,),
    "label": ("1",),
    "cancel": ("1",),
    "schedule_pickup": (None,),
    "ndr_action": (None,),
    "ndr_status": ("1",),
}


def test_unsupported_operations_are_exactly_the_missing_capabilities():
    assert set(MINIMAL_ARGS) == set(OPERATIONS)
    for slug in ("delhivery", "shiprocket", "dtdc"):
        provider = get_provider(slug)
        for operation in set(OPERATIONS) - provider.capabilities:
            with pytest.raises(UnsupportedOperation):
                getattr(provider, operation)(*MINIMAL_ARGS[operation])


def test_track_goes_through_the_shared_tracker(monkeypatch):
    import libshipkore.book.base as base

    calls = []
    monkeypatch.setattr(
        base, "get_track_data", lambda slug, waybill: calls.append((slug, waybill)) or "T"
    )
    assert get_provider("delhivery").track("123") == "T"
    assert get_provider("dtdc").track("456") == "T"
    assert calls == [("delhivery", "123"), ("dtdc", "456")]


def test_provider_reexported_from_main_module():
    from libshipkore import libshipkore_base

    assert libshipkore_base.get_provider is provider_module.get_provider
