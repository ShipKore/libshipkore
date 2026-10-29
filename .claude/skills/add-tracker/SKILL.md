---
description: 'Add or fix a tracking-only integration for a courier in libshipkore: a scraper or API client that returns the standard Track. Use when asked to add, support or repair tracking for a courier, or when a tracker returns wrong data.'
when_to_use: 'Examples: "add tracking for Blue Dart", "the Ekart tracker returns Exception for everything", "support a new courier in track".'
argument-hint: "[courier name]"
---

# Add or fix a tracker

A tracker fetches one courier's tracking data and turns it into the standard `Track`. Booking is separate: see the `add-carrier` skill. Good models: `libshipkore/track/tracker/delhivery.py` (a Python tracker), `libshipkore/track/specs/amazon-shipping.json` (a spec over a plain request) and `libshipkore/track/specs/ekart.json` (a spec that reads the page's own request through a browser). Most of the other trackers have no tests, so do not assume they are right.

$ARGUMENTS

## 1. Find the best data source

The order of preference is fixed: **1. the courier's API** (needs credentials: a booking carrier in `libshipkore/book/carriers/`), **2. a direct request** to a public JSON endpoint (a tracker or spec), **3. the page in a browser** (`libshipkore/track/common/browser.py`, last resort). Use a lower layer only when the one above is not possible, and say why in the spec's `source`. A browser is for pages that build their request from scripts, cookies or a CSRF handshake; give the spec a `browser` block (`url` and `capture`) so it reads the page's own JSON call, or subclass `LayeredTracker` and define `fetch_api`, `fetch_request`, `fetch_browser`. Steps can close a popup (`"optional": true` on a click) and a block can set `"load_resources": true` for a page that never goes idle with its videos blocked (see `libshipkore/track/specs/safexpress.json`). Never solve a captcha, never copy a token out of a site's scripts. A site that answers a plain request or a headless browser with a bot-filter block (USPS) or a firewall error (India Post) is not tracked this way; list it as not supported with the reason. Prefer the courier's own tracking API over scraping its HTML. Look at what its public tracking page calls in the browser's network tab. Respect the site's terms and do not hammer it. Never put a login or token in the tracker: trackers take no credentials.

## 2. Write the tracker

**If the courier's endpoint returns plain JSON, write a spec, not a module.** Add `libshipkore/track/specs/<slug>.json` (format and an example in the docstring of `libshipkore/track/declarative.py`): URL, the path to the scans, which fields are time, message and location, and a map from the courier's status words to `StatusChoice`. It must say `source` and either `verified_on` (a real call you made) or `unverified: true`, or loading it fails. Also add the courier to `libshipkore/data/carriers.json` only if you have a fact to record (a `waybill_pattern` only when the number format is well known; a courier you cannot support gets `supported: false` and a `note` saying why, for example a captcha, which is never bypassed). Test it like a tracker (step 3). If you read the courier's own contact or coverage pages, also fill its profile in the directory (website, `phones`, `emails`, `categories`, `countries.primary` and `secondary`, `service_areas`) with `profile.sources` and `verified_on`; see `libshipkore/directory.py`. Never fill a fact from memory. Use a Python module only when the courier needs HTML parsing, a token, or logic.


Create `libshipkore/track/tracker/<module>.py`; every module in that folder is imported automatically. Use `libshipkore/track/common/basetrackservice.py` for the base class.

```python
@track_registry.register("<slug>")
class Acme(BaseTrackService):
    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "<slug>", *args, **kwargs)

    def _fetch(self):
        self.raw_data = requests.get(url, timeout=30).json()

    def _transform(self):
        ...
        self.data = data      # validated into a Track on assignment
        return data
```

- **The slug** is what users pass as `provider`. Use the same string in `super().__init__`; some old trackers do not (one registers `professional-couriers` but passes `professional_couriers`), so the `provider` on the returned `Track` disagrees with the slug the user passed.
- **`status_mapper`** returns one of `StatusChoice` in `libshipkore/track/models/model.py`. An unmapped courier status must become `Exception`, never raise. Map the reverse-flow statuses too (`ReverseInTransit`, `ReverseOutForDelivery`, `ReverseDelivered`) when the courier has returns.
- **Checkpoint keys:** `slug`, `city`, `location`, `country_name`, `message`, `submessage`, `country_iso3`, `status`, `substatus`, `checkpoint_time`, `state`, `zip`. Only `slug` and `checkpoint_time` are required. **Track keys:** `waybill`, `provider`, `status`, `substatus`, `estimated_date`, `reference_no`, `package_type`, `destination`, `client`, `consignee_address`, `product`, `receiver_name`, `delivered_date`, `checkpoints`. Extra keys are ignored.
- **Dates:** give a timezone offset when you know it (Indian couriers: append `+05:30`). A date-only string stays a date; that is deliberate. Do not invent a time.
- **Order:** checkpoints are not normalised; some trackers return newest first, others oldest first. Say which in a comment. Consumers sort by `checkpoint_time`.
- **Numbers** arriving where text belongs are fine (they become strings). A boolean is rejected.
- Always pass `timeout=` to `requests`. Leave no `print` calls behind (some old trackers still print the raw payload).
- If the courier has another name people use, add it to `ALTERNATIVE_PROVIDERS` in `libshipkore/track/__init__.py`. The value must be a registered slug; one existing alias pointed at a slug that did not exist.

## 3. Test it without the network

Add `tests/test_track_<slug>.py`, modelled on the end-to-end tests in `tests/test_track_contract.py`: mock the endpoint with `responses`, call `get_track_data("<slug>", waybill)`, and assert on `to_jsonable(result)`.

- Use a real payload copied from the courier, not one you made up, and say where it came from in the test's docstring. If you only have the documented shape, say that instead.
- Cover every status your mapper handles, an unknown status (must give `Exception`), a delivered shipment, a not-found waybill, and a date-only value if the courier sends one.
- A not-found waybill must not crash with a `KeyError`; decide what it should return and test it.

## 4. Verify

`get_provider("<slug>").capabilities` should now be `{"track"}` (`libshipkore/provider.py`). Run the full suite and `flake8 --ignore=E501,W503 libshipkore tests`. In your report, say whether the payload was real or only the documented shape, and that nothing has been run against the live site unless you did.
