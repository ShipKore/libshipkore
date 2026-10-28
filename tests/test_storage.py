"""Tests for the document storage layer and its configuration."""

import sys

import pytest

from libshipkore.common.exceptions import StorageError
from libshipkore.storage import (
    MemoryStorage,
    SQLiteStorage,
    Storage,
    create_storage,
)


@pytest.fixture(params=["memory", "sqlite", "sqlalchemy"])
def storage(request, tmp_path):
    if request.param == "memory":
        store = MemoryStorage()
    elif request.param == "sqlite":
        store = SQLiteStorage(str(tmp_path / "s.db"))
    else:
        pytest.importorskip("sqlalchemy")
        store = create_storage(f"sqlite+pysqlite:///{tmp_path / 'sa.db'}")
    yield store
    store.close()


def test_put_get_replace_delete(storage):
    assert storage.get("orders", "1") is None
    storage.put("orders", "1", {"a": 1, "nested": {"b": [1, 2]}})
    assert storage.get("orders", "1") == {"a": 1, "nested": {"b": [1, 2]}}
    storage.put("orders", "1", {"a": 2})
    assert storage.get("orders", "1") == {"a": 2}
    assert storage.delete("orders", "1") is True
    assert storage.delete("orders", "1") is False
    assert storage.get("orders", "1") is None


def test_collections_are_separate(storage):
    storage.put("orders", "1", {"x": "order"})
    storage.put("products", "1", {"x": "product"})
    assert storage.get("orders", "1") == {"x": "order"}
    assert storage.get("products", "1") == {"x": "product"}
    assert len(storage.list("orders")) == 1


def test_list_newest_first_with_paging(storage):
    for i in range(5):
        storage.put("orders", str(i), {"n": i})
    assert [d["n"] for d in storage.list("orders")] == [4, 3, 2, 1, 0]
    assert [d["n"] for d in storage.list("orders", limit=2)] == [4, 3]
    assert [d["n"] for d in storage.list("orders", limit=2, offset=2)] == [2, 1]
    storage.put("orders", "0", {"n": 0})  # rewriting moves it to the front
    assert storage.list("orders", limit=1)[0]["n"] == 0


def test_list_filters_on_top_level_equality(storage):
    storage.put("orders", "1", {"provider": "delhivery", "status": "Booked"})
    storage.put("orders", "2", {"provider": "shiprocket", "status": "Booked"})
    storage.put("orders", "3", {"provider": "delhivery", "status": "Failed"})
    found = storage.list("orders", {"provider": "delhivery", "status": "Booked"})
    assert [d["provider"] for d in found] == ["delhivery"]
    assert len(storage.list("orders", {"provider": "none"})) == 0


def test_documents_are_copied_not_shared(storage):
    doc = {"items": [1]}
    storage.put("orders", "1", doc)
    doc["items"].append(2)
    stored = storage.get("orders", "1")
    assert stored == {"items": [1]}
    stored["items"].append(3)
    assert storage.get("orders", "1") == {"items": [1]}


@pytest.mark.parametrize("kind", ["sqlite", "sqlalchemy"])
def test_data_survives_reopening(kind, tmp_path):
    if kind == "sqlalchemy":
        pytest.importorskip("sqlalchemy")
        url = f"sqlite+pysqlite:///{tmp_path / 'p.db'}"
    else:
        url = f"sqlite:///{tmp_path / 'p.db'}"
    first = create_storage(url)
    first.put("orders", "1", {"a": 1})
    first.close()
    second = create_storage(url)
    assert second.get("orders", "1") == {"a": 1}
    second.close()


def test_create_storage_from_urls_dicts_and_instances(tmp_path):
    assert isinstance(create_storage("memory://"), MemoryStorage)
    assert isinstance(create_storage(None), MemoryStorage)
    sqlite = create_storage(f"sqlite:///{tmp_path}/x.db")
    assert isinstance(sqlite, SQLiteStorage) and sqlite.path == f"{tmp_path}/x.db"
    assert create_storage("sqlite://:memory:").path == ":memory:"
    assert isinstance(create_storage({"backend": "memory"}), MemoryStorage)
    from_dict = create_storage({"backend": "sqlite", "path": str(tmp_path / "d.db")})
    assert isinstance(from_dict, SQLiteStorage)
    instance = MemoryStorage()
    assert create_storage(instance) is instance


def test_create_storage_reads_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LIBSHIPKORE_STORAGE", f"sqlite:///{tmp_path}/e.db")
    assert isinstance(create_storage(), SQLiteStorage)


class DictStorage(Storage):
    """A custom backend, as a user would write one."""

    def __init__(self, prefix=""):
        self.prefix = prefix
        self.data = {}

    def put(self, collection, key, document):
        self.data[(collection, key)] = document

    def get(self, collection, key):
        return self.data.get((collection, key))

    def delete(self, collection, key):
        return self.data.pop((collection, key), None) is not None

    def list(self, collection, filters=None, limit=None, offset=0):
        return [d for (c, _), d in self.data.items() if c == collection]


def test_custom_backend_by_dotted_path():
    store = create_storage(
        {"backend": "tests.test_storage.DictStorage", "prefix": "p"}
    )
    assert isinstance(store, DictStorage) and store.prefix == "p"


@pytest.mark.parametrize("spec", [
    "nonsense", 42, {"no": "backend"}, {"backend": "nothing.here.Missing"},
    {"backend": "Plain"},
])
def test_bad_specs_raise(spec):
    with pytest.raises(StorageError):
        create_storage(spec)


def test_sqlalchemy_missing_gives_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "sqlalchemy", None)
    with pytest.raises(StorageError, match=r"libshipkore\[sql\]"):
        create_storage("postgresql://user@host/db")
