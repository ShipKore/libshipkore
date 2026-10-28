import json
import sqlite3
import threading
import time
from libshipkore.common.exceptions import StorageError
from .base import Storage, matches


class SQLiteStorage(Storage):
    """
    A single SQLite file, with no dependency beyond the standard library.
    Use ":memory:" for a throwaway database. Filters are applied in Python
    after reading the collection, which is fine for thousands of rows, not
    millions; use SQLAlchemyStorage with an indexed schema beyond that.
    """

    def __init__(self, path=":memory:"):
        self.path = path
        self._lock = threading.Lock()
        try:
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS documents ("
                "collection TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL, "
                "written_at REAL NOT NULL, PRIMARY KEY (collection, key))"
            )
            self._db.commit()
        except sqlite3.Error as error:
            raise StorageError(f"cannot open sqlite database {path}: {error}")

    def put(self, collection, key, document):
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?)",
                (collection, key, json.dumps(document), time.time()),
            )

    def get(self, collection, key):
        with self._lock:
            row = self._db.execute(
                "SELECT data FROM documents WHERE collection=? AND key=?",
                (collection, key),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def delete(self, collection, key):
        with self._lock, self._db:
            cursor = self._db.execute(
                "DELETE FROM documents WHERE collection=? AND key=?",
                (collection, key),
            )
        return cursor.rowcount > 0

    def list(self, collection, filters=None, limit=None, offset=0):
        with self._lock:
            rows = self._db.execute(
                "SELECT data FROM documents WHERE collection=? "
                "ORDER BY written_at DESC, rowid DESC",
                (collection,),
            ).fetchall()
        docs = [d for d in (json.loads(r[0]) for r in rows) if matches(d, filters)]
        end = None if limit is None else offset + limit
        return docs[offset:end]

    def close(self):
        with self._lock:
            self._db.close()
