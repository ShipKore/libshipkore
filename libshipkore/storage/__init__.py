import importlib
import os
from libshipkore.common.exceptions import StorageError
from .base import Storage
from .memory import MemoryStorage
from .sqlite import SQLiteStorage

__all__ = ["Storage", "MemoryStorage", "SQLiteStorage", "create_storage"]

ENV_VAR = "LIBSHIPKORE_STORAGE"


def _load(dotted):
    module, _, name = dotted.rpartition(".")
    if not module:
        raise StorageError(f"unknown storage backend '{dotted}'")
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError):
        raise StorageError(f"cannot import storage backend '{dotted}'")


def create_storage(spec=None):
    """
    Build the storage from configuration. spec can be:

    - a Storage instance, used as is
    - None: the LIBSHIPKORE_STORAGE environment variable, else in-memory
    - a URL: "memory://", "sqlite:///relative.db", "sqlite:////abs/path.db",
      "sqlite://:memory:", or any SQLAlchemy URL such as "postgresql://..."
    - a dict {"backend": "memory" | "sqlite" | "sqlalchemy" | "pkg.mod.Class",
      ...options}, so a custom Storage subclass can be configured by name
    """
    if isinstance(spec, Storage):
        return spec
    if spec is None:
        spec = os.environ.get(ENV_VAR) or "memory://"
    if isinstance(spec, dict):
        options = dict(spec)
        backend = options.pop("backend", None)
        if backend == "memory":
            return MemoryStorage()
        if backend == "sqlite":
            return SQLiteStorage(**options)
        if backend == "sqlalchemy":
            from .sql import SQLAlchemyStorage
            return SQLAlchemyStorage(**options)
        if backend:
            return _load(backend)(**options)
        raise StorageError("storage config needs a 'backend'")
    if not isinstance(spec, str):
        raise StorageError(f"unsupported storage spec: {spec!r}")
    if spec.startswith("memory://"):
        return MemoryStorage()
    if spec.startswith("sqlite:///"):
        return SQLiteStorage(spec[len("sqlite:///"):] or ":memory:")
    if spec == "sqlite://:memory:":
        return SQLiteStorage(":memory:")
    if "://" in spec:
        from .sql import SQLAlchemyStorage
        return SQLAlchemyStorage(spec)
    raise StorageError(f"unsupported storage spec: {spec!r}")
