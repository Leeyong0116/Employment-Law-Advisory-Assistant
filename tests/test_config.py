"""Config integrity: the document registry drives every citation the system
emits, so it must stay consistent with what is actually on disk."""
import pathlib

import pytest
import yaml

CONFIG_PATH = pathlib.Path("config/config.yaml")


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def documents(cfg):
    return cfg["corpus"]["documents"]


def test_document_ids_are_unique(documents):
    ids = [d["id"] for d in documents]
    assert len(ids) == len(set(ids))


def test_every_document_has_citation_metadata(documents):
    # Act/citation and jurisdiction are both required to render a citation.
    for d in documents:
        assert d["act_number"], d["id"]
        assert d["short_name"], d["id"]
        assert d["jurisdiction"], d["id"]
        assert d["status"] in {"in_force", "not_yet_in_force", "repealed"}, d["id"]


def test_amending_documents_point_at_a_principal_document(documents):
    by_id = {d["id"]: d for d in documents}
    for d in documents:
        if d["doc_type"] != "amending":
            continue
        target = by_id.get(d["amends"])
        assert target is not None, f"{d['id']} amends unknown {d['amends']}"
        assert target["doc_type"] == "principal"
        assert target["jurisdiction"] == d["jurisdiction"]


def test_uncommenced_amendment_is_not_marked_in_force(documents):
    # Act A1754 has Royal Assent but no appointed commencement date. Marking it
    # in force would make the system present 98 days' maternity leave as the
    # current Sarawak position when 60 days is still operative.
    for d in documents:
        if d.get("commencement") is None and d["doc_type"] == "amending":
            assert d["status"] == "not_yet_in_force", d["id"]


def test_jurisdiction_notes_reference_known_documents(cfg, documents):
    ids = {d["id"] for d in documents}
    jurisdictions = {d["jurisdiction"] for d in documents}
    for jurisdiction, notes in cfg["jurisdiction_notes"].items():
        assert jurisdiction in jurisdictions
        for note in notes:
            assert note["source"] in ids
            assert note["note"].strip()


@pytest.mark.corpus
def test_registry_matches_the_pdfs_on_disk(cfg, documents):
    pymupdf = pytest.importorskip("pymupdf")
    raw = pathlib.Path(cfg["corpus"]["raw_dir"])
    if not any(raw.glob("*.pdf")):
        pytest.skip("source PDFs not present")
    for d in documents:
        path = raw / d["file"]
        assert path.exists(), f"{d['id']}: {path} missing"
        with pymupdf.open(path) as doc:
            assert doc.page_count == d["pages"], d["id"]


def test_amending_document_in_force_records_its_commencement_date(documents):
    # An amending Act is only in force once the Minister appoints a date under
    # its commencement clause. Requiring the date means the status cannot be
    # flipped on assumption — A1754's own text still reads "a date to be
    # appointed", so the evidence has to live here.
    for d in documents:
        if d["doc_type"] == "amending" and d["status"] == "in_force":
            assert d.get("commencement"), f"{d['id']} in force with no commencement date"


def test_commencement_exceptions_are_well_formed(documents):
    # Partial commencement: A1754 commenced on 1 May 2025 except the new
    # Part IVa, so one document carries two statuses.
    for d in documents:
        for exc in d.get("commencement_exceptions", []):
            assert exc["source_section"], d["id"]
            assert exc["status"] in {"in_force", "not_yet_in_force"}, d["id"]
            if exc["status"] == "not_yet_in_force":
                assert exc["commencement"] is None, d["id"]
            assert exc.get("inserts_part") or exc.get("subject"), d["id"]


def test_operative_jurisdiction_notes_carry_an_effective_date(cfg):
    for notes in cfg["jurisdiction_notes"].values():
        for note in notes:
            if note["status"] == "in_force":
                assert note.get("effective"), note["source"]


def test_only_sarawak_needs_amendment_linking(documents):
    # Sabah Cap. 67 (June 2026) is consolidated, so amends/amended_by linking is
    # a Sarawak-only concern. If a future corpus refresh adds an unconsolidated
    # principal text, this fails and the parser assumption gets revisited.
    unconsolidated = [
        d["id"] for d in documents
        if d["doc_type"] == "principal" and not d.get("consolidated")
    ]
    assert unconsolidated == ["labour_ordinance_sarawak"], unconsolidated


def test_documents_carry_every_listing1_citation_field(documents):
    # docs/chunk_schema.md Listing 1: these are copied verbatim onto each chunk,
    # so a missing one silently produces an uncitable chunk.
    for d in documents:
        assert d["short_name"], d["id"]          # -> chunk "statute"
        assert d["act_number"], d["id"]          # -> chunk "act_number"
        assert d["jurisdiction_label"], d["id"]  # -> chunk "jurisdiction"
        assert d["source_version"], d["id"]      # -> chunk "source_version"
        assert "source_url" in d, d["id"]        # may be null, must be declared
