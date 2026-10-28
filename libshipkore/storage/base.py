from abc import ABC, abstractmethod


def matches(document, filters):
    """True when every filter key equals the document's top-level value."""
    return all(document.get(k) == v for k, v in (filters or {}).items())


class Storage(ABC):
    """
    The database layer: JSON documents grouped in collections and found by
    key. Documents are plain JSON-serialisable dicts, so any backend (SQL,
    Redis, Mongo, Firebase) can implement it. Implement these four methods
    to plug in your own.

    Collections used by the library: orders, products, tracking, labels,
    responses.
    """

    @abstractmethod
    def put(self, collection, key, document):
        """Insert or replace one document."""

    @abstractmethod
    def get(self, collection, key):
        """The document, or None."""

    @abstractmethod
    def delete(self, collection, key):
        """Remove a document; True if it existed."""

    @abstractmethod
    def list(self, collection, filters=None, limit=None, offset=0):
        """
        Documents whose top-level fields equal every filter, most recently
        written first.
        """

    def close(self):
        pass
