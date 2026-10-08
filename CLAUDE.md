

Claude · MD
# CLAUDE.md: GetRight (Malaysian Employment Law RAG Chatbot)
 
## What this project is
 

Title: "AI-Powered Employment Rights Advisory Chatbot Using Retrieval-Augmented Generation (RAG)". Frontend app name: GetRight.
 
The system answers English questions about Malaysian employment law. Every answer is grounded in retrieved statutory text and cites the exact provision (Act, Part, Section, Subsection) so the user can check the source.
 

## Core contribution (protect this in every design choice)
 
1. **Citation traceability.** Every substantive statement links to a specific provision. Citations come from **chunk metadata**, never from text the LLM generates.
2. **Traceability, not verification.** We do not prove the cited provision legally supports the claim. We measure faithfulness, not legal correctness. Keep this distinction in code comments, docs, and report wording.
3. **Abstention gate.** If no retrieved chunk passes a calibrated reranker score threshold, do NOT generate. Return an "out of scope" notice listing the statutes we hold. A confident answer with wrong citations is the worst failure mode.
4. **Jurisdiction awareness.** EA 1955 does not apply in Sabah or Sarawak. Citing EA to a Sabah user is wrong even if the entitlement is the same.
## Corpus (official English PDFs only)
 
| Instrument | Territory | Source | Text state |
|---|---|---|---|
| Employment Act 1955 (Act 265) | Peninsular Malaysia and Labuan | AGC (lom.agc.gov.my) | Consolidated as at 1 Jan 2023 |
| Industrial Relations Act 1967 (Act 177) | Whole of Malaysia | AGC | Consolidated as at 1 Nov 2021 |
| Labour Ordinance Sabah Cap. 67 | Sabah | Sabah SAGC | Consolidated incl. 2025 amendments |
| Labour Ordinance Sarawak Cap. 76 | Sarawak | Sarawak LawNet | Principal text only (1958 ed., amended to 2006) |
| Labour Ordinance of Sarawak (Amendment) Act 2025 (Act A1754) | Sarawak | Sarawak Labour Dept | Amending instrument, in force 1 May 2025 |
 
Rules:
- Sarawak principal text and Act A1754 are indexed as **separate documents**, linked in metadata, so an amended provision is retrieved with its amendment. Do NOT build a merged consolidated text. Example: Sarawak s.84 says 60 days maternity leave, but A1754 changed it to 98.
- Every chunk stores its consolidation date and source page/URL.
- Out of scope for the corpus: Minimum Wages Order, EPF Act, SOCSO Act, Minimum Retirement Age Act, Workmen's Compensation Act, Children and Young Persons Act, case law (Industrial Court awards).
## Architecture (deterministic Advanced RAG)
 
Offline indexing:
1. **Ingestion**: PyMuPDF text extraction, keep headings, numbering, page numbers.
2. **Chunking**: custom rule-based section parser. Boundary = subsection (smallest complete legal rule). Short undivided section = one chunk. No fixed-length splitters.
3. **Embedding**: bge-m3 (8192 token limit, dense + sparse, multilingual).
4. **Storage**: PostgreSQL + pgvector. Text, metadata and vector in one record.
Online query:
5. **Hybrid retrieval**: dense (bge-m3) + sparse (BM25), with metadata filter on jurisdiction and statute inside the SQL query.
6. **Reranking**: bge-reranker-large cross-encoder.
7. **Abstention gate**: reranker score threshold.
8. **Prompt + generation**: top chunks + query + fixed rules (advisory tone, answer only from context, no recommendations). Model: Qwen3-14B, 4-bit, no fine-tuning.
9. **Response**: answer and citations are **separate typed fields**. Citations built from chunk metadata.
 
Not allowed: agentic RAG, GraphRAG, Modular RAG, self-RAG. They make retrieval non-deterministic, which breaks citation traceability and makes RAGAS comparisons invalid. Cross-references are handled as metadata instead of a graph.
 
## Chunk schema (from CP1 Listing 1, field names are canonical)
 
```json
{
  "chunk_id": "EA1955_s59_1",
  "statute": "Employment Act 1955",
  "act_number": "Act 265",
  "part": "Part XII",
  "part_title": "Rest Day, Hours of Work, Holidays and Other Conditions of Service",
  "section": "59",
  "section_title": "Rest day",
  "subsection": "(1)",
  "citation": "Employment Act 1955, s. 59(1)",
  "content": "Every employee shall be allowed ... (embedded text, provisos kept)",
  "cross_references_internal": ["s. 37", "s. 60F"],
  "cross_references_external": ["Workmen's Compensation Act 1952 [Act 273]"],
  "jurisdiction": "Peninsular Malaysia and Labuan",
  "source_version": "as at 1 January 2023",
  "source_page": 53,
  "source_url": "https://lom.agc.gov.my/..."
}
```
 
Only `content` is embedded. Everything else is for filtering and citation.
 
Additional locked decisions:
- Use `cross_references_internal` exactly. No shorthand like `cross_refs`.
- Jurisdiction strings must be precise (EA = "Peninsular Malaysia and Labuan", never "Malaysia").
- Deleted/repealed sections stay as real chunks with `status: "deleted"`, `deleted_by`, `deleted_at`.
- Definition chunks (`'term' means ...`) get `chunk_type: "definition"` and are co-retrieved with parent context.
- `in_force_notes[]` holds verbatim footnote text for pending-amendment notes (IRA style).
- External cross-references are recorded so the system can say when an answer depends on a statute it does not hold.
- BM25 gets zero overlap on non-English input, so language detection at query entry is a required gate.
## Parser gotchas (high risk of silent failure)
 
- Provisos must stay attached to the subsection above them. A chunk that loses its proviso still produces a fluent, correctly cited, wrong answer.
- Omitted/deleted sections appear only as placeholders.
- EA 1955 First Schedule is a two-column table, not numbered sections.
- Page furniture detection must be **positional**, not frequency only (Sabah has 142 deleted-section lines that frequency detection would strip).
- Sarawak has a three-line header, needs a wider page-number detection window.
- Validation script: every section in the source's ARRANGEMENT OF SECTIONS must appear in at least one chunk. Hand-fix rare chunks where no rule fits.
## Tech stack
 
| Layer | Choice |
|---|---|
| PDF extraction | PyMuPDF |
| Chunking | Custom rule-based parser |
| Embedding | bge-m3 |
| Vector store | PostgreSQL + pgvector |
| Sparse | BM25 (bge-m3 learned sparse as alt config) |
| Reranker | bge-reranker-large |
| Generator | Qwen3-14B 4-bit (local RTX A4000 16GB); hosted API fallback |
| Orchestration | LangChain (fixed pipeline, not agents) |
| Backend | FastAPI, typed Pydantic schemas, streaming |
| Frontend | React + TypeScript (+ Tailwind, shadcn/ui) |
| Evaluation | RAGAS |
 
Hardware rules: load models one at a time on the 16GB GPU. Generator is called through **one interface** so local / HPC / hosted API is a config switch, not a rewrite.
 
## Evaluation plan
 
- Gold set: 60 to 80 items (minimum 40 in-scope + 20 out-of-scope). Each item = question, reference answer, expected citations.
- Questions sourced externally (Dept of Labour FAQs, forums, HR sites), not written while reading the statute.
- Stratified by topic (wages, hours, leave, termination, dismissal), difficulty (single vs multi-provision), and scope (in vs out).
- RAGAS metrics reported separately: faithfulness, answer relevancy, context precision, context recall. Same judge model and prompts across all configs.
- Abstention: report % out-of-scope correctly declined and % in-scope wrongly declined.
- Manual citation inspection on a sample: displayed citation matches retrieved chunk and the real Act page.
- Config comparison: dense only vs hybrid vs hybrid + rerank; generators compared on identical retrieval.
## Frontend (after the response schema is stable)
 
- Landing: single query box, 4 suggested topics, sidebar with history stored in the **browser only**.
- Answer view: plain-language prose with inline numbered markers + Sources block (Act, section, heading).
- Source panel: full provision text including provisos, fetched live from the corpus.
- Abstention state: informational notice, not an error. Lists covered statutes, points to Dept of Labour.
- Help/FAQ: states which statutes apply to which territory.
- Disclaimer: legal information, not legal advice.
## Privacy and ethics
 
No accounts, no personal data, no server-side conversation storage. DB holds only statutory text. Prompt forbids recommending a course of action.
 

## Scope discipline
 
Deferred to future work: Bahasa Malaysia, case law, extra statutes, agentic/graph retrieval, production deployment. Anything new in CP2 needs supervisor agreement. Do not add features quietly.
 
## Current status (update as work progresses)
 
- Phase: M1 ingestion **complete**. Next: M2 indexing (PostgreSQL + pgvector, bge-m3, BM25). Start collecting gold-set questions in parallel.
- Run it: `python -m src.ingestion.pipeline` writes `data/processed/chunks.jsonl`, `toc_inventory.jsonl` and `ingestion_report.json`; exits 1 if validation finds problems.
- Result: 1,852 chunks (EA 370, IRA 273, Sabah 627, Sarawak 435, A1754 147). All 721 listed sections and every schedule have chunks; validation clean; 184 tests passing. Formula fractions are rebuilt from drawn bars (`monthly rate of pay / 26`).
- Manual audit done 2026-10-08: 60 chunks (seed 42, stratified) checked against the PDFs, 60/60 on content, boundaries and page numbers (`data/eval/chunk_audit_sample.csv`, devlog Section 14).
- Act A1753 (Sabah amendment) checked and deliberately not indexed: the Sabah text already includes it (config.yaml, devlog Section 13).
- Modules: `extract.py` (pages, furniture incl. three-line headers, footnotes), `toc.py` (inventory), `sections.py` (subsection chunks, definitions per term, placeholders), `schedules.py` (coverage tables from coordinates), `amendments.py` (A1754 chunks + links to Cap. 76), `validate.py`, `pipeline.py`.
- Sarawak: Cap. 76 chunks amended by A1754 are `superseded` with `amended_by` links (138); deleted by A1754 are `deleted` (29). A1754 s.52 (Part IVa) is `not_yet_in_force`.
- Check by hand once: the 8 inferred section titles in `ingestion_report.json` (all verified 2026-10-08), and a sample of A1754 links.
- Open items: confirm Act A1754 commencement against the P.U. gazette; settle Sarawak handling with Dr Azam; Sarawak has no Part III anywhere in the 2006 text (source fact, worth mentioning).
- Deferred (in `docs/chunk_schema.md`): LIST OF AMENDMENTS provenance tables; EA Second Schedule is a three-column table chunked as plain text.
- Other context docs: `docs/chunk_schema.md`, `docs/plans/`, `docs/devlog/` (one English log per working session, written as source material for the CP2 report: decisions, problems and fixes, evidence, numbers).
## How to work with me
 
- Plan first, then TDD (Superpowers workflow).
- Plain, concise explanations. No em dashes.
- When a decision changes, update this file or `docs/` so the next session knows.
 
