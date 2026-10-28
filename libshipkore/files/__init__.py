import importlib
import os
from urllib.parse import urlparse
from libshipkore.common.exceptions import StorageError
from .base import FileStore
from .memory import MemoryFileStore
from .s3 import S3FileStore

__all__ = ["FileStore", "MemoryFileStore", "S3FileStore", "create_file_store"]

ENV_VAR = "LIBSHIPKORE_FILES"


def create_file_store(spec=None):
    """
    Build the file store from configuration. spec can be:

    - a FileStore instance, used as is
    - None: the LIBSHIPKORE_FILES environment variable if set, else None,
      meaning labels are not copied and only the provider's link is kept
    - "s3://bucket/optional/prefix": AWS credentials from the usual chain
    - "memory://": in-process, for tests
    - a dict {"backend": "s3" | "memory" | "pkg.mod.Class", ...options}, e.g.
      {"backend": "s3", "bucket": "labels", "endpoint_url": "https://minio:9000",
       "access_key": "...", "secret_key": "..."}
    """
    if isinstance(spec, FileStore):
        return spec
    if spec is None:
        spec = os.environ.get(ENV_VAR)
        if not spec:
            return None
    if isinstance(spec, dict):
        options = dict(spec)
        backend = options.pop("backend", None)
        if backend == "memory":
            return MemoryFileStore()
        if backend == "s3":
            return S3FileStore(**options)
        if backend:
            module, _, name = backend.rpartition(".")
            try:
                return getattr(importlib.import_module(module), name)(**options)
            except (ImportError, AttributeError, ValueError):
                raise StorageError(f"cannot import file backend '{backend}'")
        raise StorageError("file store config needs a 'backend'")
    if isinstance(spec, str):
        if spec.startswith("memory://"):
            return MemoryFileStore()
        if spec.startswith("s3://"):
            parsed = urlparse(spec)
            prefix = parsed.path.lstrip("/")
            if prefix and not prefix.endswith("/"):
                prefix += "/"
            return S3FileStore(parsed.netloc, prefix=prefix)
    raise StorageError(f"unsupported file store spec: {spec!r}")
