"""Tests for src/indexing/store.py.

Row mapping is tested without a database. The database tests (marker `db`)
need `docker compose up -d` and are skipped when PostgreSQL is not running.
"""
import pytest

from src.indexing import store

CHUNK = {
    "chunk_id": "EA1955_s59_1", "doc_id": "employment_act_1955", "statute": "Employment Act 1955",
    "jurisdiction": "Peninsular Malaysia and Labuan", "section": "59", "chunk_type": "provision",
    "status": "in_force", "citation": "Employment Act 1955, s. 59(1)",
    "content": "Every employee shall be allowed in each week a rest day", "source_page": 53,
}


class TestChunkRow:
    def test_filter_columns_and_full_metadata(self):
        row = store.chunk_row(CHUNK, [0.1] * 4, {"12": 0.3}, "v1")
        assert row["chunk_id"] == "EA1955_s59_1"
        assert row["jurisdiction"] == "Peninsular Malaysia and Labuan"
        assert row["content"] == CHUNK["content"]
        assert row["metadata"]["source_page"] == 53
        assert row["index_version"] == "v1"

    def test_embedding_is_a_plain_list_of_floats(self):
        row = store.chunk_row(CHUNK, (0.5, 0.25), {}, "v1")
        assert row["embedding"] == [0.5, 0.25]


@pytest.fixture
def db():
    import yaml

    config = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
    try:
        conn = store.connect(config)
    except Exception as error:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"PostgreSQL not available: {error}")
    chunk_store = store.ChunkStore(conn, dim=4, table="chunks_test")
    chunk_store.ensure_schema()
    yield chunk_store
    conn.execute("DROP TABLE IF EXISTS chunks_test")
    conn.commit()
    conn.close()


def _rows(version):
    sabah = dict(CHUNK, chunk_id="SBH67_s104B_1", jurisdiction="Sabah", doc_id="labour_ordinance_sabah")
    ira = dict(CHUNK, chunk_id="IRA1967_s5_1", jurisdiction="Malaysia", doc_id="industrial_relations_act_1967")
    return [
        store.chunk_row(CHUNK, [1, 0, 0, 0], {}, version),
        store.chunk_row(sabah, [0.9, 0.1, 0, 0], {}, version),
        store.chunk_row(ira, [0, 1, 0, 0], {}, version),
    ]


@pytest.mark.db
class TestChunkStore:
    def test_upsert_and_count(self, db):
        db.upsert(_rows("v1"))
        assert db.count("v1") == 3

    def test_upsert_is_idempotent(self, db):
        db.upsert(_rows("v1"))
        db.upsert(_rows("v1"))
        assert db.count("v1") == 3

    def test_dense_search_orders_by_similarity(self, db):
        db.upsert(_rows("v1"))
        hits = db.dense_search([1, 0, 0, 0], k=3, index_version="v1")
        assert [h[0] for h in hits] == ["EA1955_s59_1", "SBH67_s104B_1", "IRA1967_s5_1"]
        assert hits[0][1] == pytest.approx(1.0)

    def test_jurisdiction_filter_is_applied_in_sql(self, db):
        db.upsert(_rows("v1"))
        hits = db.dense_search([1, 0, 0, 0], k=3, jurisdictions=["Sabah", "Malaysia"], index_version="v1")
        assert [h[0] for h in hits] == ["SBH67_s104B_1", "IRA1967_s5_1"]

    def test_stale_versions_are_removed(self, db):
        db.upsert(_rows("v1"))
        db.upsert([dict(r, index_version="v2") for r in _rows("v2")[:1]])
        removed = db.delete_other_versions("v2")
        assert removed == 2 and db.count("v2") == 1
