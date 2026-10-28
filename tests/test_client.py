"""Tests for the Shipkore facade, over mocked provider HTTP."""

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import parse_qs

import pytest
import responses

from libshipkore.book.models import (
    Address,
    NdrAction,
    OrderStatus,
    Parcel,
    PaymentMode,
    Product,
    RequestStatus,
)
from libshipkore.client import Shipkore
from libshipkore.common.exceptions import (
    DuplicateOrder,
    NotFound,
    ProviderError,
    UnsupportedOperation,
)
from libshipkore.files import MemoryFileStore
from libshipkore.storage import MemoryStorage
from libshipkore.track.models.model import Checkpoint, Track

DELHIVERY = "https://track.delhivery.com"
SHIPROCKET = "https://apiv2.shiprocket.in/v1/external"
HERE = os.path.dirname(__file__)

with open(os.path.join(HERE, "fixtures", "delhivery.json")) as f:
    DLV = json.load(f)
with open(os.path.join(HERE, "fixtures", "shiprocket.json")) as f:
    SR = json.load(f)

PDF = b"%PDF-1.4 label"
PDF_URL = DLV["label_ok"]["packages"][0]["pdf_download_link"]
NOW = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)

PROVIDERS = {
    "delhivery": {"credentials": {"api_token": "tok"}},
    "shiprocket": {"credentials": {"email": "a@b.c", "password": "pw"}},
}


@pytest.fixture
def clock():
    box = {"now": NOW}
    return box


@pytest.fixture
def kore(clock):
    shipkore = Shipkore(providers=PROVIDERS, storage=MemoryStorage(),
                        files=MemoryFileStore())
    shipkore._now = lambda: clock["now"]
    shipkore.save_product(Product(sku="TEE", name="T-shirt", price=499,
                                  weight_kg=0.3))
    return shipkore


def consignee():
    return Address(
        name="Asha", phone="9876543210", address="12 MG Road",
        pincode="560001", city="Bengaluru", state="Karnataka",
        email="asha@example.com",
    )


def book(kore, order_id="ORD-1", provider="delhivery", **kwargs):
    kwargs.setdefault("items", [{"sku": "TEE", "quantity": 2}])
    return kore.create_order(provider, order_id, consignee(), "Main WH", **kwargs)


def mock_create(fixture="create_ok", status=200):
    responses.add(responses.POST, DELHIVERY + "/api/cmu/create.json",
                  json=DLV[fixture], status=status)


def make_track(status="InTransit"):
    return Track(
        waybill="1234567890123", provider="delhivery", status=status,
        checkpoints=[Checkpoint(slug="delhivery", message="scan",
                                checkpoint_time=NOW)],
    )


# products ------------------------------------------------------------------

def test_product_catalog_crud(kore):
    assert kore.get_product("TEE").price == 499
    kore.save_product({"sku": "CAP", "name": "Cap", "price": 199, "weight_kg": 0.1})
    assert {p.sku for p in kore.list_products()} == {"TEE", "CAP"}
    assert kore.delete_product("CAP") is True
    with pytest.raises(NotFound):
        kore.get_product("CAP")


def test_service_types(kore):
    services = kore.services("delhivery")
    assert [(s.code, s.name) for s in services] == [("E", "Express"), ("S", "Surface")]
    with pytest.raises(UnsupportedOperation):
        kore.services("shiprocket")


# orders --------------------------------------------------------------------

@responses.activate
def test_create_order_derives_value_weight_and_description(kore):
    mock_create()
    order = book(kore)
    assert order.status == OrderStatus.Booked
    assert order.waybill == "1234567890123"
    assert order.declared_value == 998 and order.parcel.weight_kg == pytest.approx(0.6)
    assert order.description == "T-shirt x2"
    sent = json.loads(parse_qs(responses.calls[0].request.body)["data"][0])
    shipment = sent["shipments"][0]
    assert shipment["weight"] == pytest.approx(600)
    assert shipment["total_amount"] == 998 and shipment["quantity"] == "2"
    assert shipment["products_desc"] == "T-shirt x2"
    assert sent["pickup_location"] == {"name": "Main WH"}


@responses.activate
def test_order_is_stored_and_listed(kore):
    mock_create()
    book(kore)
    assert kore.get_order("ORD-1").provider == "delhivery"
    assert [o.order_id for o in kore.list_orders(provider="delhivery")] == ["ORD-1"]
    assert kore.list_orders(provider="shiprocket") == []
    assert kore.list_orders(status="Booked")[0].order_id == "ORD-1"
    with pytest.raises(NotFound):
        kore.get_order("missing")


@responses.activate
def test_booked_order_cannot_be_created_twice(kore):
    mock_create()
    book(kore)
    with pytest.raises(DuplicateOrder):
        book(kore)
    assert len(responses.calls) == 1


@responses.activate
def test_failed_order_is_stored_and_can_be_retried(kore, clock):
    mock_create("create_duplicate")
    with pytest.raises(ProviderError, match="Duplicate Order Id"):
        book(kore)
    failed = kore.get_order("ORD-1")
    assert failed.status == OrderStatus.Failed and "Duplicate" in failed.error
    clock["now"] += timedelta(minutes=5)
    responses.replace(responses.POST, DELHIVERY + "/api/cmu/create.json",
                      json=DLV["create_ok"])
    retried = book(kore)
    assert retried.status == OrderStatus.Booked and retried.error is None
    assert retried.created_at == failed.created_at


def test_unknown_sku_and_missing_weight_are_caught_before_any_call(kore):
    with pytest.raises(NotFound):
        book(kore, items=[{"sku": "NOPE"}])
    with pytest.raises(ValueError, match="parcel"):
        book(kore, items=None)
    with pytest.raises(NotFound):
        kore.get_order("ORD-1")


@responses.activate
def test_explicit_parcel_and_value_override_the_catalog(kore):
    mock_create()
    order = book(kore, items=None, parcel=Parcel(weight_kg=2), declared_value=50,
                 description="Gift", payment_mode=PaymentMode.COD, cod_amount=50)
    assert order.parcel.weight_kg == 2 and order.declared_value == 50
    assert order.payment_mode == PaymentMode.COD


@responses.activate
def test_shiprocket_order_keeps_the_provider_reference(kore):
    responses.add(responses.POST, SHIPROCKET + "/auth/login", json=SR["login"])
    responses.add(responses.POST, SHIPROCKET + "/orders/create/adhoc",
                  json=SR["create_order"])
    responses.add(responses.POST, SHIPROCKET + "/courier/assign/awb",
                  json=SR["assign_awb"])
    order = book(kore, provider="shiprocket",
                 parcel=Parcel(weight_kg=1, length_cm=10, breadth_cm=10, height_cm=5),
                 courier_id=54)
    assert order.waybill == "19041211125783" and order.reference == "15151515"
    assert json.loads(responses.calls[-1].request.body)["courier_id"] == 54


# cancel / pickup / NDR -----------------------------------------------------

@responses.activate
def test_cancel_marks_the_order_cancelled(kore):
    mock_create()
    book(kore)
    responses.add(responses.POST, DELHIVERY + "/api/p/edit", json=DLV["cancel_ok"])
    assert kore.cancel_order("ORD-1").status == OrderStatus.Cancelled
    with pytest.raises(ValueError, match="not booked"):
        kore.cancel_order("ORD-1")


@responses.activate
def test_refused_cancel_is_raised_and_recorded_on_the_order(kore):
    mock_create()
    book(kore)
    responses.add(responses.POST, DELHIVERY + "/api/p/edit",
                  json=DLV["cancel_rejected"])
    with pytest.raises(ProviderError, match="picked up"):
        kore.cancel_order("ORD-1")
    order = kore.get_order("ORD-1")
    assert order.status == OrderStatus.Booked and "picked up" in order.error


@responses.activate
def test_asynchronous_cancel_leaves_the_order_pending(kore):
    responses.add(responses.POST, SHIPROCKET + "/auth/login", json=SR["login"])
    responses.add(responses.POST, SHIPROCKET + "/orders/create/adhoc",
                  json=SR["create_order"])
    responses.add(responses.POST, SHIPROCKET + "/courier/assign/awb",
                  json=SR["assign_awb"])
    responses.add(responses.POST, SHIPROCKET + "/orders/cancel/shipment/awbs",
                  json=SR["cancel_ok"])
    book(kore, provider="shiprocket",
         parcel=Parcel(weight_kg=1, length_cm=10, breadth_cm=10, height_cm=5))
    assert kore.cancel_order("ORD-1").status == OrderStatus.CancelPending


@responses.activate
def test_schedule_pickup_is_kept_on_the_order(kore):
    mock_create()
    book(kore)
    responses.add(responses.POST, DELHIVERY + "/fm/request/new/", json=DLV["pickup_ok"])
    pickup = kore.schedule_pickup("ORD-1", date(2026, 11, 2), time(14, 30))
    assert pickup.pickup_id == "118775"
    assert kore.get_order("ORD-1").pickup.center == "Mumbai MIDC"
    body = json.loads(responses.calls[-1].request.body)
    assert body["pickup_location"] == "Main WH" and body["expected_package_count"] == 1


@responses.activate
def test_ndr_action_and_status_are_tracked_on_the_order(kore):
    mock_create()
    book(kore)
    responses.add(responses.POST, DELHIVERY + "/api/p/update", json=DLV["ndr_accepted"])
    result = kore.ndr_action("ORD-1", NdrAction.Reattempt)
    assert result.status == RequestStatus.Pending
    upl = DLV["ndr_accepted"]["request_id"]
    responses.add(responses.GET, DELHIVERY + "/api/cmu/get_bulk_upl/" + upl,
                  json=DLV["ndr_status_done"])
    done = kore.ndr_status("ORD-1")
    assert done.status == RequestStatus.Completed and done.waybill == "1234567890123"
    assert kore.get_order("ORD-1").ndr[-1].status == RequestStatus.Completed


def test_ndr_status_without_a_request(kore):
    kore.storage.put("orders", "X", json.loads(_booked_order_json(kore)))
    with pytest.raises(NotFound, match="no NDR"):
        kore.ndr_status("X")


def _booked_order_json(kore):
    from libshipkore.book.models import Order
    now = NOW
    return Order(
        order_id="X", provider="delhivery", status="Booked", consignee=consignee(),
        pickup_location="W", parcel=Parcel(weight_kg=1), waybill="1",
        created_at=now, updated_at=now,
    ).model_dump_json()


# labels --------------------------------------------------------------------

@responses.activate
def test_label_pdf_is_copied_to_the_file_store_once(kore):
    mock_create()
    book(kore)
    responses.add(responses.GET, DELHIVERY + "/api/p/packing_slip",
                  json=DLV["label_ok"])
    responses.add(responses.GET, PDF_URL, body=PDF)
    label = kore.label("ORD-1", size="4R")
    key = "labels/delhivery/1234567890123.pdf"
    assert label.storage_key == key and label.url.startswith("memory://" + key)
    assert kore.files.get(key) == PDF
    calls = len(responses.calls)

    again = kore.label("ORD-1")
    assert again.storage_key == key and again.url.startswith("memory://")
    assert len(responses.calls) == calls  # no provider call, no download

    kore.label("ORD-1", refresh=True)
    assert len(responses.calls) == calls + 2


@responses.activate
def test_label_is_regenerated_if_the_stored_pdf_vanished(kore):
    mock_create()
    book(kore)
    responses.add(responses.GET, DELHIVERY + "/api/p/packing_slip",
                  json=DLV["label_ok"])
    responses.add(responses.GET, PDF_URL, body=PDF)
    kore.label("ORD-1")
    kore.files.delete("labels/delhivery/1234567890123.pdf")
    kore.label("ORD-1")
    assert kore.files.exists("labels/delhivery/1234567890123.pdf")


@responses.activate
def test_label_without_a_file_store_reuses_the_link_until_it_expires(clock):
    kore = Shipkore(providers=PROVIDERS, storage=MemoryStorage())
    kore._now = lambda: clock["now"]
    mock_create()
    book(kore, items=None, parcel=Parcel(weight_kg=1))
    responses.add(responses.GET, DELHIVERY + "/api/p/packing_slip",
                  json=DLV["label_ok"])
    first = kore.label("ORD-1")
    assert first.url == PDF_URL and first.storage_key is None
    clock["now"] += timedelta(hours=23)
    assert kore.label("ORD-1").url == PDF_URL
    assert len(responses.calls) == 2  # create + one packing slip
    clock["now"] += timedelta(hours=2)  # past the 24h expiry
    kore.label("ORD-1")
    assert len(responses.calls) == 3


@responses.activate
def test_label_download_failure_is_a_storage_error(kore):
    from libshipkore.common.exceptions import StorageError
    mock_create()
    book(kore)
    responses.add(responses.GET, DELHIVERY + "/api/p/packing_slip",
                  json=DLV["label_ok"])
    responses.add(responses.GET, PDF_URL, status=403, body="expired")
    with pytest.raises(StorageError, match="could not download"):
        kore.label("ORD-1")
    assert not kore.files.files


# tracking ------------------------------------------------------------------

@pytest.fixture
def tracker(monkeypatch):
    calls = []
    state = {"status": "InTransit"}

    def fake(slug, waybill):
        calls.append((slug, waybill))
        return make_track(state["status"])

    monkeypatch.setattr("libshipkore.book.base.get_track_data", fake)
    return calls, state


def test_tracking_is_served_from_storage_within_the_ttl(kore, tracker, clock):
    calls, _ = tracker
    kore.track("1234567890123", "delhivery")
    kore.track("1234567890123", "delhivery")
    assert len(calls) == 1
    clock["now"] += timedelta(seconds=301)
    kore.track("1234567890123", "delhivery")
    assert len(calls) == 2
    kore.track("1234567890123", "delhivery", refresh=True)
    assert len(calls) == 3


def test_delivered_shipments_are_never_refetched(kore, tracker, clock):
    calls, state = tracker
    state["status"] = "Delivered"
    kore.track("1234567890123", "delhivery")
    clock["now"] += timedelta(days=30)
    result = kore.track("1234567890123", "delhivery")
    assert len(calls) == 1 and result.status.value == "Delivered"
    assert result.checkpoints[0].message == "scan"


def test_tracking_works_for_providers_without_credentials(kore, tracker):
    calls, _ = tracker
    kore.track("999", "dtdc")
    assert calls == [("dtdc", "999")]


def test_track_order_updates_the_delivery_status(kore, tracker):
    kore.storage.put("orders", "X", json.loads(_booked_order_json(kore)))
    track = kore.track_order("X")
    assert track.status.value == "InTransit"
    assert kore.get_order("X").delivery_status == "InTransit"


def test_missing_tracking_data(kore, monkeypatch):
    monkeypatch.setattr("libshipkore.book.base.get_track_data", lambda s, w: None)
    with pytest.raises(NotFound):
        kore.track("1", "delhivery")


# audit trail ---------------------------------------------------------------

@responses.activate
def test_raw_provider_responses_are_recorded_without_credentials(kore):
    mock_create()
    book(kore)
    records = kore.responses(order_id="ORD-1")
    assert len(records) == 1
    record = records[0]
    assert record["operation"] == "create_shipment"
    assert record["provider"] == "delhivery" and record["status_code"] == 200
    assert "1234567890123" in record["body"]
    # only the response is kept: no request headers, so no API token
    assert "Authorization" not in json.dumps(record)
    assert set(record) == {"id", "provider", "operation", "order_id", "method",
                           "path", "status_code", "body", "at"}


@responses.activate
def test_failed_calls_are_recorded_too(kore):
    mock_create("create_duplicate")
    with pytest.raises(ProviderError):
        book(kore)
    assert "Duplicate Order Id" in kore.responses(order_id="ORD-1")[0]["body"]


@responses.activate
def test_recording_can_be_turned_off():
    kore = Shipkore(providers=PROVIDERS, storage=MemoryStorage(),
                    record_responses=False)
    mock_create()
    kore.save_product(Product(sku="T", name="T", price=1, weight_kg=1))
    kore.create_order("delhivery", "O", consignee(), "W", items=[{"sku": "T"}])
    assert kore.responses() == []


def test_a_broken_recorder_never_breaks_the_call(kore, monkeypatch):
    monkeypatch.setattr(kore.storage, "put", _raise_for_responses(kore.storage.put))
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, DELHIVERY + "/api/cmu/create.json",
                 json=DLV["create_ok"])
        assert book(kore).status == OrderStatus.Booked


def _raise_for_responses(real_put):
    def put(collection, key, document):
        if collection == "responses":
            raise RuntimeError("audit store down")
        real_put(collection, key, document)
    return put


# configuration -------------------------------------------------------------

@responses.activate
def test_orders_persist_in_a_sqlite_file_across_instances(tmp_path):
    url = f"sqlite:///{tmp_path / 'kore.db'}"
    mock_create()
    with Shipkore(providers=PROVIDERS, storage=url) as first:
        first.save_product(Product(sku="T", name="T", price=10, weight_kg=1))
        first.create_order("delhivery", "ORD-9", consignee(), "W", items=[{"sku": "T"}])
    with Shipkore(storage=url) as second:
        assert second.get_order("ORD-9").waybill == "1234567890123"
        assert second.get_product("T").price == 10
        assert second.responses(order_id="ORD-9")


def test_from_config_builds_storage_and_files(tmp_path):
    kore = Shipkore.from_config({
        "providers": PROVIDERS,
        "storage": {"backend": "sqlite", "path": str(tmp_path / "c.db")},
        "files": "memory://",
        "sandbox": True,
        "track_ttl": 10,
    })
    assert isinstance(kore.files, MemoryFileStore) and kore.track_ttl == 10
    assert kore.provider("delhivery").sandbox is True


def test_sandbox_can_be_set_per_provider():
    kore = Shipkore(providers={
        "delhivery": {"credentials": {"api_token": "t"}, "sandbox": True},
        "shiprocket": {},
    })
    assert kore.provider("delhivery").sandbox is True
    assert kore.provider("shiprocket").sandbox is False
    assert kore.provider("delhivery") is kore.provider("delhivery")


@responses.activate
def test_stateless_lookups_pass_through(kore):
    responses.add(responses.GET, DELHIVERY + "/c/api/pin-codes/json/",
                  json=DLV["serviceability_ok"])
    assert kore.serviceability("delhivery", "110001").serviceable
    responses.add(responses.GET, DELHIVERY + "/api/kinko/v1/invoice/charges/.json",
                  json=DLV["rates"])
    rates = kore.rates("delhivery", "110001", "560001", Parcel(weight_kg=1))
    assert rates[0].amount == 85.5


# previews: what a booking would do, without doing it --------------------

def test_a_preview_touches_neither_the_provider_nor_storage(kore):
    with responses.RequestsMock():  # no routes registered: any HTTP call raises
        order = kore.preview_order(
            "delhivery", "ORD-1", consignee(), "Main WH", items=[{"sku": "TEE", "quantity": 2}])
    assert order.status == OrderStatus.Draft and order.declared_value == 998
    assert order.description == "T-shirt x2" and order.waybill is None
    assert kore.list_orders() == [] and kore.responses() == []


def test_a_preview_applies_the_providers_own_requirements(kore):
    missing = consignee()
    missing.email = None
    with pytest.raises(ValueError, match="consignee.email.*parcel.length_cm"):
        kore.preview_order("shiprocket", "SR-1", missing, "Primary",
                           parcel=Parcel(weight_kg=1))
    with pytest.raises(ValueError, match="only the provider option courier_id"):
        kore.preview_order("shiprocket", "SR-1", consignee(), "Primary",
                           parcel=Parcel(weight_kg=1, length_cm=1, breadth_cm=1, height_cm=1),
                           surprise=1)


@responses.activate
def test_a_preview_refuses_what_booking_would_refuse(kore):
    mock_create()
    book(kore)
    with pytest.raises(DuplicateOrder):
        kore.preview_order("delhivery", "ORD-1", consignee(), "Main WH",
                           items=[{"sku": "TEE"}])


@responses.activate
def test_pickups_and_ndr_actions_need_a_booked_order(kore):
    mock_create()
    book(kore)
    responses.add(responses.POST, DELHIVERY + "/api/p/edit", json=DLV["cancel_ok"])
    kore.cancel_order("ORD-1")
    with pytest.raises(ValueError, match="Cancelled, not booked"):
        kore.preview_pickup("ORD-1", date(2026, 11, 2), time(10, 0))
    with pytest.raises(ValueError, match="Cancelled, not booked"):
        kore.preview_ndr_action("ORD-1", NdrAction.Reattempt)


@responses.activate
def test_a_pickup_preview_applies_the_providers_requirements(kore):
    mock_create()
    book(kore)
    with pytest.raises(ValueError, match="pickup_time"):
        kore.preview_pickup("ORD-1", date(2026, 11, 2))
    order, request = kore.preview_pickup("ORD-1", date(2026, 11, 2), time(10, 0))
    assert request.warehouse == "Main WH" and order.status == OrderStatus.Booked
    with pytest.raises(UnsupportedOperation):
        kore.preview_ndr_action("ORD-1", NdrAction.Defer)
