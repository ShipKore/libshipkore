"""Tests for the Delhivery booking client, against canned responses."""

import json
import os
from datetime import date, time
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from libshipkore.book import get_carrier, get_carriers
from libshipkore.book.base import BaseCarrier
from libshipkore.book.models import (
    Address,
    NdrAction,
    NdrRequest,
    Parcel,
    PaymentMode,
    PickupRequest,
    RequestStatus,
    ShipmentRequest,
)
from libshipkore.common.exceptions import (
    CredentialsError,
    ProviderError,
    UnsupportedOperation,
)

PROD = "https://track.delhivery.com"
STAGING = "https://staging-express.delhivery.com"

with open(os.path.join(os.path.dirname(__file__), "fixtures", "delhivery.json")) as f:
    FIXTURES = json.load(f)


@pytest.fixture
def carrier():
    return get_carrier("delhivery", credentials={"api_token": "tok"})


@pytest.fixture
def shipment_request():
    return ShipmentRequest(
        order_id="ORD-1",
        consignee=Address(
            name="Asha", phone="9876543210", address="12 MG Road",
            pincode="560001", city="Bengaluru", state="Karnataka",
        ),
        pickup_location="Main Warehouse",
        parcel=Parcel(weight_kg=1.5, length_cm=10, breadth_cm=10, height_cm=5),
        payment_mode=PaymentMode.COD,
        cod_amount=999,
        declared_value=999,
        description="Shirt",
    )


def test_registered():
    assert "delhivery" in get_carriers()


def test_missing_credentials_raises():
    with pytest.raises(CredentialsError):
        get_carrier("delhivery").serviceability("110001")


def test_sandbox_uses_staging_host():
    carrier = get_carrier(
        "delhivery", credentials={"api_token": "tok"}, sandbox=True
    )
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET, STAGING + "/c/api/pin-codes/json/",
            json=FIXTURES["serviceability_none"],
        )
        carrier.serviceability("110001")


@responses.activate
def test_auth_header_sent(carrier):
    responses.add(
        responses.GET, PROD + "/c/api/pin-codes/json/",
        json=FIXTURES["serviceability_ok"],
    )
    carrier.serviceability("110001")
    assert responses.calls[0].request.headers["Authorization"] == "Token tok"


@responses.activate
def test_serviceability_ok(carrier):
    responses.add(
        responses.GET, PROD + "/c/api/pin-codes/json/",
        json=FIXTURES["serviceability_ok"],
    )
    result = carrier.serviceability("110001")
    assert result.serviceable and result.remark is None
    assert result.prepaid is None and result.cod is None  # not documented
    assert "filter_codes=110001" in responses.calls[0].request.url


@responses.activate
def test_serviceability_reads_mode_flags_when_present(carrier):
    responses.add(
        responses.GET, PROD + "/c/api/pin-codes/json/",
        json=FIXTURES["serviceability_flags"],
    )
    result = carrier.serviceability("110001")
    assert result.serviceable and result.prepaid and result.pickup
    assert result.cod is False


@responses.activate
def test_serviceability_embargo_is_not_serviceable(carrier):
    responses.add(
        responses.GET, PROD + "/c/api/pin-codes/json/",
        json=FIXTURES["serviceability_embargo"],
    )
    result = carrier.serviceability("110001")
    assert result.serviceable is False and result.remark == "Embargo"


@responses.activate
def test_serviceability_none(carrier):
    responses.add(
        responses.GET, PROD + "/c/api/pin-codes/json/",
        json=FIXTURES["serviceability_none"],
    )
    assert carrier.serviceability("000000").serviceable is False


@responses.activate
def test_rates(carrier):
    responses.add(
        responses.GET, PROD + "/api/kinko/v1/invoice/charges/.json",
        json=FIXTURES["rates"],
    )
    rates = carrier.rates(
        "110001", "560001",
        Parcel(weight_kg=2, length_cm=30, breadth_cm=20, height_cm=10),
        PaymentMode.COD, 500,
    )
    assert rates[0].amount == 85.5 and rates[0].currency == "INR"
    query = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert query["md"] == ["E"] and query["ss"] == ["Delivered"]
    assert query["cgm"] == ["2000"] and query["pt"] == ["COD"]
    assert query["o_pin"] == ["110001"] and query["l"] == ["30"]
    assert "cod" not in query


@responses.activate
def test_rates_surface_mode(carrier):
    responses.add(
        responses.GET, PROD + "/api/kinko/v1/invoice/charges/.json",
        json=FIXTURES["rates"],
    )
    rates = carrier.rates(
        "110001", "560001", Parcel(weight_kg=1), PaymentMode.Prepaid, mode="S"
    )
    assert rates[0].service == "Surface"
    query = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert query["md"] == ["S"] and query["pt"] == ["Pre-paid"]


@responses.activate
def test_rates_api_error_surfaces(carrier):
    responses.add(
        responses.GET, PROD + "/api/kinko/v1/invoice/charges/.json",
        json=FIXTURES["rates_bad_mode"], status=400,
    )
    with pytest.raises(ProviderError, match="HTTP 400"):
        carrier.rates("110001", "560001", Parcel(weight_kg=1),
                      PaymentMode.Prepaid, mode="X")


@responses.activate
def test_create_shipment(carrier, shipment_request):
    shipment_request.invoice_number = "INV-9"
    responses.add(
        responses.POST, PROD + "/api/cmu/create.json", json=FIXTURES["create_ok"]
    )
    shipment = carrier.create_shipment(shipment_request)
    assert shipment.waybill == "1234567890123"
    assert shipment.remarks == []  # the API's [""] is dropped
    body = parse_qs(responses.calls[0].request.body)
    assert body["format"] == ["json"]
    payload = json.loads(body["data"][0])
    assert payload["pickup_location"] == {"name": "Main Warehouse"}
    sent = payload["shipments"][0]
    assert sent["payment_mode"] == "COD" and sent["weight"] == 1500
    assert sent["seller_inv"] == "INV-9" and sent["quantity"] == "1"
    assert "ewbn" not in sent


@responses.activate
def test_create_reverse_uses_pickup_mode(carrier, shipment_request):
    shipment_request.is_reverse = True
    responses.add(
        responses.POST, PROD + "/api/cmu/create.json", json=FIXTURES["create_ok"]
    )
    carrier.create_shipment(shipment_request)
    body = parse_qs(responses.calls[0].request.body)
    assert json.loads(body["data"][0])["shipments"][0]["payment_mode"] == "Pickup"


@responses.activate
def test_create_shipment_rejected_prefers_package_remark(carrier, shipment_request):
    responses.add(
        responses.POST, PROD + "/api/cmu/create.json",
        json=FIXTURES["create_duplicate"],
    )
    with pytest.raises(ProviderError, match="Duplicate Order Id"):
        carrier.create_shipment(shipment_request)


@responses.activate
def test_create_shipment_bad_warehouse_uses_top_level_remark(
    carrier, shipment_request
):
    responses.add(
        responses.POST, PROD + "/api/cmu/create.json",
        json=FIXTURES["create_bad_warehouse"],
    )
    with pytest.raises(ProviderError, match="ClientWarehouse matching query"):
        carrier.create_shipment(shipment_request)


@responses.activate
def test_http_error_wrapped(carrier):
    responses.add(
        responses.GET, PROD + "/c/api/pin-codes/json/", status=401, body="nope"
    )
    with pytest.raises(ProviderError) as exc:
        carrier.serviceability("110001")
    assert exc.value.status_code == 401 and exc.value.body == "nope"


@responses.activate
def test_cancel_accepted(carrier):
    responses.add(responses.POST, PROD + "/api/p/edit", json=FIXTURES["cancel_ok"])
    result = carrier.cancel("1234567890123")
    assert result.status == RequestStatus.Accepted
    assert result.message == "Shipment has been cancelled."
    # the API needs the lowercase string "true", not a boolean
    assert json.loads(responses.calls[0].request.body) == {
        "waybill": "1234567890123", "cancellation": "true",
    }


@responses.activate
def test_cancel_rejected(carrier):
    responses.add(
        responses.POST, PROD + "/api/p/edit", json=FIXTURES["cancel_rejected"]
    )
    result = carrier.cancel("1234567890123")
    assert result.status == RequestStatus.Failed
    assert "already in return flow" in result.message


def pickup_request():
    return PickupRequest(
        warehouse="Main Warehouse", pickup_date=date(2026, 11, 2),
        pickup_time=time(14, 30), package_count=5,
    )


@responses.activate
def test_schedule_pickup_reports_the_assigned_slot(carrier):
    responses.add(responses.POST, PROD + "/fm/request/new/", json=FIXTURES["pickup_ok"])
    pickup = carrier.schedule_pickup(pickup_request())
    assert pickup.pickup_id == "118775"
    assert pickup.center == "Mumbai MIDC"
    # asked for 2 Nov 14:30; the server assigned 3 Nov 16:00
    assert pickup.pickup_date == date(2026, 11, 3)
    assert pickup.pickup_time == time(16, 0)
    assert json.loads(responses.calls[0].request.body) == {
        "pickup_location": "Main Warehouse",
        "pickup_date": "2026-11-02",
        "pickup_time": "14:30:00",
        "expected_package_count": 5,
    }


@responses.activate
def test_schedule_pickup_bad_warehouse(carrier):
    responses.add(
        responses.POST, PROD + "/fm/request/new/",
        json=FIXTURES["pickup_bad_warehouse"], status=400,
    )
    with pytest.raises(ProviderError) as exc:
        carrier.schedule_pickup(pickup_request())
    assert exc.value.status_code == 400
    assert "ClientWarehouse matching query" in exc.value.body


@responses.activate
def test_ndr_reattempt_is_pending_with_request_id(carrier):
    responses.add(responses.POST, PROD + "/api/p/update", json=FIXTURES["ndr_accepted"])
    result = carrier.ndr_action(
        NdrRequest(waybill="1234567890123", action=NdrAction.Reattempt)
    )
    assert result.request_id == "UPL17749083484755923441"
    assert result.status == RequestStatus.Pending
    assert json.loads(responses.calls[0].request.body) == {
        "data": [{"waybill": "1234567890123", "act": "RE-ATTEMPT"}]
    }


@responses.activate
def test_ndr_pickup_reschedule_maps_to_act(carrier):
    responses.add(responses.POST, PROD + "/api/p/update", json=FIXTURES["ndr_accepted"])
    carrier.ndr_action(
        NdrRequest(waybill="1234567890123", action=NdrAction.PickupReschedule)
    )
    entry = json.loads(responses.calls[0].request.body)["data"][0]
    assert entry["act"] == "PICKUP_RESCHEDULE"


@pytest.mark.parametrize("action", [NdrAction.Defer, NdrAction.EditDetails])
def test_ndr_actions_not_in_current_docs_are_unsupported(carrier, action):
    # the older readme.io docs listed these; the current portal docs do not
    with pytest.raises(UnsupportedOperation):
        carrier.ndr_action(NdrRequest(waybill="1", action=action))


@responses.activate
def test_ndr_without_request_id_fails(carrier):
    responses.add(responses.POST, PROD + "/api/p/update", json=FIXTURES["ndr_no_id"])
    with pytest.raises(ProviderError):
        carrier.ndr_action(
            NdrRequest(waybill="1234567890123", action=NdrAction.Reattempt)
        )


UPL = "UPL17749083484755923441"


@responses.activate
def test_ndr_status_success(carrier):
    responses.add(
        responses.GET, PROD + "/api/cmu/get_bulk_upl/" + UPL,
        json=FIXTURES["ndr_status_done"],
    )
    result = carrier.ndr_status(UPL)
    assert result.status == RequestStatus.Completed
    assert result.succeeded == ["1234567890123"] and result.failed == {}
    assert "verbose=true" in responses.calls[0].request.url


@responses.activate
def test_ndr_status_partial_failure_keeps_both_lists(carrier):
    responses.add(
        responses.GET, PROD + "/api/cmu/get_bulk_upl/" + UPL,
        json=FIXTURES["ndr_status_partial"],
    )
    result = carrier.ndr_status(UPL)
    assert result.status == RequestStatus.Failed
    assert result.succeeded == ["1234567890123"]
    assert result.failed == {"999": "Package in incorrect status"}


@responses.activate
def test_ndr_status_unrecognised_state_stays_pending(carrier):
    responses.add(
        responses.GET, PROD + "/api/cmu/get_bulk_upl/" + UPL,
        json=FIXTURES["ndr_status_unknown"],
    )
    assert carrier.ndr_status(UPL).status == RequestStatus.Pending


def test_unimplemented_operation_is_unsupported():
    with pytest.raises(UnsupportedOperation):
        BaseCarrier().cancel("x")
