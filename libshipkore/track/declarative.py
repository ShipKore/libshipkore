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
        "scans": "data.scans",                      dotted path; digits index lists
        "fields": {"time": "ts", "message": "desc", "location": "place",
                   "code": "status", "city": "city", "state": "state", "zip": "pin"},
        "status": "data.current",                   optional, else the newest scan's
        "estimated": "data.etd",                    optional
        "time_format": "%d-%m-%Y %H:%M",            optional, else ISO
        "timezone": "+05:30"                        added to times that carry none
      },
      "statuses": {"DELIVERED": "Delivered"}        words to StatusChoice names
    }

{waybill} is replaced in the url, params and json. Anything missing from the
response becomes an empty field; an unmapped status word becomes Exception.
"""
import json
import os
import re
from datetime import datetime

import requests

from libshipkore.common.exceptions import ProviderError
from libshipkore.track.common.basetrackservice import BaseTrackService, track_registry
from libshipkore.track.models.model import StatusChoice

SPEC_DIR = os.path.join(os.path.dirname(__file__), "specs")
TZ_SUFFIX = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")
REQUIRED = ("slug", "name", "request", "response", "statuses")


def dig(value, path):
    """value["a"]["b"][0] for "a.b.0"; None as soon as the path leaves the data."""
    for part in str(path).split("."):
        if isinstance(value, dict):
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
    return value


def check_spec(spec, source="spec"):
    missing = [key for key in REQUIRED if key not in spec]
    if missing:
        raise ValueError(f"{source}: missing {', '.join(missing)}")
    if not (spec.get("verified_on") or spec.get("unverified")):
        raise ValueError(f"{source}: say verified_on (a date) or unverified: true")
    if "source" not in spec:
        raise ValueError(f"{source}: say where the response shape was seen")
    if "{waybill}" not in json.dumps(spec["request"]):
        raise ValueError(f"{source}: the request never uses {{waybill}}")
    bad = sorted(set(spec["statuses"].values()) - {s.value for s in StatusChoice})
    if bad:
        raise ValueError(f"{source}: unknown status names {bad}")
    if "scans" not in spec["response"] or "time" not in spec["response"].get("fields", {}):
        raise ValueError(f"{source}: response needs scans and fields.time")
    if spec.get("waybill_pattern"):
        re.compile(spec["waybill_pattern"])


def moment(text, response):
    """A scan time as ISO text with an offset, from the spec's format and timezone."""
    if text is None or text == "":
        return None
    text = str(text).strip()
    if response.get("time_format"):
        try:
            text = datetime.strptime(text, response["time_format"]).isoformat()
        except ValueError:
            datetime.fromisoformat(text.replace("Z", "+00:00"))  # already ISO, else this raises
    else:
        text = text.replace(" ", "T", 1) if re.match(r"\d{4}-\d{2}-\d{2} ", text) else text
    if len(text) > 10 and not TZ_SUFFIX.search(text) and response.get("timezone"):
        text += response["timezone"]
    return text


class DeclarativeTracker(BaseTrackService):
    spec = None  # set on each generated subclass

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, self.spec["slug"], *args, **kwargs)

    def _fetch(self):
        request = self.spec["request"]
        call = fill(request, self.waybill)
        response = requests.request(
            call.get("method", "GET"), call["url"], headers=call.get("headers"),
            params=call.get("params"), json=call.get("json"), timeout=30,
        )
        if not response.ok:
            raise ProviderError(self.provider, f"HTTP {response.status_code}",
                                status_code=response.status_code, body=response.text)
        try:
            self.raw_data = response.json()
        except ValueError:
            raise ProviderError(self.provider, "response was not JSON", body=response.text)

    def _status(self, word):
        name = self.spec["statuses"].get(str(word)) if word is not None else None
        return name or StatusChoice.Exception.value

    def _transform(self):
        rules = self.spec["response"]
        fields = rules["fields"]
        scans = dig(self.raw_data, rules["scans"])
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
        current = dig(self.raw_data, rules["status"]) if "status" in rules else None
        self.data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self._status(current) if current is not None else checkpoints[0]["status"],
            "substatus": current if current is not None else checkpoints[0]["substatus"],
            "estimated_date": moment(dig(self.raw_data, rules["estimated"]), rules)
            if "estimated" in rules else None,
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
