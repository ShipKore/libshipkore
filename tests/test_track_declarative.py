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
    assert indian and all(
        c.get("country") == "IN" or "IN" in c.get("countries", {}).get("primary", []) for c in indian)
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


def test_a_missing_spec_directory_means_no_specs_not_a_crash(tmp_path):
    # the shipped directory is empty today, and git does not store empty directories
    assert declarative.load_specs(str(tmp_path / "absent")) == []


# the first shipped spec: Amazon Shipping India, from a recorded response ----

AMAZON = "https://track.amazon.in/api/tracker/TESTID123"


def amazon_fixture():
    import os
    with open(os.path.join(os.path.dirname(__file__), "fixtures", "amazon_shipping.json")) as handle:
        return {k: v for k, v in json.load(handle).items() if k != "_note"}


@responses.activate
def test_amazon_shipping_from_its_recorded_response():
    from libshipkore.track import get_track_data
    responses.add(responses.GET, AMAZON, json=amazon_fixture())
    track = get_track_data("amazon-shipping", "TESTID123")
    assert track.status.value == "Delivered" and len(track.checkpoints) == 14
    newest, oldest = track.checkpoints[0], track.checkpoints[-1]
    assert (newest.message, newest.checkpoint_time.isoformat()) == ("Delivered", "2026-10-01T16:14:24+05:30")
    assert oldest.status.value == "InfoReceived" and oldest.checkpoint_time.isoformat() == "2026-09-25T18:38:39+05:30"
    gurugram = [c for c in track.checkpoints if c.city == "Gurugram"][0]
    assert (gurugram.state, gurugram.zip) == ("Haryana", "122503")
    assert [c.status.value for c in track.checkpoints if c.message == "DeliveryAttempted"] == ["AttemptFail"]
    assert track.estimated_date.isoformat() == "2026-10-02T20:00:00+05:30"


@responses.activate
def test_amazon_shipping_not_found_is_a_provider_error():
    from libshipkore.track import get_track_data
    responses.add(responses.GET, AMAZON, json={"eventHistory": None, "progressTracker": "{}"})
    with pytest.raises(ProviderError, match="no tracking data"):
        get_track_data("amazon-shipping", "TESTID123")


def test_json_inside_a_string_is_unpacked_and_bad_json_is_empty():
    assert dig({"a": '{"b": [1, 2]}'}, "a.@json.b.1") == 2
    assert dig({"a": "not json"}, "a.@json.b") is None and dig({"a": None}, "a.@json") is None


def test_the_directory_marks_what_is_built():
    for name in ("amazon", "shadowfax", "ekart"):
        assert search_carriers(name)[0]["supported"] is True, name


def test_an_unreadable_estimate_loses_the_estimate_not_the_scans():
    spec = {**SPEC, "response": {**SPEC["response"], "estimated": "data.etd", "estimated_format": "%Y"}}
    cls = type("Spec_est", (DeclarativeTracker,), {"spec": spec})
    tracker = cls("AC123456")
    tracker.raw_data = {"data": {**BODY["data"], "etd": "soon"}}
    tracker.transform()
    assert tracker.data.estimated_date is None and len(tracker.data.checkpoints) == 3


# the profiles: website, contacts, categories, countries, service areas ------

def raw_entries():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "libshipkore", "data", "carriers.json")
    with open(path) as handle:
        return json.load(handle)


def test_every_directory_entry_is_valid_and_every_fact_has_a_source():
    from libshipkore.directory import Carrier
    for raw in raw_entries():
        carrier = Carrier(**raw)
        if carrier.website or carrier.phones or carrier.emails or carrier.countries:
            assert carrier.profile and carrier.profile.sources, carrier.slug
            assert carrier.profile.verified_on.year >= 2026, carrier.slug


@pytest.mark.parametrize("change,message", [
    ({"website": "x.test"}, "must be a URL"),
    ({"categories": ["fast"]}, "unknown categories"),
    ({"countries": {"primary": ["india"]}}, "two capital letters"),
    ({"country": "India"}, "two capital letters"),
    ({"emails": [{"address": "nobody", "label": "x"}]}, "not an email"),
    ({"phones": [{"number": "call us", "label": "x"}]}, "not a phone"),
    ({"profile": {"sources": ["x.test"], "verified_on": "2026-01-01"}}, "URLs of the courier"),
    ({"surprise": 1}, "surprise"),
])
def test_a_bad_profile_is_refused(change, message):
    from libshipkore.directory import Carrier
    base = {"slug": "x", "name": "X", "website": "https://x.test",
            "profile": {"sources": ["https://x.test/"], "verified_on": "2026-01-01"}}
    with pytest.raises(Exception, match=message):
        Carrier(**{**base, **change})


def test_facts_without_a_source_are_refused():
    from libshipkore.directory import Carrier
    with pytest.raises(Exception, match="need profile.sources"):
        Carrier(slug="x", name="X", website="https://x.test")
    Carrier(slug="x", name="X")  # nothing claimed, nothing to source


def test_search_by_category_and_by_primary_or_secondary_country(monkeypatch):
    from libshipkore.track import detect
    assert {c["slug"] for c in search_carriers(category="aggregator")} == {"ithink", "shiprocket"}
    assert "delhivery" in {c["slug"] for c in search_carriers(country="in", category="ptl_freight")}
    entries = [{"slug": "far", "name": "Far", "country": "DE", "supported": True,
                "countries": {"primary": ["DE"], "secondary": ["IN"]},
                "profile": {"sources": ["https://far.test/"], "verified_on": "2026-01-01"}}]
    monkeypatch.setattr(detect, "_load", lambda: entries)
    assert [c["slug"] for c in search_carriers(country="IN")] == ["far"]  # a secondary country counts
    assert search_carriers(country="FR") == []


def test_a_researched_entry_carries_its_contacts_and_provenance():
    from libshipkore.track.detect import get_carrier
    shiprocket = get_carrier("shiprocket")
    assert {"address": "support@shiprocket.in", "label": "customer support"} in shiprocket["emails"]
    assert shiprocket["profile"]["sources"][0].startswith("https://www.shiprocket.in")
    assert get_carrier("bluedart")["phones"][0]["number"] == "+912240611234"
    assert get_carrier("nonexistent") is None
    assert "countries" not in get_carrier("pitney-bowes")  # not researched: nothing is invented


def test_every_booking_carrier_is_in_the_directory():
    from libshipkore.book.base import carrier_registry
    assert set(carrier_registry.keys()) <= {c["slug"] for c in search_carriers(limit=1000)}
