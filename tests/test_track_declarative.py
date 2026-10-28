"""The data-described trackers, and the carrier directory with auto-detect."""

import json

import pytest
import responses

from libshipkore.common.exceptions import NotFound, ProviderError
from libshipkore.track import declarative, track_registry
from libshipkore.track.detect import detect_carriers, search_carriers
from libshipkore.track.declarative import DeclarativeTracker, check_spec, dig

SPEC = {
    "slug": "acme-test", "name": "Acme Test", "country": "IN",
    "waybill_pattern": "^AC\\d{6}$", "source": "invented for this test",
    "unverified": True,
    "request": {"method": "GET", "url": "https://acme.test/track/{waybill}"},
    "response": {
        "scans": "data.scans", "status": "data.state", "estimated": "data.etd",
        "fields": {"time": "at", "message": "what", "location": "where", "code": "code"},
        "time_format": "%d-%m-%Y %H:%M", "timezone": "+05:30",
    },
    "statuses": {"DEL": "Delivered", "OFD": "OutForDelivery", "PKD": "InTransit"},
}
BODY = {"data": {"state": "OFD", "etd": "2026-05-04T18:00:00", "scans": [
    {"at": "01-05-2026 10:00", "what": "Picked", "where": "Delhi", "code": "PKD"},
    {"at": "02-05-2026 08:15", "what": "Out", "where": "Pune", "code": "OFD"},
    {"at": "03-05-2026 09:00", "what": "Odd", "where": "Pune", "code": "WEIRD"},
]}}


@pytest.fixture
def acme():
    cls = type("Spec_acme", (DeclarativeTracker,), {"spec": SPEC})
    return cls("AC123456")


@responses.activate
def test_a_spec_becomes_a_working_tracker(acme):
    responses.add(responses.GET, "https://acme.test/track/AC123456", json=BODY)
    track = acme.run()
    assert track.provider == "acme-test" and track.status.value == "OutForDelivery"
    assert [c.message for c in track.checkpoints] == ["Odd", "Out", "Picked"]  # newest first
    assert track.checkpoints[1].checkpoint_time.isoformat() == "2026-05-02T08:15:00+05:30"
    assert track.checkpoints[0].status.value == "Exception"  # an unmapped word never raises
    assert track.estimated_date.isoformat() == "2026-05-04T18:00:00+05:30"


@responses.activate
def test_no_scans_or_a_failed_request_is_a_provider_error(acme):
    responses.add(responses.GET, "https://acme.test/track/AC123456", json={"data": {}})
    with pytest.raises(ProviderError, match="no tracking data"):
        acme.run()
    responses.replace(responses.GET, "https://acme.test/track/AC123456", status=500)
    with pytest.raises(ProviderError, match="HTTP 500"):
        acme.run()


def test_dig_follows_dicts_and_list_indexes_and_never_raises():
    data = {"a": [{"b": 5}]}
    assert dig(data, "a.0.b") == 5
    assert dig(data, "a.1.b") is None and dig(data, "x.y") is None and dig(data, "a.b") is None


@pytest.mark.parametrize("change,message", [
    ({"statuses": {"X": "Nonsense"}}, "unknown status"),
    ({"unverified": None}, "verified_on"),
    ({"source": None}, "where the response shape"),
    ({"request": {"url": "https://x"}}, "never uses"),
    ({"waybill_pattern": "("}, None),
])
def test_a_bad_spec_is_refused_at_load(change, message):
    spec = {**SPEC, **change}
    if "source" in change:
        spec.pop("source")
    with pytest.raises(Exception, match=message):
        check_spec(spec)


def test_specs_in_a_directory_are_registered(tmp_path):
    (tmp_path / "x.json").write_text(json.dumps({**SPEC, "slug": "dir-test"}))
    (tmp_path / "ignored.txt").write_text("not json")
    try:
        assert [s["slug"] for s in declarative.load_specs(str(tmp_path))] == ["dir-test"]
        assert "dir-test" in track_registry
        assert search_carriers("dir-test")[0]["name"] == "Acme Test"
        assert detect_carriers("AC000001") == ["dir-test"]
    finally:
        track_registry._classes.pop("dir-test")


def test_every_shipped_spec_loads_and_names_its_source():
    # load_specs ran at import; a bad spec would have failed `import libshipkore`
    for slug in track_registry:
        spec = getattr(track_registry._classes[slug], "spec", None)
        if spec:
            check_spec(spec, slug)


# directory -----------------------------------------------------------------

def test_the_directory_lists_every_tracker_and_the_known_gaps():
    everything = search_carriers(limit=1000)
    slugs = [c["slug"] for c in everything]
    assert len(slugs) == len(set(slugs))
    assert set(track_registry.keys()) <= set(slugs)
    assert all(c["supported"] for c in everything if c["slug"] in track_registry)
    xpressbees = search_carriers("xpressbees")[0]
    assert xpressbees["supported"] is False and "captcha" in xpressbees["note"]


def test_search_filters_by_name_country_and_support():
    assert {c["slug"] for c in search_carriers("blue")} == {"bluedart"}
    indian = search_carriers(country="in")
    assert indian and all(c["country"] == "IN" for c in indian)
    assert all(not c["supported"] for c in search_carriers(supported=False))
    assert "waybill_pattern" not in indian[0]


def test_detect_only_offers_supported_carriers_with_a_matching_format():
    assert detect_carriers("123456789012") == ["fedex"]
    assert detect_carriers("1Z999AA10123456784") == []  # UPS: known format, tracking not built
    assert detect_carriers("hello") == []


def test_shipkore_guesses_the_carrier_or_says_why_it_cannot(monkeypatch):
    from libshipkore.client import Shipkore
    calls = []
    monkeypatch.setattr(Shipkore, "track", lambda self, w, p=None, refresh=False:
                        calls.append((w, p)) or "tracked" if p else Shipkore._track_detected(self, w, refresh))
    kore = Shipkore()
    assert kore.track("123456789012") == "tracked" and calls == [("123456789012", "fedex")]
    with pytest.raises(ValueError, match="cannot tell the carrier"):
        kore.track("not-a-number")


def test_every_candidate_failing_is_reported(monkeypatch):
    from libshipkore.client import Shipkore
    kore = Shipkore()
    monkeypatch.setattr(kore, "provider", lambda slug: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(NotFound, match="fedex: down"):
        kore.track("123456789012")
