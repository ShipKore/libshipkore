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
    def __init__(self, url, body, status=200):
        self.url, self._body, self.status = url, body, status

    def json(self):
        return self._body


class FakePage:
    def __init__(self, world):
        self.world = world

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

    def expect_response(self, predicate):
        world = self.world

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
                        lambda url, match: seen.append((url, match)) or recorded)
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
