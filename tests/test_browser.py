"""
The browser fallback and the order of preference. No test starts a browser: a
fake stands in for Playwright, so these need neither it nor Chrome installed.
"""

import json
import os
import sys
import types

import pytest

from libshipkore.common.exceptions import ProviderError
from libshipkore.track import get_track_data
from libshipkore.track.common import browser
from libshipkore.track.common.basetrackservice import track_registry
from libshipkore.track.common.layered import LayeredTracker

HERE = os.path.dirname(__file__)


class FakeTimeoutError(Exception):
    pass


FakeTimeoutError.__name__ = "TimeoutError"  # what Playwright's is called


class FakeResponse:
    def __init__(self, url, body, status=200, method="GET"):
        self.url, self._body, self.status = url, body, status
        self.request = types.SimpleNamespace(method=method)

    def json(self):
        return self._body


class FakePage:
    def __init__(self, world):
        self.world = world
        self.context = types.SimpleNamespace(expect_event=self.expect_event)

    def route(self, pattern, handler):
        self.world["routes"].append(handler)

    def goto(self, url, wait_until=None):
        self.world["visited"].append(url)

    def content(self):
        return "<html>rendered</html>"

    def wait_for_selector(self, selector):
        if self.world.get("never"):
            raise FakeTimeoutError("waiting")
        self.world["waited"] = selector

    def wait_for_load_state(self, state):
        self.world["settled"] = state

    def fill(self, selector, value):
        self.world.setdefault("acts", []).append(("fill", selector, value))

    def click(self, selector, timeout=None):
        if selector in self.world.get("absent", ()):
            raise FakeTimeoutError(f"no {selector}")
        self.world.setdefault("acts", []).append(("click", selector))

    def expect_event(self, name, predicate):
        world = self.world
        assert name == "response"  # the context-wide event, so a tab the page opens is seen too

        class Seen:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                if world.get("never"):
                    raise FakeTimeoutError("no response")
                self.value = next(r for r in world["responses"] if predicate(r))
                return False

        return Seen()


@pytest.fixture
def playwright(monkeypatch):
    """A fake playwright.sync_api; `world` records what the code asked of it."""
    world = {"launch": None, "visited": [], "routes": [], "closed": False, "responses": []}

    class Browser:
        def new_context(self):
            return types.SimpleNamespace(
                set_default_timeout=lambda ms: world.update(timeout=ms),
                new_page=lambda: FakePage(world),
            )

        def close(self):
            world["closed"] = True

    class Chromium:
        def launch(self, **options):
            world["launch"] = options
            if world.get("cannot_start"):
                raise RuntimeError("Executable doesn't exist")
            return Browser()

    class Manager:
        chromium = Chromium()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: Manager()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    for name in ("LIBSHIPKORE_BROWSER_CHANNEL", "LIBSHIPKORE_BROWSER_PATH"):
        monkeypatch.delenv(name, raising=False)
    return world


# the browser helper --------------------------------------------------------

def test_without_playwright_the_error_says_how_to_get_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(browser.BrowserUnavailable, match=r"libshipkore\[browser\].*playwright install chromium"):
        browser.render("https://x.test")


def test_capture_json_returns_what_the_page_itself_fetched(playwright):
    playwright["responses"] = [
        FakeResponse("https://x.test/other", {"no": 1}),
        FakeResponse("https://x.test/api/trackings/v2", {"yes": 1}),
    ]
    assert browser.capture_json("https://x.test/track/1", "trackings/v2") == {"yes": 1}
    assert playwright["visited"] == ["https://x.test/track/1"] and playwright["closed"]
    assert "acts" not in playwright and "settled" not in playwright  # no steps, no waiting around


def test_steps_act_like_a_visitor_after_the_page_has_settled(playwright):
    playwright["responses"] = [FakeResponse("https://api.test/track/AWB1/", {"ok": 1})]
    steps = [{"fill": "#awb", "value": "AWB1"}, {"click": "button"}]
    assert browser.capture_json("https://x.test", "/track/", steps) == {"ok": 1}
    assert playwright["settled"] == "networkidle"
    assert playwright["acts"] == [("fill", "#awb", "AWB1"), ("click", "button")]
    with pytest.raises(ValueError, match="unknown browser step"):
        browser.capture_json("https://x.test", "/track/", [{"hover": "a"}])


def test_a_cors_preflight_is_not_taken_for_the_answer(playwright):
    playwright["responses"] = [
        FakeResponse("https://api.test/track/AWB1/", {}, method="OPTIONS"),
        FakeResponse("https://api.test/track/AWB1/", {"ok": 1}, method="POST"),
    ]
    assert browser.capture_json("https://x.test", "/track/") == {"ok": 1}


def test_an_empty_answer_is_tried_once_more(playwright):
    class Empty(FakeResponse):
        def json(self):
            raise json.JSONDecodeError("Expecting value", "", 0)

    playwright["responses"] = [Empty("https://api.test/track/AWB1/", None)]
    with pytest.raises(json.JSONDecodeError):
        browser.capture_json("https://x.test", "/track/")
    assert playwright["visited"] == ["https://x.test", "https://x.test"]  # two attempts, then it gives up


def test_an_optional_click_is_skipped_when_the_popup_is_not_there(playwright):
    playwright["responses"] = [FakeResponse("https://api.test/track/AWB1/", {"ok": 1})]
    playwright["absent"] = {".popup"}
    steps = [{"click": ".popup", "optional": True}, {"fill": "#awb", "value": "AWB1"}]
    assert browser.capture_json("https://x.test", "/track/", steps) == {"ok": 1}
    assert playwright["acts"] == [("fill", "#awb", "AWB1")]
    playwright["absent"] = {".popup"}  # a click that is not optional still fails
    with pytest.raises(browser.BrowserTimeout):
        browser.capture_json("https://x.test", "/track/", [{"click": ".popup"}])


def test_a_failed_response_is_not_taken_for_the_answer(playwright):
    playwright["responses"] = [FakeResponse("https://x.test/trackings/v2", {"err": 1}, status=500)]
    with pytest.raises(StopIteration):  # the fake found no 200; a real page would time out
        browser.capture_json("https://x.test", "trackings/v2")


def test_render_waits_for_the_selector_and_returns_html(playwright):
    assert browser.render("https://x.test", wait_for="#result") == "<html>rendered</html>"
    assert playwright["waited"] == "#result"


def test_a_page_that_never_shows_up_is_a_timeout_not_a_hang(playwright):
    playwright["never"] = True
    with pytest.raises(browser.BrowserTimeout, match="matching 'trackings'"):
        browser.capture_json("https://x.test", "trackings")
    with pytest.raises(browser.BrowserTimeout, match="#result"):
        browser.render("https://x.test", wait_for="#result")
    assert playwright["closed"]  # and the browser is always closed


def test_images_media_and_fonts_are_not_loaded(playwright):
    browser.render("https://x.test")
    handler = playwright["routes"][0]
    calls = []

    def route(kind):
        return types.SimpleNamespace(
            request=types.SimpleNamespace(resource_type=kind),
            abort=lambda: calls.append(("abort", kind)),
            continue_=lambda: calls.append(("continue", kind)),
        )

    for kind in ("image", "font", "media", "document", "xhr"):
        handler(route(kind))
    assert calls == [("abort", "image"), ("abort", "font"), ("abort", "media"),
                     ("continue", "document"), ("continue", "xhr")]


def test_the_browser_to_use_comes_from_the_environment(playwright, monkeypatch):
    browser.render("https://x.test")
    assert playwright["launch"] == {"headless": True}
    monkeypatch.setenv("LIBSHIPKORE_BROWSER_CHANNEL", "chrome")
    browser.render("https://x.test")
    assert playwright["launch"] == {"headless": True, "channel": "chrome"}
    monkeypatch.setenv("LIBSHIPKORE_BROWSER_PATH", "/opt/chromium")
    browser.render("https://x.test")
    assert playwright["launch"] == {"headless": True, "executable_path": "/opt/chromium"}


def test_a_browser_that_cannot_start_says_what_to_do(playwright):
    playwright["cannot_start"] = True
    with pytest.raises(browser.BrowserUnavailable, match="playwright install chromium"):
        browser.render("https://x.test")


# the order of preference ---------------------------------------------------

class Layers(LayeredTracker):
    def __init__(self, waybill, calls, broken=(), **kwargs):
        super().__init__(waybill, "layers", **kwargs)
        self.calls, self.broken = calls, broken

    def _try(self, name):
        self.calls.append(name)
        if name in self.broken:
            raise RuntimeError(f"{name} down")
        return {"via": name}

    def fetch_browser(self):  # defined first on purpose: order must not depend on it
        return self._try("browser")

    def fetch_request(self):
        return self._try("request")

    def fetch_api(self):
        return self._try("api")

    def transform(self):
        self.data = {"waybill": self.waybill, "provider": "layers", "checkpoints": []}


@pytest.mark.parametrize("broken,tried,used", [
    ((), ["api"], "api"),
    (("api",), ["api", "request"], "request"),
    (("api", "request"), ["api", "request", "browser"], "browser"),
])
def test_api_then_direct_request_then_browser(broken, tried, used):
    calls = []
    tracker = Layers("W1", calls, broken)
    tracker.run()
    assert calls == tried and tracker.strategy == used and tracker.raw_data == {"via": used}


def test_when_every_layer_fails_the_error_names_each():
    tracker = Layers("W1", [], ("api", "request", "browser"))
    with pytest.raises(ProviderError) as error:
        tracker.run()
    text = str(error.value)
    assert "api: RuntimeError: api down" in text and "browser: RuntimeError: browser down" in text


def test_transform_follows_the_strategy_that_won():
    class Two(Layers):
        def transform_request(self):
            self.data = {"waybill": "W", "provider": "layers", "checkpoints": [], "substatus": "request-way"}

    tracker = Two("W", [], ("api",))
    assert tracker.run().substatus == "request-way"


# Ekart: the browser reads the page's own request ---------------------------

def test_ekart_tracks_through_the_browser_from_a_recorded_response(monkeypatch):
    with open(os.path.join(HERE, "fixtures", "ekart_trackings_v2.json")) as handle:
        recorded = {k: v for k, v in json.load(handle).items() if k != "_note"}
    seen = []
    monkeypatch.setattr(browser, "capture_json",
                        lambda url, match, steps=None: seen.append((url, match)) or recorded)
    track = get_track_data("ekart", "TESTEKART1")
    assert seen == [("https://ekartlogistics.com/shipmenttrack/TESTEKART1", "trackings/v2")]
    assert track.provider == "ekart" and len(track.checkpoints) == 10
    assert track.status.value == "OutForDelivery" and track.substatus == "Out For Delivery"
    assert track.checkpoints[0].checkpoint_time.isoformat() == "2026-10-29T09:21:01+05:30"
    attempt = [c for c in track.checkpoints if c.message.startswith("Unsuccessful")][0]
    assert attempt.status.value == "AttemptFail"
    assert track.checkpoints[-1].status.value == "InfoReceived" and track.checkpoints[-1].city == "Lucknow"
    assert track.estimated_date.isoformat() == "2026-10-26T23:00:00+05:30"


def test_ekart_without_a_browser_says_how_to_get_one(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(ProviderError, match=r"libshipkore\[browser\]"):
        get_track_data("ekart", "TESTEKART1")


def test_the_old_ekart_scraper_is_gone_and_the_spec_is_registered():
    assert "ekart" in track_registry
    assert track_registry._classes["ekart"].__module__ == "libshipkore.track.declarative"


@pytest.mark.skipif(not os.environ.get("LIBSHIPKORE_LIVE_BROWSER"),
                    reason="needs a browser and the network: set LIBSHIPKORE_LIVE_BROWSER=<real Ekart id>")
def test_live_ekart_in_a_real_browser():
    track = get_track_data("ekart", os.environ["LIBSHIPKORE_LIVE_BROWSER"])
    assert track.checkpoints


def test_shadowfax_fills_the_form_then_reads_the_pages_own_call(monkeypatch):
    with open(os.path.join(HERE, "fixtures", "shadowfax_track.json")) as handle:
        recorded = {k: v for k, v in json.load(handle).items() if k != "_note"}
    seen = []
    monkeypatch.setattr(browser, "capture_json",
                        lambda url, match, steps=None: seen.append((url, match, steps)) or recorded)
    track = get_track_data("shadowfax", "TESTSF1")
    url, match, steps = seen[0]
    assert url == "https://www.shadowfax.in/track" and match == "/web_app/delivery/track/"
    assert steps[0] == {"fill": "input[placeholder='Enter AWB Number']", "value": "TESTSF1"}  # the waybill is filled in
    assert track.status.value == "AttemptFail" and track.substatus == "Delivery Attempt Unsucessful"
    assert track.checkpoints[0].checkpoint_time.isoformat() == "2026-10-28T21:26:20+05:30"
    assert track.checkpoints[0].message.startswith("Delivery attempt failed")
    assert track.estimated_date.isoformat() == "2026-10-28T00:00:00+05:30"


def test_safexpress_closes_the_popup_then_reads_the_pages_own_call(monkeypatch):
    with open(os.path.join(HERE, "fixtures", "safexpress_trackingbytype.json")) as handle:
        recorded = {k: v for k, v in json.load(handle).items() if k != "_note"}
    seen = []
    monkeypatch.setattr(browser, "capture_json",
                        lambda url, match, steps=None, **extra: seen.append((url, match, steps, extra)) or recorded)
    track = get_track_data("safexpress", "100035812989")
    url, match, steps, extra = seen[0]
    assert url == "https://www.safexpress.com/" and match.endswith("/trackingbytype")
    assert extra == {"block_resources": False}  # its videos keep the page busy when blocked
    assert steps[0].get("optional") is True and steps[1]["value"] == "100035812989"
    assert track.status.value == "Delivered" and track.substatus == "DELIVERED"
    assert len(track.checkpoints) == 13
    assert track.checkpoints[0].checkpoint_time.isoformat() == "2026-05-16T23:59:59+05:30"
    statuses = {c.substatus: c.status.value for c in track.checkpoints}
    assert statuses["UN-DELIVERED"] == "AttemptFail" and statuses["BOOKED"] == "InfoReceived"


def test_the_old_safexpress_scraper_is_gone_and_the_spec_is_registered():
    import libshipkore.track.tracker as tracker_package
    assert not os.path.exists(os.path.join(os.path.dirname(tracker_package.__file__), "safexpress.py"))
    assert "safexpress" in track_registry


def test_dtdc_is_not_claimed_the_directory_says_why():
    from libshipkore.track.detect import search_carriers
    dtdc = search_carriers("dtdc")[0]
    assert dtdc["supported"] is False and "captcha" in dtdc["note"] and "dtdc" not in track_registry
