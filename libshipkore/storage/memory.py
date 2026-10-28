import json
import threading
from .base import Storage, matches


class MemoryStorage(Storage):
    """Process-local storage for tests and scripts; nothing is persisted."""

    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()

    def put(self, collection, key, document):
        with self._lock:
            docs = self._data.setdefault(collection, {})
            # re-insert so the most recently written document sorts first
            docs.pop(key, None)
            docs[key] = json.dumps(document)

    def get(self, collection, key):
        with self._lock:
            raw = self._data.get(collection, {}).get(key)
        return json.loads(raw) if raw is not None else None

    def delete(self, collection, key):
        with self._lock:
            return self._data.get(collection, {}).pop(key, None) is not None

    def list(self, collection, filters=None, limit=None, offset=0):
        with self._lock:
            raws = list(self._data.get(collection, {}).values())
        docs = [d for d in map(json.loads, reversed(raws)) if matches(d, filters)]
        end = None if limit is None else offset + limit
        return docs[offset:end]
