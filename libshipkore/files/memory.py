from libshipkore.common.exceptions import NotFound
from .base import FileStore


class MemoryFileStore(FileStore):
    """In-process files for tests; not for production use."""

    def __init__(self):
        self.files = {}

    def put(self, key, content, content_type="application/pdf"):
        self.files[key] = (bytes(content), content_type)

    def get(self, key):
        try:
            return self.files[key][0]
        except KeyError:
            raise NotFound(f"no stored file '{key}'")

    def exists(self, key):
        return key in self.files

    def url(self, key, expires_in=3600):
        if key not in self.files:
            raise NotFound(f"no stored file '{key}'")
        return f"memory://{key}?expires_in={expires_in}"

    def delete(self, key):
        self.files.pop(key, None)
