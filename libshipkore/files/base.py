from abc import ABC, abstractmethod


class FileStore(ABC):
    """
    Where binary files such as label PDFs live, kept apart from the
    document database. The shipped backend is S3 compatible; implement
    these methods for anything else.
    """

    @abstractmethod
    def put(self, key, content, content_type="application/pdf"):
        """Store bytes under key, replacing any existing file."""

    @abstractmethod
    def get(self, key):
        """The bytes; raises NotFound when there is no such file."""

    @abstractmethod
    def exists(self, key):
        """True when a file is stored under key."""

    @abstractmethod
    def url(self, key, expires_in=3600):
        """A link to download the file, valid for expires_in seconds."""

    @abstractmethod
    def delete(self, key):
        """Remove the file; a missing file is not an error."""
