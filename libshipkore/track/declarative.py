"""
Trackers described as data. A carrier whose public tracking endpoint returns
JSON needs no Python: one file in libshipkore/track/specs/ says where to
fetch, where the scans are and how its status words map to ours. Carriers
that need HTML parsing, tokens or logic stay as modules in track/tracker/.

A spec is JSON:

    {
      "slug": "acme", "name": "Acme Express", "country": "IN",
      "waybill_pattern": "^\\d{10}$",             optional, used by auto-detect
      "source": "where the shape was seen", "verified_on": "2026-01-01"
                                                   or "unverified": true,
      "request": {"method": "GET", "url": "https://x/{waybill}",
                  "headers": {}, "params": {}, "json": {}},
      "response": {
        "scans": "data.scans",                      dotted path; digits index lists;
                                                   "@json" parses a JSON string on the way
        "fields": {"time": "ts", "message": "desc", "location": "place",
                   "code": "status", "city": "city", "state": "state", "zip": "pin"},
        "status": "data.current",                   optional, else the newest scan's
        "estimated": "data.etd",                    optional
        "time_format": "%d-%m-%Y %H:%M",            optional, else ISO
        "timezone": "+05:30"                        added to times that carry none
      },
      "statuses": {"DELIVERED": "Delivered"},       words to StatusChoice names
      "status_prefixes": {"Out For": "OutForDelivery"}   optional: a word starting so
    }

Instead of (or after) "request", a spec can name a browser fallback for pages
that build their own request from scripts, cookies or a CSRF handshake:

      "browser": {"url": "https://x/track/{waybill}", "capture": "trackings/v2"}

The page is opened in a headless browser and the JSON of the request it makes
whose URL contains "capture" is read with the same "response" rules. Optional
"steps" ([{"fill": selector, "value": "{waybill}"}, {"click": selector}]) act
like a visitor first, for pages that only look a number up after a form submit. The order
is request first, browser only if that fails (see track/common/browser.py). A click step with
"optional": true is skipped when its element does not show (a popup that is not always
there). "load_resources": true in the browser block keeps images and media loading, for a page
that never goes idle without them. An answer that is empty or not JSON is tried once more.
"time_format" may be "epoch_ms" for millisecond timestamps; "estimated_format"
sets a different format for the estimate (default: the same).

{waybill} is replaced in the url, params, json and response paths. Anything missing from the
response becomes an empty field; an unmapped status word becomes Exception.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests

from libshipkore.common.exceptions import ProviderError
from libshipkore.track.common import browser
from libshipkore.track.common.basetrackservice import track_registry
from libshipkore.track.common.layered import LayeredTracker
from libshipkore.track.models.model import StatusChoice

SPEC_DIR = os.path.join(os.path.dirname(__file__), "specs")
TZ_SUFFIX = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")
REQUIRED = ("slug", "name", "response", "statuses")


def dig(value, path):
    """value["a"]["b"][0] for "a.b.0"; None as soon as the path leaves the data. "@json" parses a string."""
    for part in str(path).split("."):
        if part == "@json":  # the value is JSON inside a string
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                return None
        elif isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def fill(value, waybill):
    if isinstance(value, str):
        return value.replace("{waybill}", waybill)
    if isinstance(value, dict):
        return {k: fill(v, waybill) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, waybill) for v in value]
    return value


def check_spec(spec, source="spec"):
    missing = [key for key in REQUIRED if key not in spec]
    if missing:
        raise ValueError(f"{source}: missing {', '.join(missing)}")
    if not (spec.get("verified_on") or spec.get("unverified")):
        raise ValueError(f"{source}: say verified_on (a date) or unverified: true")
    if "source" not in spec:
        raise ValueError(f"{source}: say where the response shape was seen")
    if not (spec.get("request") or spec.get("browser")):
        raise ValueError(f"{source}: needs a request or a browser")
    for kind in ("request", "browser"):
        if spec.get(kind) and "{waybill}" not in json.dumps(spec[kind]):
            raise ValueError(f"{source}: the {kind} never uses {{waybill}}")
    if spec.get("browser") and not spec["browser"].get("capture"):
        raise ValueError(f"{source}: browser needs capture (part of the URL of the page's own request)")
    names = set(spec["statuses"].values()) | set(spec.get("status_prefixes", {}).values())
    bad = sorted(names - {s.value for s in StatusChoice})
    if bad:
        raise ValueError(f"{source}: unknown status names {bad}")
    if "scans" not in spec["response"] or "time" not in spec["response"].get("fields", {}):
        raise ValueError(f"{source}: response needs scans and fields.time")
    if spec.get("waybill_pattern"):
        re.compile(spec["waybill_pattern"])


def offset(text):
    """timezone("+05:30") as a tzinfo; UTC when absent."""
    match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", text or "")
    if not match:
        return timezone.utc
    delta = timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))
    return timezone(delta if match.group(1) == "+" else -delta)


def moment(text, response, format_key="time_format"):
    """A scan time as ISO text with an offset, from the spec's format and timezone."""
    if text is None or text == "":
        return None
    pattern = response.get(format_key) or (response.get("time_format") if format_key == "estimated_format" else None)
    if pattern == "epoch_ms":
        return datetime.fromtimestamp(int(text) / 1000, offset(response.get("timezone"))).isoformat()
    text = str(text).strip()
    if pattern:
        try:
            text = datetime.strptime(text, pattern).isoformat()
        except ValueError:
            datetime.fromisoformat(text.replace("Z", "+00:00"))  # already ISO, else this raises
    else:
        text = text.replace(" ", "T", 1) if re.match(r"\d{4}-\d{2}-\d{2} ", text) else text
    if len(text) > 10 and not TZ_SUFFIX.search(text) and response.get("timezone"):
        text += response["timezone"]
    return text


class DeclarativeTracker(LayeredTracker):
    spec = None  # set on each generated subclass

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, self.spec["slug"], *args, **kwargs)

    def fetch_request(self):
        request = self.spec.get("request")
        if not request:
            raise NotImplementedError("no direct request for this carrier")
        call = fill(request, self.waybill)
        response = requests.request(
            call.get("method", "GET"), call["url"], headers=call.get("headers"),
            params=call.get("params"), json=call.get("json"), timeout=30,
        )
        if not response.ok:
            raise ProviderError(self.provider, f"HTTP {response.status_code}",
                                status_code=response.status_code, body=response.text)
        try:
            return response.json()
        except ValueError:
            raise ProviderError(self.provider, "response was not JSON", body=response.text)

    def fetch_browser(self):
        page = self.spec.get("browser")
        if not page:
            raise NotImplementedError("no browser fallback for this carrier")
        call = fill(page, self.waybill)
        extra = {"block_resources": False} if call.get("load_resources") else {}
        return browser.capture_json(call["url"], call["capture"], call.get("steps"), **extra)

    def _status(self, word):
        if word is None:
            return StatusChoice.Exception.value
        word = str(word)
        name = self.spec["statuses"].get(word)
        if not name:
            lowered = word.lower()
            for prefix, mapped in self.spec.get("status_prefixes", {}).items():
                if lowered.startswith(prefix.lower()):
                    return mapped
        return name or StatusChoice.Exception.value

    @staticmethod
    def _estimate(value, rules):
        try:
            return moment(value, rules, "estimated_format")
        except ValueError:  # a delivery estimate we cannot read must not lose the scans
            return None

    def transform(self):
        rules = self.spec["response"]
        fields = rules["fields"]
        scans = dig(self.raw_data, fill(rules["scans"], self.waybill))
        if not scans:
            raise ProviderError(self.provider, f"no tracking data for {self.waybill}",
                                body=self.raw_data)
        checkpoints = []
        for scan in scans:
            word = dig(scan, fields["code"]) if "code" in fields else None
            checkpoints.append({
                "slug": self.provider,
                "city": dig(scan, fields["city"]) if "city" in fields else None,
                "location": dig(scan, fields["location"]) if "location" in fields else None,
                "state": dig(scan, fields["state"]) if "state" in fields else None,
                "zip": dig(scan, fields["zip"]) if "zip" in fields else None,
                "message": dig(scan, fields["message"]) if "message" in fields else None,
                "substatus": word,
                "status": self._status(word),
                "checkpoint_time": moment(dig(scan, fields["time"]), rules),
            })
        checkpoints = [c for c in checkpoints if c["checkpoint_time"]]
        checkpoints.sort(key=lambda c: c["checkpoint_time"], reverse=True)  # newest first
        current = dig(self.raw_data, fill(rules["status"], self.waybill)) if "status" in rules else None
        estimated = dig(self.raw_data, fill(rules["estimated"], self.waybill)) if "estimated" in rules else None
        self.data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self._status(current) if current is not None else checkpoints[0]["status"],
            "substatus": current if current is not None else checkpoints[0]["substatus"],
            "estimated_date": self._estimate(estimated, rules),
            "checkpoints": checkpoints,
        }
        return self.data


def load_specs(directory=SPEC_DIR):
    """Register every *.json spec in the directory; a bad spec fails loudly at import."""
    loaded = []
    if not os.path.isdir(directory):  # git does not keep an empty directory
        return loaded
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(directory, name)) as handle:
            spec = json.load(handle)
        check_spec(spec, name)
        cls = type(f"Spec_{spec['slug'].replace('-', '_')}", (DeclarativeTracker,), {"spec": spec})
        track_registry.register(spec["slug"])(cls)
        loaded.append(spec)
    return loaded
