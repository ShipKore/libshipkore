import json
import time
from libshipkore.common.exceptions import StorageError
from .base import Storage, matches


class SQLAlchemyStorage(Storage):
    """
    Any database SQLAlchemy supports (Postgres, MySQL, SQLite...) from a
    connection URL. Needs `pip install libshipkore[sql]`. One `documents`
    table is created if missing. Filters are applied in Python after
    reading the collection, as with SQLiteStorage.
    """

    def __init__(self, url, **engine_options):
        try:
            import sqlalchemy as sa
        except ImportError:
            raise StorageError(
                "SQLAlchemyStorage needs sqlalchemy: pip install libshipkore[sql]"
            )
        self._sa = sa
        self.engine = sa.create_engine(url, **engine_options)
        meta = sa.MetaData()
        self.table = sa.Table(
            "documents",
            meta,
            sa.Column("collection", sa.String(64), primary_key=True),
            sa.Column("key", sa.String(255), primary_key=True),
            sa.Column("data", sa.Text, nullable=False),
            sa.Column("written_at", sa.Float, nullable=False),
        )
        try:
            meta.create_all(self.engine)
        except sa.exc.SQLAlchemyError as error:
            raise StorageError(f"cannot prepare the documents table: {error}")

    def _where(self, collection, key=None):
        clause = self.table.c.collection == collection
        if key is not None:
            clause = clause & (self.table.c.key == key)
        return clause

    def put(self, collection, key, document):
        t = self.table
        values = {"data": json.dumps(document), "written_at": time.time()}
        with self.engine.begin() as conn:
            updated = conn.execute(
                t.update().where(self._where(collection, key)).values(**values)
            )
            if updated.rowcount == 0:
                conn.execute(
                    t.insert().values(collection=collection, key=key, **values)
                )

    def get(self, collection, key):
        with self.engine.connect() as conn:
            row = conn.execute(
                self._sa.select(self.table.c.data).where(
                    self._where(collection, key)
                )
            ).first()
        return json.loads(row[0]) if row else None

    def delete(self, collection, key):
        with self.engine.begin() as conn:
            result = conn.execute(
                self.table.delete().where(self._where(collection, key))
            )
        return result.rowcount > 0

    def list(self, collection, filters=None, limit=None, offset=0):
        query = (
            self._sa.select(self.table.c.data)
            .where(self._where(collection))
            .order_by(self.table.c.written_at.desc())
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        docs = [d for d in (json.loads(r[0]) for r in rows) if matches(d, filters)]
        end = None if limit is None else offset + limit
        return docs[offset:end]

    def close(self):
        self.engine.dispose()
