"""
Contract tests for the tracking models and trackers.

Trackers feed scraped and JSON values straight into Track, so these pin the
behaviour consumers saw under pydantic 1 (checked by running the old and new
models over the same inputs): numbers fill text fields, a date-only string
stays a date, and JSON dates are plain isoformat with +00:00 for UTC.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
import responses
from pydantic import ValidationError

from libshipkore.common.serialization import to_jsonable
from libshipkore.track import get_track_data
from libshipkore.track.models.model import Checkpoint, StatusChoice, Track


def checkpoint(**fields):
    base = {"slug": "s", "checkpoint_time": "2026-01-02T03:04:05+05:30"}
    return Checkpoint(**{**base, **fields})


def track(**fields):
    base = {"waybill": "W", "provider": "p", "checkpoints": []}
    return Track(**{**base, **fields})


# models --------------------------------------------------------------------

def test_a_timestamp_keeps_its_offset():
    value = checkpoint().checkpoint_time
    assert isinstance(value, datetime)
    assert value.utcoffset() == timedelta(hours=5, minutes=30)
    assert to_jsonable(checkpoint())["checkpoint_time"] == "2026-01-02T03:04:05+05:30"


def test_a_date_only_string_stays_a_date():
    value = checkpoint(checkpoint_time="2026-01-02").checkpoint_time
    assert type(value) is date
    assert to_jsonable(checkpoint(checkpoint_time="2026-01-02"))[
        "checkpoint_time"] == "2026-01-02"


def test_a_midnight_timestamp_is_still_a_datetime():
    value = checkpoint(checkpoint_time="2026-01-02T00:00:00").checkpoint_time
    assert isinstance(value, datetime)


def test_utc_is_written_as_plus_zero_not_z():
    dumped = to_jsonable(checkpoint(checkpoint_time="2026-01-02T03:04:05Z"))
    assert dumped["checkpoint_time"] == "2026-01-02T03:04:05+00:00"


@pytest.mark.parametrize("raw, expected", [
    (1767323045, "2026-01-02T03:04:05+00:00"),
    ("1767323045", "2026-01-02T03:04:05+00:00"),
    (1767323045.5, "2026-01-02T03:04:05.500000+00:00"),
])
def test_epoch_seconds_are_read_as_utc(raw, expected):
    assert to_jsonable(checkpoint(checkpoint_time=raw))["checkpoint_time"] == expected


def test_date_and_datetime_objects_pass_through():
    assert type(checkpoint(checkpoint_time=date(2026, 1, 2)).checkpoint_time) is date
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert checkpoint(checkpoint_time=moment).checkpoint_time == moment


def test_optional_dates_follow_the_same_rules():
    result = track(estimated_date="2026-01-05", delivered_date="2026-01-06T10:00:00Z")
    assert type(result.estimated_date) is date
    dumped = to_jsonable(result)
    assert dumped["estimated_date"] == "2026-01-05"
    assert dumped["delivered_date"] == "2026-01-06T10:00:00+00:00"


@pytest.mark.parametrize("value, expected", [
    (560001, "560001"), (56.5, "56.5"), ("560001", "560001"), ("", ""),
])
def test_numbers_fill_text_fields(value, expected):
    assert checkpoint(zip=value).zip == expected
    assert track(waybill=value).waybill == expected


def test_optionals_default_to_none_and_status_to_exception():
    result = track()
    assert result.status == StatusChoice.Exception
    for name in ("substatus", "estimated_date", "reference_no", "package_type",
                 "destination", "client", "consignee_address", "product",
                 "receiver_name", "delivered_date"):
        assert getattr(result, name) is None, name
    assert checkpoint().city is None and checkpoint().zip is None


def test_none_is_accepted_for_optional_fields():
    assert checkpoint(city=None, zip=None, status=StatusChoice.Delivered).city is None
    assert track(estimated_date=None, product=None).product is None


def test_unknown_keys_from_a_scraper_are_ignored():
    result = track(shipment_type="MPS", receiver_relationship="self")
    assert not hasattr(result, "shipment_type")


@pytest.mark.parametrize("fields", [
    {"checkpoint_time": "garbage"},
    {"checkpoint_time": None},
    {"city": ["a"]},
    {"message": {"k": 1}},
    {"status": "bogus"},
    {"status": None},
])
def test_bad_values_are_rejected(fields):
    with pytest.raises(ValidationError):
        checkpoint(**fields)


def test_a_boolean_is_not_accepted_as_text():
    # pydantic 1 turned True into "True"; a tracker doing that has a bug
    with pytest.raises(ValidationError):
        checkpoint(message=True)


def test_checkpoints_must_be_a_list():
    with pytest.raises(ValidationError):
        track(checkpoints=None)


# trackers, from raw provider payload to final JSON -------------------------

@responses.activate
def test_delhivery_tracker_end_to_end():
    responses.add(
        responses.GET,
        "https://dlv-web-api.delhivery.com/v3/track?wbn=1234567890123",
        json={"data": [{
            "status": {"status": "IN_TRANSIT"},
            "estimatedDate": "2026-01-05T00:00:00",
            "referenceNo": 99812,
            "packageType": "COD",
            "destination": "Bengaluru",
            "clientName": "Acme",
            "consigneeAddress": "12 MG Road",
            "productName": "T-shirt",
            "scans": [
                {"scan": "OUT_DELIVERY", "cityLocation": "Bengaluru",
                 "scanNslRemark": "Out for delivery",
                 "scanDateTime": "2026-01-04T08:00:00"},
                {"scan": "WAITING_PICKUP", "cityLocation": "Delhi",
                 "scanNslRemark": "Manifested",
                 "scanDateTime": "2026-01-02T10:30:00"},
            ],
        }]},
    )
    result = get_track_data("delhivery", "1234567890123")
    data = to_jsonable(result)
    assert data["status"] == "InTransit" and data["provider"] == "delhivery"
    assert data["reference_no"] == "99812"  # a number in the payload
    assert data["estimated_date"] == "2026-01-05T00:00:00+05:30"
    assert [c["status"] for c in data["checkpoints"]] == ["InfoReceived", "OutForDelivery"]
    assert data["checkpoints"][0]["checkpoint_time"] == "2026-01-02T10:30:00+05:30"
    assert data["checkpoints"][1]["country_iso3"] == "IND"


@responses.activate
def test_ekart_tracker_end_to_end_with_date_only_values():
    responses.add(
        responses.POST,
        "https://ekartlogistics.com/ws/getTrackingDetails",
        json={
            "expectedDeliveryDate": "2026-01-05",
            "shipmentType": "FORWARD",
            "destinationCity": "Pune",
            "merchantName": "Acme",
            "receiverName": "Asha",
            "receiverRelationShip": "self",
            # Ekart lists scans oldest first; the last one is the current status
            "shipmentTrackingDetails": [
                {"statusDetails": "Shipment Created", "city": "Mumbai",
                 "instructions": "Created", "date": "2026-01-02T10:00:00"},
                {"statusDetails": "Delivered", "city": "Pune",
                 "instructions": "Handed over", "date": "2026-01-04"},
            ],
        },
    )
    result = get_track_data("ekart", "FMPP123")
    data = to_jsonable(result)
    assert data["status"] == "Delivered" and data["receiver_name"] == "Asha"
    assert data["estimated_date"] == "2026-01-05"  # stays a date
    # the tracker returns checkpoints newest first
    assert [c["checkpoint_time"] for c in data["checkpoints"]] == [
        "2026-01-04", "2026-01-02T10:00:00",
    ]
    assert "shipment_type" not in data and "receiver_relationship" not in data
