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

from libshipkore.directory import Carrier
from libshipkore.track.common.basetrackservice import track_registry


def _load():
    text = resources.files("libshipkore").joinpath("data/carriers.json").read_text(encoding="utf-8")
    entries = {}
    for raw in json.loads(text):
        carrier = Carrier(**raw)  # a typo or an unsourced fact fails here, loudly
        entries[carrier.slug] = carrier.model_dump(mode="json", exclude_none=True)
    for slug in track_registry.keys():
        entry = entries.setdefault(slug, {"slug": slug, "name": slug})
        entry["supported"] = True
        spec = getattr(track_registry._classes[slug], "spec", None)
        if spec:
            entry.update(name=spec["name"])
            if spec.get("country"):
                entry["country"] = spec["country"]
            if spec.get("waybill_pattern"):
                entry["waybill_pattern"] = spec["waybill_pattern"]
    return sorted(entries.values(), key=lambda e: e["slug"])


def search_carriers(query=None, country=None, supported=None, category=None, limit=50):
    """
    Directory entries whose slug or name contains query. `country` matches
    where the courier is based or operates (primary or secondary).
    """
    found = []
    for entry in _load():
        if query and query.lower() not in f"{entry['slug']} {entry['name']}".lower():
            continue
        if country and not Carrier(**{k: v for k, v in entry.items()
                                      if k != "waybill_pattern"}).operates_in(country):
            continue
        if supported is not None and entry.get("supported", False) != supported:
            continue
        if category and category not in entry.get("categories", []):
            continue
        found.append({k: v for k, v in entry.items() if k != "waybill_pattern"})
    return found[:limit]


def get_carrier(slug):
    """One directory entry in full, or None."""
    return next((c for c in search_carriers(limit=100000) if c["slug"] == slug), None)


def detect_carriers(waybill):
    """Slugs of supported carriers whose known number format fits, best guess first."""
    waybill = str(waybill).strip()
    return [
        entry["slug"] for entry in _load()
        if entry["supported"] and entry.get("waybill_pattern")
        and re.fullmatch(entry["waybill_pattern"], waybill)
    ]
