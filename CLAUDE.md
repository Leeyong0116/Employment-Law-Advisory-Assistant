

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
| Employment (Limitation of Overtime Work) Regulations 1980 | Peninsular Malaysia and Labuan | JTKSM | Revised P.U. (A) 339/1983, amended to 1991. Added 2026-10-16 |
| Employment (Termination and Lay-Off Benefits) Regulations 1980 | Peninsular Malaysia and Labuan | JTKSM | Revised P.U. (A) 338/1983, amendments to 1999 (P.U. (A) 92/11 status unknown). Added 2026-10-16 |
 
Rules:
- Sarawak principal text and Act A1754 are indexed as **separate documents**, linked in metadata, so an amended provision is retrieved with its amendment. Do NOT build a merged consolidated text. Example: Sarawak s.84 says 60 days maternity leave, but A1754 changed it to 98.
- Every chunk stores its consolidation date and source page/URL.
- Out of scope for the corpus: Minimum Wages Order, EPF Act, SOCSO Act, Minimum Retirement Age Act, Workmen's Compensation Act, Children and Young Persons Act, higher-court judgments (High Court, Court of Appeal, Federal Court), Labour Court decisions.
- **Changed (agreed with Dr Azam, recorded 2026-10-16):** Industrial Court awards are now IN scope, about 20 to 40 awards chosen by topic (dismissal, constructive dismissal, wages, termination benefits, misconduct / domestic inquiry), across regions. Design pending (brainstorm, then spec in `docs/superpowers/specs/`). Rules agreed so far: gold-set questions still come from the Q&A sources, never written from an award (no leakage); a gold item may expect an award paragraph as its citation; this makes gold set v2, with v1 kept as the statute-only baseline and thresholds recalibrated on v2.
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
 
Deferred to future work: Bahasa Malaysia, case law beyond Industrial Court awards, extra statutes, agentic/graph retrieval, production deployment. Anything new in CP2 needs supervisor agreement. Do not add features quietly.
 
## Current status (update as work progresses)
 
- Phase: M1 ingestion, M2 indexing and M3 retrieval **complete**; gold set v1 built and first retrieval evaluation done (2026-10-10). Next: M4 generation over `RetrievalResult`, then full RAGAS.
- EA regulations added 2026-10-16 (author's decision; report to Dr Azam). Overtime Regulations (2 chunks, `OT1980_r2` = 104 hours) and Termination and Lay-Off Benefits Regulations (43 chunks, `TLB1980_r6_1` = rates). Registry: `doc_type: subsidiary`, `parent`, `provision_label: reg.`, `inline_titles`, `page_numbers: pdf_index` (no printed pages), `declared_sections` (overtime regs have no contents page). Corpus 1,897 chunks, index `459843bf28ba`; existing chunks unchanged except `A1754_s1` lost a self-reference in `cross_references_external` (bug fix). Re-run on gold v1: hybrid + rerank hit@5 0.926, MRR 0.793, AUC 0.918, **5-fold 60% out-of-scope declined** (was 70%) / 11% in-scope wrongly declined; JPPM-013 and RDT-009 now pass the gate on near-miss matches with TLB reg. 15(3) and 11(1). Threshold unchanged (0.0325). Gold v1 has no in-scope Peninsular regulation question, so it shows the cost, not the benefit. Sabah / Sarawak equivalents not held (SBH-073, SWK-033 stay external). Devlog `docs/devlog/2026-10-16_ea-regulations.md`, plan `docs/plans/2026-10-16-ea-regulations.md`.
- Gold set v1: `data/eval/gold_set.jsonl`, 77 items (54 in scope: Peninsular 19, IRA 6, Sarawak 13, Sabah 11, no region 5; 3 external; 20 out of scope), from official JTKSM / JPPM / JTK Sarawak / JTK Sabah FAQs and Reddit posts. Per-item corpus check in `data/eval/gold_review.json`; candidates in `data/eval/faq_candidates_all.csv`. 15 reference answers were rewritten by Claude and still need the author's reading. Do not edit v1 after seeing answer-level results except for documented errors.
- Retrieval evaluation: `python -m src.evaluation.retrieval_eval` (results in `data/eval/runs/`). Hybrid + rerank best: hit@5 0.926, MRR 0.802, recall 0.837; abstention AUC 0.936, 5-fold 70% out-of-scope declined / 11% in-scope wrongly declined (report the 5-fold figures). Thresholds in config calibrated on the gold set (rerank 0.0325). Devlog: `docs/devlog/2026-10-10_gold-set-and-retrieval-eval.md`.
- Pending decision (author thinking, then Dr Azam): two-signal abstention gate. Long scenario questions get low cross-encoder scores even when retrieval is right (median 0.117 for >25 words vs 0.908 for <=15). Rule "answer if reranker >= threshold OR dense cosine above the highest out-of-scope training score" cut 5-fold wrong declines from 11% to 6% with out-of-scope declines unchanged at 70%. Not adopted: CLAUDE.md defines the gate on the reranker score, and 20 out-of-scope items is thin evidence. Devlog `2026-10-10_gold-set-and-retrieval-eval.md` Section 9; script `scripts/exp_gate_amendments.py`.
- Data issues found (to fix): citation label names a whole subsection after a mid-sentence definition (EA s.37(1)); `superseded` marks unchanged subsections (A1754 s.34 -> 13 chunks); EA s.1(2) says Peninsular only (Labuan basis not in corpus); termination-benefit rates and the overtime limit: Peninsular regulations now held (2026-10-16), Sabah and Sarawak equivalents not held, and the empowering sections still have empty `cross_references_external`.
- M3 (2026-10-10, plan `docs/plans/2026-10-10-m3-retrieval.md`, devlog `docs/devlog/2026-10-10_m3-retrieval.md`): `src/retrieval/pipeline.py` `Retriever.retrieve(query, region, mode, gate)` = language gate (word share, mixed English/Malay passes) -> dense (placeholders excluded) + BM25 -> RRF -> reranker (citation + title + content, sliding window) -> per-mode abstention gate -> expansion (amendment links both ways, same-section definitions except s.2, cap 12). Modes `dense` / `hybrid` / `hybrid_rerank` for the config comparison. Smoke: `python -m src.retrieval.smoke` (12/12). Batch: `python -m src.retrieval.run`. Thresholds in config are PROVISIONAL (dev list, never report); calibrate on the gold set with `scripts/calibrate.py`, same rule for every mode (plan Section 7a). Finding: on full sentences dense separated in/out of scope as well as the reranker (AUC 0.967 vs 0.960, n = 25), so the earlier "only the reranker can gate" note is not supported.
- M2 indexing: `docker compose up -d` (PostgreSQL + pgvector), then `docker compose run --rm ml python -m src.indexing.build` and `... src.indexing.smoke`. 1,852 chunks, bge-m3 1,024-dim, exact cosine search filtered in SQL, BM25 over citation + title + content. Smoke checks 7/7. ML code runs in the `ml` container because Windows Smart App Control blocks native DLLs (scipy) in the venv; do NOT suggest turning it off (irreversible). Devlog: `docs/devlog/2026-10-08_m2-indexing.md`.
- Hand tools: `scripts/search.py`, `scripts/compare.py` (web page, 4 methods side by side; not the M3 pipeline). Devlog: `docs/devlog/2026-10-09_retrieval-exploration.md`.
- Run it: `python -m src.ingestion.pipeline` writes `data/processed/chunks.jsonl`, `toc_inventory.jsonl` and `ingestion_report.json`; exits 1 if validation finds problems.
- Result: 1,852 chunks (EA 370, IRA 273, Sabah 627, Sarawak 435, A1754 147). All 721 listed sections and every schedule have chunks; validation clean. Formula fractions are rebuilt from drawn bars (`monthly rate of pay / 26`).
- Manual audit done 2026-10-08: 60 chunks (seed 42, stratified) checked against the PDFs, 60/60 on content, boundaries and page numbers (`data/eval/chunk_audit_sample.csv`, devlog Section 14).
- Act A1753 (Sabah amendment) checked and deliberately not indexed: the Sabah text already includes it (config.yaml, devlog Section 13).
- Modules: `extract.py` (pages, furniture incl. three-line headers, footnotes), `toc.py` (inventory), `sections.py` (subsection chunks, definitions per term, placeholders), `schedules.py` (coverage tables from coordinates), `amendments.py` (A1754 chunks + links to Cap. 76), `validate.py`, `pipeline.py`.
- Sarawak: Cap. 76 chunks amended by A1754 are `superseded` with `amended_by` links (138); deleted by A1754 are `deleted` (29). A1754 s.52 (Part IVa) is `not_yet_in_force`.
- Check by hand once: the 8 inferred section titles in `ingestion_report.json` (all verified 2026-10-08), and a sample of A1754 links.
- Open items: ask Dr Azam about k-fold threshold calibration and the 10% in-scope budget, the RAGAS judge model, the termination-benefit and overtime regulations now indexed (and whether to find the Sabah / Sarawak equivalents), find P.U. (A) 92/11 to confirm the termination text's currency, the Labuan basis, and keeping gold item JTKSM-68 (inference); check IRA s.33B chunking against the PDF; confirm Act A1754 commencement against the P.U. gazette; settle Sarawak handling with Dr Azam; Sarawak has no Part III anywhere in the 2006 text (source fact, worth mentioning).
- Deferred (in `docs/chunk_schema.md`): LIST OF AMENDMENTS provenance tables; EA Second Schedule is a three-column table chunked as plain text.
- Other context docs: `docs/chunk_schema.md`, `docs/plans/`, `docs/devlog/` (one English log per working session, written as source material for the CP2 report: decisions, problems and fixes, evidence, numbers).
## How to work with me
 
- Plan first, then TDD (Superpowers workflow).
- Plain, concise explanations. No em dashes.
- When a decision changes, update this file or `docs/` so the next session knows.
 
