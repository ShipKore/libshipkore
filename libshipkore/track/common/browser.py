"""
A real browser, for the last resort. Order of preference for tracking is:

    1. the courier's API (with credentials)      book/carriers/*.py
    2. a direct HTTP request to a public endpoint requests, in a tracker or a spec
    3. the courier's page in a browser           this module

A browser is slower (about a second to start), heavier, and breaks when a
page is redesigned, so it is used only when the first two are not possible:
the page builds its request from scripts, cookies or a CSRF handshake that a
plain request cannot reproduce. It acts like any visitor: it loads the
public page and reads what the page itself shows or fetches. It does not
solve captchas, copy tokens out of a site's scripts, or hide that it is
automated.

Needs the optional extra (pip install "libshipkore[browser]") and a browser:
either Google Chrome installed (set LIBSHIPKORE_BROWSER_CHANNEL=chrome) or
Playwright's own (playwright install chromium). LIBSHIPKORE_BROWSER_PATH
points at any Chromium-family executable instead.
"""
import os
from contextlib import contextmanager

from libshipkore.common.exceptions import ShipkoreError

DEFAULT_TIMEOUT_MS = 30000
OPTIONAL_STEP_MS = 3000
BLOCKED_RESOURCES = {"image", "media", "font"}


class BrowserUnavailable(ShipkoreError):
    """Playwright or a browser is not installed, or could not start."""


class BrowserTimeout(ShipkoreError):
    """The page did not show or fetch what was expected in time."""


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserUnavailable(
            "browser tracking needs the optional extra: pip install "
            '"libshipkore[browser]", then either install Google Chrome and set '
            "LIBSHIPKORE_BROWSER_CHANNEL=chrome, or run: playwright install chromium"
        ) from None
    return sync_playwright


@contextmanager
def browser_page(timeout_ms=DEFAULT_TIMEOUT_MS, block_resources=True):
    """
    A fresh page in a fresh, isolated browser context (no shared cookies),
    closed on exit. Images, media and fonts are not loaded unless asked.
    """
    start = _playwright()
    with start() as playwright:
        options = {"headless": True}
        if os.environ.get("LIBSHIPKORE_BROWSER_PATH"):
            options["executable_path"] = os.environ["LIBSHIPKORE_BROWSER_PATH"]
        elif os.environ.get("LIBSHIPKORE_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LIBSHIPKORE_BROWSER_CHANNEL"]
        try:
            browser = playwright.chromium.launch(**options)
        except Exception as error:
            raise BrowserUnavailable(
                f"could not start the browser ({type(error).__name__}); install one with "
                "'playwright install chromium' or set LIBSHIPKORE_BROWSER_CHANNEL=chrome"
            ) from error
        try:
            context = browser.new_context()
            context.set_default_timeout(timeout_ms)
            page = context.new_page()
            if block_resources:
                page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in BLOCKED_RESOURCES
                    else route.continue_(),
                )
            yield page
        finally:
            browser.close()


def _timeout_error(error):
    return type(error).__name__ == "TimeoutError"


def render(url, wait_for=None, timeout_ms=DEFAULT_TIMEOUT_MS):
    """The page's HTML after its scripts ran; wait_for is a CSS selector to wait for."""
    with browser_page(timeout_ms) as page:
        try:
            page.goto(url, wait_until="domcontentloaded")
            if wait_for:
                page.wait_for_selector(wait_for)
            return page.content()
        except Exception as error:
            if _timeout_error(error):
                raise BrowserTimeout(f"{url} did not show {wait_for or 'its content'} in time") from error
            raise


def capture_json(url, match, steps=None, timeout_ms=DEFAULT_TIMEOUT_MS,
                 block_resources=True):
    """
    _capture_json, tried once more if the page's answer was empty or not JSON:
    some servers answer a lookup with a 200 and no body now and then.
    """
    try:
        return _capture_json(url, match, steps, timeout_ms, block_resources)
    except ValueError as error:  # json.JSONDecodeError; an unknown step is also a ValueError
        if "unknown browser step" in str(error):
            raise
    return _capture_json(url, match, steps, timeout_ms, block_resources)


def _capture_json(url, match, steps, timeout_ms, block_resources):
    """
    Load a page and return the JSON body of the first request the page itself
    makes (in any tab it opens) whose URL contains `match`. The page builds
    the request (cookies, CSRF tokens, headers); we only read the answer.

    `steps` act like a visitor on the page first: {"fill": selector, "value": text}
    types into a field and {"click": selector} presses a button; with
    "optional": true a click is skipped if the element does not appear (a
    popup that is not always there). Images, media and fonts are not loaded
    unless block_resources is False, which a page that never goes idle
    without them (it keeps retrying blocked videos) needs.
    """
    with browser_page(timeout_ms, block_resources) as page:
        try:
            with page.context.expect_event(
                "response",
                # a CORS preflight (OPTIONS) answers 200 with no body: not the data
                lambda response: match in response.url and response.status == 200
                and response.request.method != "OPTIONS",
            ) as seen:
                page.goto(url, wait_until="domcontentloaded")
                if steps:
                    try:
                        page.wait_for_load_state("networkidle")  # let the page's scripts attach
                    except Exception as error:
                        # some pages never go quiet (polling, retries); try the steps anyway
                        if not _timeout_error(error):
                            raise
                for step in steps or []:
                    if "fill" in step:
                        page.fill(step["fill"], step["value"])
                    elif "click" in step and step.get("optional"):
                        # a popup that may not show up: skip it when it does not
                        try:
                            page.click(step["click"], timeout=OPTIONAL_STEP_MS)
                        except Exception:
                            pass
                    elif "click" in step:
                        page.click(step["click"])
                    else:
                        raise ValueError(f"unknown browser step {step}")
            return seen.value.json()
        except Exception as error:
            if _timeout_error(error):
                raise BrowserTimeout(f"{url} made no request matching '{match}' in time") from error
            raise
