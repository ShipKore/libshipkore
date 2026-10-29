import os

import pytest
import responses

from libshipkore.common.exceptions import ProviderError
from libshipkore.track import get_track_data

HERE = os.path.dirname(__file__)
URL = "https://trackon.in/courier-tracking"


def fixture(name):
    with open(os.path.join(HERE, "fixtures", name)) as handle:
        return handle.read()


@responses.activate
def test_trackon_reads_the_recorded_page():
    responses.add(responses.POST, URL, body=fixture("trackon_courier_tracking.html"))
    track = get_track_data("trackon", "100468264445")
    assert track.status.value == "Delivered" and track.substatus.startswith("DELIVERED")
    assert len(track.checkpoints) == 7
    newest, oldest = track.checkpoints[0], track.checkpoints[-1]
    assert newest.checkpoint_time.isoformat() == "2026-08-31T13:02:00+05:30"  # day/month/year
    assert newest.location == "W10608-LUCKNOW 5, UTTAR PRADESH"
    assert oldest.message.startswith("IN TRANSIT TO LUCKNOW 5")
    assert track.delivered_date == newest.checkpoint_time
    assert track.estimated_date.isoformat() == "2026-08-17T00:00:00+05:30"
    request = responses.calls[0].request
    assert request.headers["Referer"] == "https://trackon.in/"  # without it the site answers with no scans
    assert request.body == "awbSingleTrackingId=100468264445"


@responses.activate
def test_an_undelivered_scan_is_an_attempt_not_a_delivery():
    responses.add(responses.POST, URL, body=fixture("trackon_courier_tracking.html"))
    track = get_track_data("trackon", "100468264445")
    statuses = {c.message: c.status.value for c in track.checkpoints}
    assert statuses["UNDELIVERED DUE TO OUT OF DELIVERY AREA (ODA)"] == "AttemptFail"
    assert statuses["IN TRANSIT TO LUCKNOW 5"] == "InTransit"


@responses.activate
def test_no_record_says_so_instead_of_an_index_error():
    responses.add(responses.POST, URL, body=fixture("trackon_no_record.html"))
    with pytest.raises(ProviderError, match="no tracking record for 100444195039"):
        get_track_data("trackon", "100444195039")
