"""Tests for the Shiprocket booking client, against canned responses."""

import json
import os
from datetime import date, time
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from libshipkore.book import get_carrier, get_carriers
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

API = "https://apiv2.shiprocket.in/v1/external"
CREDENTIALS = {"email": "api@example.com", "password": "pw"}

with open(os.path.join(os.path.dirname(__file__), "fixtures", "shiprocket.json")) as f:
    FIXTURES = json.load(f)


def login(rsps=responses, fixture="login"):
    rsps.add(responses.POST, API + "/auth/login", json=FIXTURES[fixture])


@pytest.fixture
def carrier():
    return get_carrier("shiprocket", credentials=dict(CREDENTIALS))


@pytest.fixture
def shipment_request():
    return ShipmentRequest(
        order_id="ORD-1",
        consignee=Address(
            name="Asha", phone="9876543210", address="12 MG Road",
            pincode="560001", city="Bengaluru", state="Karnataka",
            email="asha@example.com",
        ),
        pickup_location="Primary",
        parcel=Parcel(weight_kg=1.5, length_cm=10, breadth_cm=10, height_cm=5),
        payment_mode=PaymentMode.COD,
        cod_amount=999,
        declared_value=1000,
        description="Shirt",
        quantity=2,
    )


def test_registered():
    assert "shiprocket" in get_carriers()


def test_missing_credentials_raises():
    with pytest.raises(CredentialsError):
        get_carrier("shiprocket").cancel("1")


def test_no_sandbox():
    carrier = get_carrier(
        "shiprocket", credentials=dict(CREDENTIALS), sandbox=True
    )
    with pytest.raises(UnsupportedOperation):
        carrier.cancel("1")


@responses.activate
def test_login_once_then_bearer_reused(carrier):
    login()
    responses.add(responses.POST, API + "/orders/cancel/shipment/awbs",
                  json=FIXTURES["cancel_ok"])
    carrier.cancel("1")
    carrier.cancel("2")
    logins = [c for c in responses.calls if c.request.url.endswith("/auth/login")]
    assert len(logins) == 1
    assert json.loads(logins[0].request.body) == CREDENTIALS
    assert responses.calls[1].request.headers["Authorization"] == "Bearer jwt-1"
    assert responses.calls[2].request.headers["Authorization"] == "Bearer jwt-1"


@responses.activate
def test_supplied_token_skips_login():
    carrier = get_carrier("shiprocket", credentials={"token": "given"})
    responses.add(responses.POST, API + "/orders/cancel/shipment/awbs",
                  json=FIXTURES["cancel_ok"])
    carrier.cancel("1")
    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["Authorization"] == "Bearer given"


@responses.activate
def test_expired_token_relogs_in_once_and_retries(carrier):
    url = API + "/orders/cancel/shipment/awbs"
    login()
    responses.add(responses.POST, url, status=401, body="expired")
    responses.add(responses.POST, API + "/auth/login", json=FIXTURES["login_2"])
    responses.add(responses.POST, url, json=FIXTURES["cancel_ok"])
    carrier.cancel("1")
    assert responses.calls[-1].request.headers["Authorization"] == "Bearer jwt-2"


@responses.activate
def test_persistent_401_gives_up_after_one_retry(carrier):
    url = API + "/orders/cancel/shipment/awbs"
    login()
    responses.add(responses.POST, url, status=401, body="no")
    responses.add(responses.POST, API + "/auth/login", json=FIXTURES["login_2"])
    responses.add(responses.POST, url, status=401, body="no")
    with pytest.raises(ProviderError) as exc:
        carrier.cancel("1")
    assert exc.value.status_code == 401
    assert len(responses.calls) == 4


@responses.activate
def test_failed_login(carrier):
    responses.add(responses.POST, API + "/auth/login", status=403, body="bad")
    with pytest.raises(ProviderError, match="login failed"):
        carrier.cancel("1")


@responses.activate
def test_serviceability_uses_credential_origin():
    carrier = get_carrier(
        "shiprocket", credentials={**CREDENTIALS, "pickup_pincode": "110001"}
    )
    login()
    responses.add(responses.GET, API + "/courier/serviceability/",
                  json=FIXTURES["serviceability"])
    result = carrier.serviceability("560001")
    assert result.serviceable
    query = parse_qs(urlparse(responses.calls[1].request.url).query)
    assert query["pickup_postcode"] == ["110001"]
    assert query["delivery_postcode"] == ["560001"]


@responses.activate
def test_serviceability_none(carrier):
    login()
    responses.add(responses.GET, API + "/courier/serviceability/",
                  json=FIXTURES["serviceability_none"])
    assert carrier.serviceability("560001", origin_pincode="110001") \
        .serviceable is False


def test_serviceability_needs_an_origin(carrier):
    with pytest.raises(ValueError, match="origin_pincode"):
        carrier.serviceability("560001")


@responses.activate
def test_rates_sorted_cheapest_first(carrier):
    login()
    responses.add(responses.GET, API + "/courier/serviceability/",
                  json=FIXTURES["serviceability"])
    rates = carrier.rates(
        "110001", "560001", Parcel(weight_kg=2), PaymentMode.COD
    )
    assert [r.service for r in rates] == [
        "Delhivery Surface", "Xpressbees", "Blue Dart Air",
    ]
    assert rates[0].amount == 85.5 and rates[0].estimated_days == 3
    assert rates[2].estimated_days is None
    query = parse_qs(urlparse(responses.calls[1].request.url).query)
    assert query["cod"] == ["1"] and query["weight"] == ["2.0"]


@responses.activate
def test_create_shipment_creates_order_then_assigns_awb(carrier, shipment_request):
    login()
    responses.add(responses.POST, API + "/orders/create/adhoc",
                  json=FIXTURES["create_order"])
    responses.add(responses.POST, API + "/courier/assign/awb",
                  json=FIXTURES["assign_awb"])
    shipment = carrier.create_shipment(shipment_request)
    assert shipment.waybill == "19041211125783"
    assert shipment.reference == "15151515"
    order = json.loads(responses.calls[1].request.body)
    assert order["payment_method"] == "COD" and order["sub_total"] == 1000
    assert order["shipping_is_billing"] is True
    assert order["order_items"][0]["units"] == 2
    assert order["order_items"][0]["selling_price"] == 500
    assert json.loads(responses.calls[2].request.body) == {"shipment_id": 15151515}


@responses.activate
def test_create_shipment_passes_chosen_courier(carrier, shipment_request):
    login()
    responses.add(responses.POST, API + "/orders/create/adhoc",
                  json=FIXTURES["create_order"])
    responses.add(responses.POST, API + "/courier/assign/awb",
                  json=FIXTURES["assign_awb"])
    carrier.create_shipment(shipment_request, courier_id=54)
    assert json.loads(responses.calls[2].request.body)["courier_id"] == 54


@responses.activate
def test_create_order_rejected(carrier, shipment_request):
    login()
    responses.add(responses.POST, API + "/orders/create/adhoc",
                  json=FIXTURES["create_order_rejected"])
    with pytest.raises(ProviderError, match="Wrong pickup location"):
        carrier.create_shipment(shipment_request)


@responses.activate
def test_awb_failure_reports_the_orphaned_shipment(carrier, shipment_request):
    login()
    responses.add(responses.POST, API + "/orders/create/adhoc",
                  json=FIXTURES["create_order"])
    responses.add(responses.POST, API + "/courier/assign/awb",
                  json=FIXTURES["assign_awb_failed"])
    with pytest.raises(ProviderError, match="shipment 15151515"):
        carrier.create_shipment(shipment_request)


def test_create_requires_fields_shiprocket_demands(carrier, shipment_request):
    shipment_request.consignee.email = None
    shipment_request.parcel.height_cm = None
    with pytest.raises(ValueError, match="consignee.email, parcel.height_cm"):
        carrier.create_shipment(shipment_request)


@responses.activate
def test_cancel_is_pending_not_done(carrier):
    login()
    responses.add(responses.POST, API + "/orders/cancel/shipment/awbs",
                  json=FIXTURES["cancel_ok"])
    result = carrier.cancel("19041211125783")
    assert result.status == RequestStatus.Pending
    assert "in progress" in result.message
    assert json.loads(responses.calls[1].request.body) == {
        "awbs": ["19041211125783"]
    }


@responses.activate
def test_cancel_with_empty_204_body(carrier):
    login()
    responses.add(responses.POST, API + "/orders/cancel/shipment/awbs",
                  status=204)
    assert carrier.cancel("1").status == RequestStatus.Pending


@responses.activate
def test_schedule_pickup(carrier):
    login()
    responses.add(responses.POST, API + "/courier/generate/pickup",
                  json=FIXTURES["pickup_ok"])
    pickup = carrier.schedule_pickup(
        PickupRequest(pickup_date=date(2021, 12, 10), shipment_ids=["15151515"])
    )
    assert pickup.pickup_id.startswith("Reference No: 194_BIGFOOT")
    assert pickup.pickup_date == date(2021, 12, 10)
    assert pickup.pickup_time == time(12, 39, 54)
    assert json.loads(responses.calls[1].request.body) == {
        "shipment_id": [15151515], "pickup_date": ["2021-12-10"],
    }


@responses.activate
def test_pickup_not_booked(carrier):
    login()
    responses.add(responses.POST, API + "/courier/generate/pickup",
                  json=FIXTURES["pickup_failed"])
    with pytest.raises(ProviderError, match="Already in Pickup Scheduled"):
        carrier.schedule_pickup(
            PickupRequest(pickup_date=date(2021, 12, 10), shipment_ids=["1"])
        )


@pytest.mark.parametrize("ids", [[], ["1", "2"]])
def test_pickup_needs_exactly_one_shipment(carrier, ids):
    with pytest.raises(ValueError, match="one shipment"):
        carrier.schedule_pickup(
            PickupRequest(pickup_date=date(2021, 12, 10), shipment_ids=ids)
        )


def test_ndr_not_implemented_yet(carrier):
    with pytest.raises(UnsupportedOperation):
        carrier.ndr_action(NdrRequest(waybill="1", action=NdrAction.Reattempt))


@responses.activate
def test_label_uses_shipment_reference(carrier):
    login()
    responses.add(responses.POST, API + "/courier/generate/label",
                  json=FIXTURES["label_ok"])
    label = carrier.label("19041211125783", reference="15151515")
    assert label.url.endswith("label-15151515.pdf")
    assert json.loads(responses.calls[1].request.body) == {
        "shipment_id": [15151515]
    }


@responses.activate
def test_label_not_created(carrier):
    login()
    responses.add(responses.POST, API + "/courier/generate/label",
                  json=FIXTURES["label_failed"])
    with pytest.raises(ProviderError, match="no label"):
        carrier.label("1", reference="15151515")


def test_label_needs_the_reference(carrier):
    with pytest.raises(ValueError, match="reference"):
        carrier.label("19041211125783")


# tracking (response shape unverified; scan fields from the webhook docs) ----

@responses.activate
def test_track_reads_the_scan_history(carrier):
    login()
    responses.add(responses.GET, API + "/courier/track/awb/AWB1", json={"tracking_data": {
        "shipment_track": [{"current_status": "In Transit"}], "etd": "2026-05-04 18:00:00",
        "shipment_track_activities": [
            {"date": "2026-05-01 10:00:00", "status": "X-UCI", "activity": "Manifested",
             "location": "Delhi", "sr-status-label": "MANIFEST GENERATED"},
            {"date": "2026-05-02 09:30:00", "status": "X-ILL1F", "activity": "At hub",
             "location": "Jaipur", "sr-status-label": "IN TRANSIT"},
        ]}})
    track = carrier.track("AWB1")
    assert track.status.value == "InTransit" and track.checkpoints[0].message == "At hub"
    assert track.checkpoints[0].checkpoint_time.isoformat() == "2026-05-02T09:30:00+05:30"
    assert track.estimated_date.isoformat() == "2026-05-04T18:00:00+05:30"
    assert "track" in carrier.capabilities


@responses.activate
def test_track_with_no_scans_is_a_provider_error(carrier):
    login()
    responses.add(responses.GET, API + "/courier/track/awb/AWB1",
                  json={"tracking_data": {"track_status": 0, "error": "no data"}})
    with pytest.raises(ProviderError, match="no data"):
        carrier.track("AWB1")
