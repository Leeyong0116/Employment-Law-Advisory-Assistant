"""Tests for src/indexing/build.py, with a fake embedder and an in-memory store.

The real model and database are exercised by the smoke checks
(src/indexing/smoke.py), not here.
"""
import json

from src.indexing import build


class FakeEmbedder:
    def __init__(self):
        self.calls = 0
        self.closed = False

    def encode(self, texts):
        self.calls += 1
        return [[float(len(t)), 1.0] for t in texts], [{"7": 0.5} for _ in texts]

    def close(self):
        self.closed = True


class FakeStore:
    def __init__(self):
        self.rows = {}

    def ensure_schema(self):
        pass

    def upsert(self, rows):
        self.rows.update({r["chunk_id"]: r for r in rows})

    def delete_other_versions(self, version):
        stale = [k for k, r in self.rows.items() if r["index_version"] != version]
        for k in stale:
            del self.rows[k]
        return len(stale)

    def count(self, version):
        return sum(r["index_version"] == version for r in self.rows.values())


def _chunks(n=3):
    return [
        {"chunk_id": f"EA_s{i}", "doc_id": "ea", "statute": "EA", "jurisdiction": "Peninsular Malaysia and Labuan",
         "section": str(i), "chunk_type": "provision", "status": "in_force", "citation": f"EA, s. {i}",
         "section_title": None, "content": f"provision number {i} about annual leave"}
        for i in range(n)
    ]


def _write(tmp_path, chunks):
    path = tmp_path / "chunks.jsonl"
    path.write_text("".join(json.dumps(c) + "\n" for c in chunks), encoding="utf-8")
    return path


def test_index_version_changes_with_the_chunks(tmp_path):
    a = build.index_version(_write(tmp_path, _chunks(3)))
    b = build.index_version(_write(tmp_path, _chunks(4)))
    assert a != b and len(a) == 12


def test_a_build_fills_the_store_bm25_and_manifest(tmp_path):
    path = _write(tmp_path, _chunks())
    store, embedder = FakeStore(), FakeEmbedder()
    manifest = build.build_index(path, embedder, store, tmp_path / "bm25", tmp_path / "manifest.json", model="fake")
    assert store.count(manifest["index_version"]) == 3
    assert (tmp_path / "bm25" / "chunks.json").exists()
    assert json.loads((tmp_path / "manifest.json").read_text())["chunks"] == 3
    assert embedder.closed, "the model must release the GPU before anything else loads"


def test_only_content_is_embedded(tmp_path):
    seen = []

    class Recorder(FakeEmbedder):
        def encode(self, texts):
            seen.extend(texts)
            return super().encode(texts)

    build.build_index(_write(tmp_path, _chunks(1)), Recorder(), FakeStore(), tmp_path / "bm25",
                      tmp_path / "m.json", model="fake")
    assert seen == ["provision number 0 about annual leave"]


def test_an_unchanged_build_is_skipped(tmp_path):
    path = _write(tmp_path, _chunks())
    store = FakeStore()
    build.build_index(path, FakeEmbedder(), store, tmp_path / "bm25", tmp_path / "m.json", model="fake")
    second = FakeEmbedder()
    manifest = build.build_index(path, second, store, tmp_path / "bm25", tmp_path / "m.json", model="fake")
    assert manifest["skipped"] is True and second.calls == 0


def test_a_new_corpus_replaces_the_old_rows(tmp_path):
    store = FakeStore()
    build.build_index(_write(tmp_path, _chunks(3)), FakeEmbedder(), store, tmp_path / "bm25", tmp_path / "m.json",
                      model="fake")
    manifest = build.build_index(_write(tmp_path, _chunks(2)), FakeEmbedder(), store, tmp_path / "bm25",
                                 tmp_path / "m.json", model="fake")
    assert len(store.rows) == 2 and manifest["removed_stale_rows"] == 1
