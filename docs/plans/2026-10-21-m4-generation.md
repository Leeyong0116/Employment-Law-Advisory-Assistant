# Plan: M4 generation over RetrievalResult

Status: draft 2026-10-21. D1 decided by the author (use LangChain, as in the CP1 proposal); D2 to D6 waiting for review.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a `RetrievalResult` into a typed answer: plain-language prose with numbered markers, plus a separate list of citations built only from chunk metadata, or an abstention notice when retrieval abstained.

**Architecture:** A fixed LangChain LCEL chain: `RetrievalResult` -> numbered context blocks + fixed rules (`ChatPromptTemplate`) -> one call to `ChatOpenAI` pointed at an OpenAI-compatible server -> marker parsing -> `GeneratedAnswer`. The chain has no branches chosen by a model, so it stays deterministic (CLAUDE.md: "LangChain (fixed pipeline, not agents)"). The chat model is built from config only; the vLLM server on the Sunway HPC (Open OnDemand proxy, cookie auth), a hosted API, or a local server is a config change. M3 retrieval is not rewritten: it already returns the typed `RetrievalResult` the chain starts from.

**Tech Stack:** Python 3.12, pydantic 2.13.5, langchain-core (the 0.3.x already installed for ragas) and langchain-openai (pinned in Task 4), httpx, vLLM serving Qwen3-14B 4-bit, pytest.

**Spec:** `CLAUDE.md` (core contribution 1 to 4, architecture steps 8 and 9, privacy) and `src/retrieval/schema.py` (the input contract).

## Global Constraints

- Citations come from chunk metadata, never from text the LLM generates (CLAUDE.md, core contribution 1).
- Traceability, not verification: code comments and docs say the system checks that a statement points to a retrieved provision, not that the provision legally supports it (core contribution 2).
- When `RetrievalResult.abstained` is true, no generator call is made (core contribution 3).
- The prompt forbids recommending a course of action; tone is advisory; answer only from the given context (architecture step 8, privacy).
- Answer and citations are separate typed fields (architecture step 9).
- LangChain only as a fixed LCEL chain (prompt | chat model | parser). No agents, no tools, no LangChain retrievers, no second retrieval round. One request per question.
- `src/generation/` imports no torch and no model weights; it needs only langchain-core, langchain-openai, httpx, pydantic and pyyaml.
- Secrets (cookie, API key) only in `.env`, read by variable name from config. Never logged, never written to run files.
- Docs and devlog: plain English, no em dashes.

## Decisions for the author (D1 to D6)

| # | Decision | Recommendation |
|---|---|---|
| D1 | CLAUDE.md and the CP1 proposal list LangChain for orchestration. M3 was built in plain Python. | **Decided 2026-10-21 by the author: use LangChain** for generation as a fixed LCEL chain. M3 stays as is (validated, and already typed). Report wording: LangChain composes the prompt, the model call and the parser; retrieval is a deterministic pipeline in front of it. |
| D2 | The model may write "under section 60E" in its prose. Such text is LLM-written citation, which core contribution 1 rules out. | Prompt: refer to sources only by `[n]`, never name an Act or section. The post-processor still detects provision mentions and records them in `provision_mentions` so evaluation can count violations. |
| D3 | The gate passes but the chunks do not answer the question. | The model replies with the fixed sentence `INSUFFICIENT_CONTEXT`; status becomes `insufficient_context`, reported apart from gate abstention. No new threshold. |
| D4 | Sampling. | Temperature 0, fixed seed, Qwen3 thinking mode off (`chat_template_kwargs.enable_thinking = false`). Reproducible runs matter more than style for RAGAS comparisons. |
| D5 | Scope of M4. | Generation, the batch runner, a live smoke run and one answer run on gold v1. Full RAGAS with a judge model is the next plan (judge model is still an open item for Dr Azam). |
| D6 | Exact model id. | Whatever `/v1/models` reports on the HPC server (expected an AWQ or GPTQ 4-bit Qwen3-14B). Recorded in config and in every answer record. |

## Response shape (the contract M5 and RAGAS consume)

```
GeneratedAnswer
  query, region, status: "answered" | "abstained" | "insufficient_context"
  answer: str | None            prose with markers [1], [2] renumbered by first use
  citations: list[Citation]     number + fields copied from RetrievedChunk
  abstention: Abstention | None reason, statutes_held, message
  notes: list[str]              jurisdiction notes (Sarawak worker->employee), currency caveats
  external_dependencies: list[str]   from cross_references_external of cited chunks
  checks: AnswerChecks          invalid_markers, uncited_sentences, provision_mentions, truncated
  generator: GeneratorInfo      model, temperature, seed, prompt_version, prompt/completion tokens
  context_chunk_ids: list[str]  every chunk shown to the model, in block order
  index_version: str
```

`Citation` fields: `number, chunk_id, citation, statute, act_number, section, subsection, section_title, jurisdiction, status, source_page, source_url, source_version`. All copied, none generated.

## Review Focus

1. OOD session cookie expires during a 77-question run: the proxy answers with a 302 to the login page. Expected: `SessionExpired` raised, the run stops, records already written stay valid, rerun resumes from the next id. Tests in Task 4 and Task 6.
2. The model writes markers in other forms: `[1, 3]`, `[1][3]`, `[1-3]`, `[ 2 ]`. Expected: all resolve to the same citations; a number with no block (`[9]` with 5 blocks) is dropped from the text and listed in `invalid_markers`. Test in Task 3.
3. Qwen3 emits a `<think>...</think>` block even with thinking off. Expected: stripped before parsing. Test in Task 4.
4. The model names a section in prose ("section 60E"), in breach of D2. Expected: text kept, mention listed in `provision_mentions`. Test in Task 3.
5. A superseded Sarawak chunk is in context but its A1754 chunk was dropped by the expansion cap. Expected: the block header still says superseded and names the amending provision by its chunk id, so the model is not told the old wording is current. Test in Task 2.

---

### Task 1: Answer schema

**Files:**
- Create: `src/generation/schema.py`
- Test: `tests/unit/test_generation_schema.py`

**Interfaces:**
- Consumes: `RetrievedChunk`, `RetrievalResult` from `src/retrieval/schema.py`.
- Produces: `Citation`, `Abstention`, `AnswerChecks`, `GeneratorInfo`, `GeneratedAnswer` (fields as in "Response shape"); `Citation.from_chunk(number: int, chunk: RetrievedChunk) -> Citation`; constants `DISCLAIMER: str`, `Status = Literal["answered", "abstained", "insufficient_context"]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_citation_copies_metadata_exactly():
    chunk = RetrievedChunk(chunk_id="EA1955_s60E_1", citation="Employment Act 1955, s. 60E(1)", statute="Employment Act 1955",
                           chunk_type="provision", jurisdiction="Peninsular Malaysia and Labuan", status="in_force",
                           content="...", source_page=58, added_because="retrieved")
    c = Citation.from_chunk(1, chunk)
    assert (c.number, c.chunk_id, c.citation, c.source_page) == (1, "EA1955_s60E_1", "Employment Act 1955, s. 60E(1)", 58)

def test_answered_needs_answer_and_abstained_needs_notice():
    with pytest.raises(ValidationError): GeneratedAnswer(**base(status="answered", answer=None))
    with pytest.raises(ValidationError): GeneratedAnswer(**base(status="abstained", abstention=None))

def test_citation_numbers_are_1_to_n_in_order():
    with pytest.raises(ValidationError): GeneratedAnswer(**base(citations=[cit(2), cit(1)]))
```

- [ ] **Step 2: Run them, expect FAIL** (`docker compose run --rm ml pytest tests/unit/test_generation_schema.py`, module not found)
- [ ] **Step 3: Implement the models** with a `model_validator(mode="after")` for the two rules above. Module docstring states the traceability-not-verification rule.
- [ ] **Step 4: Run them, expect PASS**
- [ ] **Step 5: Commit** `Add the typed answer schema for M4`

### Task 2: Context blocks and prompt

**Files:**
- Create: `src/generation/prompt.py`
- Test: `tests/unit/test_prompt.py`

**Interfaces:**
- Consumes: `RetrievalResult`; `config["jurisdiction_notes"]` (already in `config/config.yaml`).
- Produces: `PROMPT_VERSION = "m4-v1"`; `INSUFFICIENT = "INSUFFICIENT_CONTEXT"`; `PROMPT: ChatPromptTemplate` (system rules + a user template with variables `region`, `notes`, `context`, `question`); `build_prompt(result: RetrievalResult, jurisdiction_notes: dict) -> Prompt` where `Prompt` is a pydantic model with `variables: dict[str, str]` (the template inputs), `blocks: list[RetrievedChunk]` (block n is `blocks[n-1]`), `notes: list[str]`.

Block order = `result.chunks` order (retrieved by rank, then expansion). Block header, one line, all from metadata:
`[n] <citation> | <section_title> | <jurisdiction> | <status label>` then `content`, then `in_force_notes` verbatim. Status labels: `in force`; `SUPERSEDED, amended by <amended_by ids> (see block k)` or `(amending text not shown)` when absent; `DELETED`; `NOT YET IN FORCE`.

System rules, fixed text (exact copy decided here):
1. Answer only from the numbered sources. If they do not answer the question, reply exactly `INSUFFICIENT_CONTEXT`.
2. After each sentence that states the law, add the marker of the source(s) it comes from, like [1] or [2][3].
3. Refer to sources only by their marker. Do not name Acts, Ordinances or section numbers yourself.
4. Where a source is marked SUPERSEDED, state the amended rule from the amending source, not the old wording.
5. Explain in plain language what the law says. Do not tell the user what they should do, and do not give legal advice.
6. If the sources come from more than one territory, say which rule applies in which territory.
User message: region line (`User's region: Sabah` or `User's region: not given`), the notes, the blocks, then `Question: ...`.

- [ ] **Step 1: Write the failing tests** (render with `PROMPT.format_messages(**prompt.variables)`): `test_blocks_follow_result_order`, `test_header_built_from_metadata_only` (header equals the expected string for a fixture chunk), `test_superseded_points_to_amending_block` (SWK76_s84_1 with A1754_s24 present -> "see block 2"), `test_superseded_without_amending_chunk_says_not_shown` (Review Focus 5), `test_sarawak_note_only_when_sarawak_chunk`, `test_in_force_notes_included_verbatim`, `test_rules_forbid_advice_and_section_names` (system text contains rules 3 and 5), `test_abstained_result_raises` (`ValueError`: never build a prompt for an abstention).
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement `build_prompt`**
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `Build numbered context blocks and the fixed prompt`

### Task 3: Marker parsing and citation building

**Files:**
- Create: `src/generation/citations.py`
- Test: `tests/unit/test_citations.py`

**Interfaces:**
- Consumes: `Prompt.blocks` (Task 2), `Citation`, `AnswerChecks` (Task 1).
- Produces: `resolve(text: str, blocks: list[RetrievedChunk]) -> Resolved` with `answer: str` (markers renumbered by first use), `citations: list[Citation]`, `invalid_markers: list[int]`, `uncited_sentences: int`, `provision_mentions: list[str]`.

Marker grammar: `[` numbers separated by `,` or `-` (range) `]`, spaces allowed. Each group is rewritten as adjacent single markers `[a][b]`. Provision mentions: regex for `section \d+[A-Z]*`, `s\. ?\d+`, `reg(ulation)?\.? ?\d+`, case-insensitive. Uncited sentence: a sentence of 6 or more words with no marker (headings and one-word lines ignored).

- [ ] **Step 1: Write the failing tests**

```python
def test_renumbers_by_first_use():           # "A [3]. B [1]." -> "A [1]. B [2]."; citations[0].chunk_id == blocks[2].chunk_id
def test_group_and_range_forms():            # "[1, 3]", "[1-3]", "[ 2 ]" all parse (Review Focus 2)
def test_out_of_range_dropped_and_recorded(): # 5 blocks, "X [9]." -> answer "X.", invalid_markers == [9]
def test_uncited_sentences_counted():        # "The rule is long and has no marker at all. Y [1]." -> 1
def test_provision_mentions_flagged():       # "Under section 60E you get ... [1]" -> ["section 60E"] (Review Focus 4)
def test_unused_blocks_are_not_cited():      # 5 blocks, only [2] used -> one citation
```

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement `resolve`**
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `Resolve answer markers to citations from chunk metadata`

### Task 4: Chat model factory and config

**Files:**
- Create: `src/generation/llm.py`
- Modify: `config/config.yaml` (`generation:` block), `.env.example`, `requirements.txt` (Phase 3 block: add `langchain-openai` at the newest release compatible with the `langchain-core` that `docker compose run --rm ml pip show langchain-core` reports, and pin `httpx` at its installed version; check `pip check` is clean and ragas still imports; rebuild the ml image)
- Test: `tests/unit/test_llm.py`

**Interfaces:**
- Produces: `build_chat_model(settings: dict, env: Mapping[str, str], transport: httpx.BaseTransport | None = None) -> BaseChatModel` (a `ChatOpenAI` with `base_url`, `model`, `temperature`, `seed`, `max_tokens`, `timeout`, `max_retries=0`, `default_headers={"Cookie": ...}` when `cookie_env` is set, `api_key` from `api_key_env` or the placeholder `"EMPTY"`, `extra_body={"chat_template_kwargs": {"enable_thinking": ...}}`, and `http_client=httpx.Client(follow_redirects=False, transport=transport)`); `invoke_with_retry(model: BaseChatModel, messages, retries: int, sleep=time.sleep) -> Reply`; `Reply(text: str, model: str, finish_reason: str | None, prompt_tokens: int | None, completion_tokens: int | None)` read from `AIMessage.response_metadata` / `usage_metadata`; `list_models(settings, env) -> list[str]` (plain httpx GET `/models`, same headers); exceptions `SessionExpired`, `GeneratorError`.

Retries are ours, not the openai SDK's (`max_retries=0`), so a login redirect is never retried and the test can count calls. The openai SDK raises on a 302 or a non-JSON body; `invoke_with_retry` maps those to `SessionExpired`.

Config block (replaces the current `generation:` placeholder):

```yaml
generation:
  base_url_env: GENERATOR_BASE_URL     # e.g. the OOD proxy URL ending in /v1
  cookie_env: OOD_COOKIE_SECRET        # full Cookie header; null for a hosted API
  api_key_env: null                    # Bearer key for a hosted API
  model: null                          # set from /v1/models (D6)
  temperature: 0
  seed: 0
  max_tokens: 1024
  enable_thinking: false               # Qwen3 chat template switch (D4)
  timeout_seconds: 120
  retries: 3
```

Behaviour: 302, 401 or an HTML body -> `SessionExpired("OOD session expired: copy a fresh cookie into .env")`. 5xx or connection error -> retry with 2, 4, 8 s backoff, then `GeneratorError`. `<think>...</think>` stripped from the text.

- [ ] **Step 1: Write the failing tests** with `httpx.MockTransport` passed to `build_chat_model`: `test_sends_cookie_and_body` (Cookie header equals env value; JSON body has `model`, `temperature: 0`, `seed: 0`, `chat_template_kwargs: {"enable_thinking": false}`), `test_redirect_to_login_raises_session_expired` (one call only; Review Focus 1), `test_html_200_raises_session_expired`, `test_retries_5xx_then_fails` (4 calls, `sleep` patched), `test_think_block_stripped` (Review Focus 3), `test_finish_reason_length_reported`, `test_secret_not_in_repr` (cookie absent from `repr(model)`; if `ChatOpenAI` shows headers in its repr, wrap it so it does not).
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement `llm.py`; update config, `.env.example` (`GENERATOR_BASE_URL=`, `OOD_COOKIE_SECRET=` with a one-line note), `requirements.txt`**
- [ ] **Step 4: Run, expect PASS; `tests/test_config.py` and the existing ragas imports still pass**
- [ ] **Step 5: Commit** `Add the LangChain chat model for vLLM over OOD, or a hosted API`

### Task 5: Answerer

**Files:**
- Create: `src/generation/answer.py`
- Test: `tests/unit/test_answer.py`

**Interfaces:**
- Consumes: `PROMPT`, `build_prompt` (Task 2), `resolve` (Task 3), `build_chat_model`, `invoke_with_retry` (Task 4), schema (Task 1).
- Produces: `class Answerer: __init__(self, model: BaseChatModel, config: dict)`, `answer(self, result: RetrievalResult) -> GeneratedAnswer`, `from_config(config_path="config/config.yaml") -> Answerer`.

The chain, built once in `__init__`: `PROMPT | model` called through `invoke_with_retry`, then `resolve` on the text. Gate abstention is checked before the chain runs.

Abstention message (exact copy): "This question is outside what GetRight can answer from the statutes it holds. GetRight covers: <statutes_held, one per line>. For help with your situation, contact the Department of Labour (JTKSM, JTK Sabah or JTK Sarawak)." `external_dependencies` = union of `cross_references_external` over cited chunks, sorted.

- [ ] **Step 1: Write the failing tests** with langchain-core's `GenericFakeChatModel` (or a subclass that counts calls): `test_abstained_result_makes_no_call`, `test_answered_fields` (status, citations from blocks, `context_chunk_ids` equals block order, `index_version` copied), `test_insufficient_context_status` (reply `INSUFFICIENT_CONTEXT` -> status `insufficient_context`, no citations), `test_external_dependencies_from_cited_chunks_only`, `test_truncated_flag` (finish_reason `length`).
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement `Answerer`**
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `Answer a RetrievalResult: prompt, one call, typed result`

### Task 6: Batch runner with resume

**Files:**
- Create: `src/generation/run.py`
- Test: `tests/unit/test_generation_run.py`

**Interfaces:**
- Consumes: output files of `src/retrieval/run.py` (lines `{"id", "result"}`), `Answerer` (Task 5).
- Produces: CLI `python -m src.generation.run retrieval.jsonl answers.jsonl`; `run(items: list[dict], answerer: Answerer, output: Path) -> int` (answers written this call). Output lines `{"id", "answer": GeneratedAnswer}`, one flush per line.

Ids already present in `output` are skipped, so a rerun after `SessionExpired` continues. `SessionExpired` is printed with the count done and the command to resume, exit code 2.

- [ ] **Step 1: Write the failing tests**: `test_writes_one_line_per_item`, `test_resume_skips_done_ids`, `test_session_expired_keeps_written_lines` (fake raises on item 3: 2 lines kept, exit path raises/returns as specified; Review Focus 1).
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `Batch generation over saved retrieval results, resumable`

### Task 7: Live check, smoke run, gold v1 answers, docs

**Files:**
- Create: `src/generation/check.py`, `src/generation/smoke.py`
- Modify: `pyproject.toml` (marker `live: needs the generator server`), `CLAUDE.md` (status; orchestration row: "LangChain LCEL chain for generation; retrieval is plain Python"), `docs/devlog/2026-10-21_m4-generation.md`

- [ ] **Step 1: `python -m src.generation.check`** prints the base URL host (no cookie), the models from `/v1/models` and one 5-word test reply. Set `generation.model` from it (D6).
- [ ] **Step 2: Smoke, 7 live questions** (`python -m src.generation.smoke`, needs DB + server), each with a structural check, report to `data/processed/generation_smoke_report.json`:
  - Peninsular overtime rate: answered, cites `EA1955_s60A_3_def_overtime` (s. 60A(3), stored under the definition id, a known data issue).
  - Peninsular monthly overtime limit: answered, cites `OT1980_r2` (104 hours).
  - Sarawak maternity leave: answer contains "98", cites an A1754 chunk, does not state 60 days as current.
  - Sabah annual leave: every citation has jurisdiction Sabah or Malaysia.
  - Maternity leave, no region: answered, cites more than one territory.
  - "How do I renew my passport?": status `abstained`, generator not called.
  - Malay question: status `abstained` (language).
  Expected: 7/7.
- [ ] **Step 3: Gold v1 answer run**: `python -m src.retrieval.run data/eval/gold_set.jsonl data/eval/runs/2026-10-21_retrieval.jsonl` (local), then `python -m src.generation.run data/eval/runs/2026-10-21_retrieval.jsonl data/eval/runs/2026-10-21_answers.jsonl`. Report status counts, mean `uncited_sentences`, total `invalid_markers` and `provision_mentions`.
- [ ] **Step 4: Manual citation inspection** on 10 answered items (seed 42): each displayed citation matches its chunk and the Act page. Record in the devlog.
- [ ] **Step 5: Devlog and CLAUDE.md status; commit** `Run M4 on gold v1 and log it`

## Out of scope

Streaming and the FastAPI layer (M5), the frontend, RAGAS faithfulness and answer relevancy with a judge model (next plan), the two-signal gate (pending decision), any change to retrieval.
