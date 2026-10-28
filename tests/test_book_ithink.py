"""iThink tracking, against the response shape in iThink's Track Order V3 page."""

import pytest
import responses

from libshipkore.book import get_carrier
from libshipkore.common.exceptions import CredentialsError, ProviderError, UnsupportedOperation

API = "https://api.ithinklogistics.com/api_v3/order/track.json"
CREDENTIALS = {"access_token": "tok", "secret_key": "sec"}


def entry(status="In Transit", scans=None, **extra):
    return {"message": "success", "awb_no": "1369010468790", "current_status": status,
            "expected_delivery_date": "2026-05-04",
            "order_details": {"order_number": "ORD-1"},
            "order_date_time": {"delivery_date": "0000-00-00 00:00:00"},
            "scan_details": scans if scans is not None else [
                {"status": "Manifested", "scan_location": "Delhi", "remark": "created",
                 "scan_date_time": "2026-05-01 10:00:00", "status_reason": ""},
                {"status": "In Transit", "scan_location": "Jaipur", "remark": "moving",
                 "scan_date_time": "2026-05-02 09:30:00", "status_reason": "bag"},
            ], **extra}


@pytest.fixture
def carrier():
    return get_carrier("ithink", credentials=CREDENTIALS)


@responses.activate
def test_track_maps_the_documented_response(carrier):
    responses.add(responses.POST, API, json={"status_code": 200, "data": {"1369010468790": entry()}})
    track = carrier.track("1369010468790")
    assert track.status.value == "InTransit" and track.reference_no == "ORD-1"
    assert [c.message for c in track.checkpoints] == ["moving", "created"]  # newest first
    assert track.checkpoints[0].checkpoint_time.isoformat() == "2026-05-02T09:30:00+05:30"
    assert track.delivered_date is None  # the all-zero date means not yet
    body = responses.calls[0].request.body
    assert b'"awb_number_list": "1369010468790"' in body and b'"access_token": "tok"' in body


@pytest.mark.parametrize("status,expected", [
    ("Delivered", "Delivered"), ("Undelivered", "AttemptFail"), ("RTO Delivered", "ReverseDelivered"),
    ("Lost", "Exception"), ("Out For Delivery", "OutForDelivery"),
])
@responses.activate
def test_status_names_map_to_the_shared_ones(carrier, status, expected):
    responses.add(responses.POST, API, json={"data": {"1": entry(status)}})
    assert carrier.track("1").status.value == expected


@responses.activate
def test_an_unknown_awb_is_a_provider_error(carrier):
    responses.add(responses.POST, API, json={"data": {"1": {"message": "AWB not found"}}})
    with pytest.raises(ProviderError, match="AWB not found"):
        carrier.track("1")


@responses.activate
def test_sandbox_uses_the_pre_alpha_host():
    responses.add(responses.POST, "https://pre-alpha.ithinklogistics.com/api_v3/order/track.json",
                  json={"data": {"1": entry()}})
    assert get_carrier("ithink", credentials=CREDENTIALS, sandbox=True).track("1").waybill == "1"


def test_credentials_are_required_and_nothing_else_is_claimed():
    with pytest.raises(CredentialsError, match="access_token"):
        get_carrier("ithink").track("1")
    carrier = get_carrier("ithink", credentials=CREDENTIALS)
    assert carrier.capabilities == {"track"}
    with pytest.raises(UnsupportedOperation):
        carrier.create_shipment(None)
