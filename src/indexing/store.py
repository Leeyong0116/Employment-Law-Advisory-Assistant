"""PostgreSQL + pgvector store for the chunks.

One row per chunk: the filter columns, the content, every chunk field in
`metadata` (jsonb), the bge-m3 dense vector, and bge-m3's learned sparse
weights (kept for the alternative sparse configuration).

Search is exact cosine distance with no approximate (HNSW) index: 1,852
vectors scan in milliseconds, and an approximate index can drop rows once a
jurisdiction filter applies. Equal distances are broken by chunk_id, so
results are deterministic. The jurisdiction filter runs inside the SQL
query, as CLAUDE.md requires.
"""

from __future__ import annotations

import os
from typing import Sequence

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

_FILTER_COLUMNS = ("doc_id", "jurisdiction", "statute", "section", "chunk_type", "status", "citation")


def connect(config: dict) -> psycopg.Connection:
    """Open a connection to the local index database (password from .env).

    DB_HOST / DB_PORT override the config, so the same code connects from
    Windows (127.0.0.1) and from the ML container (the "db" service).
    """
    load_dotenv()
    db = config["database"]
    conn = psycopg.connect(
        host=os.environ.get("DB_HOST", db["host"]), port=int(os.environ.get("DB_PORT", db["port"])),
        dbname=db["name"], user=db["user"],
        password=os.environ[db["password_env"]], connect_timeout=3,
    )
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.commit()
    register_vector(conn)
    return conn


def chunk_row(chunk: dict, embedding: Sequence[float], sparse: dict, index_version: str) -> dict:
    """The table row for one chunk."""
    row = {column: chunk.get(column) for column in _FILTER_COLUMNS}
    row.update(
        chunk_id=chunk["chunk_id"],
        content=chunk["content"],
        metadata=chunk,
        embedding=[float(x) for x in embedding],
        sparse={str(k): float(v) for k, v in sparse.items()},
        index_version=index_version,
    )
    return row


class ChunkStore:
    def __init__(self, conn: psycopg.Connection, dim: int, table: str = "chunks"):
        self.conn, self.dim, self.table = conn, dim, table

    def ensure_schema(self) -> None:
        t = self.table
        self.conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {t} (
                chunk_id      text PRIMARY KEY,
                doc_id        text NOT NULL,
                jurisdiction  text NOT NULL,
                statute       text NOT NULL,
                section       text,
                chunk_type    text NOT NULL,
                status        text NOT NULL,
                citation      text NOT NULL,
                content       text NOT NULL,
                metadata      jsonb NOT NULL,
                embedding     vector({self.dim}) NOT NULL,
                sparse        jsonb,
                index_version text NOT NULL
            )"""
        )
        for column in ("jurisdiction", "doc_id", "status", "index_version"):
            self.conn.execute(f"CREATE INDEX IF NOT EXISTS {t}_{column} ON {t} ({column})")
        self.conn.commit()

    def upsert(self, rows: list[dict]) -> None:
        columns = (*_FILTER_COLUMNS, "chunk_id", "content", "metadata", "embedding", "sparse", "index_version")
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "chunk_id")
        sql = (
            f"INSERT INTO {self.table} ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))}) "
            f"ON CONFLICT (chunk_id) DO UPDATE SET {updates}"
        )
        values = [
            tuple(Jsonb(row[c]) if c in ("metadata", "sparse") else row[c] for c in columns)
            for row in rows
        ]
        with self.conn.cursor() as cursor:
            cursor.executemany(sql, values)
        self.conn.commit()

    def delete_other_versions(self, index_version: str) -> int:
        cursor = self.conn.execute(f"DELETE FROM {self.table} WHERE index_version <> %s", (index_version,))
        self.conn.commit()
        return cursor.rowcount

    def count(self, index_version: str) -> int:
        return self.conn.execute(
            f"SELECT count(*) FROM {self.table} WHERE index_version = %s", (index_version,)
        ).fetchone()[0]

    def dense_search(
        self,
        vector: Sequence[float],
        k: int = 20,
        jurisdictions: list[str] | None = None,
        index_version: str | None = None,
    ) -> list[tuple[str, float]]:
        """Top k (chunk_id, cosine similarity), filtered in SQL."""
        import numpy as np

        query_vector = np.asarray(vector, dtype=np.float32)
        conditions, params = [], []
        if jurisdictions is not None:
            conditions.append("jurisdiction = ANY(%s)")
            params.append(list(jurisdictions))
        if index_version is not None:
            conditions.append("index_version = %s")
            params.append(index_version)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self.conn.execute(
            f"SELECT chunk_id, 1 - (embedding <=> %s) AS score FROM {self.table} {where} "
            "ORDER BY embedding <=> %s, chunk_id LIMIT %s",
            (query_vector, *params, query_vector, k),
        ).fetchall()
        return [(chunk_id, float(score)) for chunk_id, score in rows]
