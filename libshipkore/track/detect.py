"""
The carrier directory and a guess at the carrier from a tracking number.

The directory (libshipkore/data/carriers.json) is ours: carriers we have
researched, whether tracking is built, and a number pattern only where the
format is well known. Every registered tracker is listed even if the file
forgets it, so the directory can never claim less than the library does.
"""
import json
import re
from importlib import resources

from libshipkore.track.common.basetrackservice import track_registry


def _load():
    text = resources.files("libshipkore").joinpath("data/carriers.json").read_text()
    entries = {entry["slug"]: dict(entry) for entry in json.loads(text)}
    for slug in track_registry.keys():
        entry = entries.setdefault(slug, {"slug": slug, "name": slug, "country": None})
        entry["supported"] = True
        spec = getattr(track_registry._classes[slug], "spec", None)
        if spec:
            entry.update(name=spec["name"], country=spec.get("country", entry.get("country")))
            if spec.get("waybill_pattern"):
                entry["waybill_pattern"] = spec["waybill_pattern"]
    return sorted(entries.values(), key=lambda e: e["slug"])


def search_carriers(query=None, country=None, supported=None, limit=50):
    """Directory entries whose slug or name contains query, newest filters first."""
    found = []
    for entry in _load():
        if query and query.lower() not in f"{entry['slug']} {entry['name']}".lower():
            continue
        if country and (entry.get("country") or "").upper() != country.upper():
            continue
        if supported is not None and entry["supported"] != supported:
            continue
        found.append({k: v for k, v in entry.items() if k != "waybill_pattern"})
    return found[:limit]


def detect_carriers(waybill):
    """Slugs of supported carriers whose known number format fits, best guess first."""
    waybill = str(waybill).strip()
    return [
        entry["slug"] for entry in _load()
        if entry["supported"] and entry.get("waybill_pattern")
        and re.fullmatch(entry["waybill_pattern"], waybill)
    ]
