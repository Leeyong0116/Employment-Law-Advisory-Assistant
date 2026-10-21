# Development log: M4 generation over RetrievalResult (21 October 2026)

Source material for the CP2 report. Follows `2026-10-16_ea-regulations.md`.
Plan: `docs/plans/2026-10-21-m4-generation.md`.

---

## 1. Summary

The system now answers. A `RetrievalResult` goes through a fixed LangChain
chain (prompt template, then the chat model) to Qwen3-14B (AWQ 4-bit) served
by vLLM on the Sunway HPC, and comes back as a typed `GeneratedAnswer`:
prose with numbered markers, and a separate list of citations copied from
chunk metadata. When retrieval abstains, no model call is made.

- 79 new tests, 413 in total, all passing.
- Live smoke run: 7/7 checks (Section 6).
- Gold set v1, all 77 items, prompt `m4-v2`: 49 answered, 21 abstained at
  the gate, 7 declined by the model (`INSUFFICIENT_CONTEXT`). 0 invalid
  markers, 0 citations outside the user's region, 0 truncated answers
  (Section 7).
- Manual reading of 10 answered items (first run, `m4-v1`): citations and
  pages match the chunks in 10/10; the content was right in 7, wrong or
  partly wrong in 3. Under `m4-v2` two of the three are now right (Section 8).
- A whole-branch code review found one critical and two important problems;
  all three were fixed and the gold run repeated (Section 5).

## 2. Where the model runs

vLLM serves `Qwen/Qwen3-14B-AWQ` (max_model_len 16,384) as an Open OnDemand
interactive app on the Sunway HPC. The OOD reverse proxy is the only way in,
and it authenticates with the browser's session cookie
(`mod_auth_openidc_session`). Retrieval stays on the laptop (database,
bge-m3, reranker on the 8 GB card); only the prompt crosses the network.

- `.env`: `GENERATOR_BASE_URL` (the OOD URL ending in `/v1`) and
  `OOD_COOKIE_SECRET` (the whole Cookie header). Never committed or logged.
- The cookie expires. The proxy then answers with a 302 to its login page.
  The client treats that as `SessionExpired`, never retries it, and the
  batch runner stops with the count done; rerunning the same command
  continues from the next question.
- Measured: a short completion takes about 0.8 s. The full gold run (77
  questions, retrieval included) finished without a session expiry.

## 3. Design decisions

| # | Decision | Why |
|---|---|---|
| D1 | LangChain for generation, as a fixed LCEL chain (`PROMPT \| ChatOpenAI`). M3 retrieval unchanged. Decided by the author: the CP1 proposal names LangChain. | One model interface for HPC, hosted or local servers (a config change); RAGAS takes a LangChain model as judge; `.stream()` for M5. No agents, no tools, no LangChain retrievers, so the pipeline stays deterministic. |
| D2 | The model cites only by `[n]`; it may not name Acts or sections. | A section number written by the model is an LLM-generated citation (core contribution 1). Breaches are counted, not hidden (`provision_mentions`). |
| D3 | When the context does not answer, the model replies `INSUFFICIENT_CONTEXT`; status `insufficient_context`, reported apart from gate abstention. | Answer only from context. No new threshold. |
| D4 | Temperature 0, seed 0, Qwen3 thinking off (`chat_template_kwargs.enable_thinking: false`). | Repeatable runs for the RAGAS comparisons. |
| D5 | M4 ends at answers for gold v1; RAGAS with a judge model is the next plan. | The judge model is still open with Dr Azam. |
| D6 | Model id from `/v1/models`: `Qwen/Qwen3-14B-AWQ`. | Recorded in config and in every answer. |

How a citation is made: each chunk in the `RetrievalResult` becomes one
numbered block whose header is built from metadata only
(`[n] citation | section title | jurisdiction | status`). The model writes
`[n]`. `src/generation/citations.py` renumbers the markers by first use and
copies the citation fields from block n. A number with no block is removed
and recorded (`invalid_markers`). This is traceability: it shows which
provision a sentence points to, not that the provision legally supports it
(core contribution 2).

Prompt `m4-v2` (after the review, Section 5) adds rule 5: a source marked
DELETED, OMITTED or NOT YET IN FORCE is not current law; do not state it as
the current rule, and if mentioned, say so. Cited chunks that are not
current law are counted in `non_current_citations` (deleted, omitted, not
yet in force, or superseded and cited without the amending chunk).

Other content of the prompt: the user's region; the Sarawak worker to
employee note (A1754 s. 2) when a Sarawak chunk is present; status labels
(`SUPERSEDED, amended by A1754_s24 (see block 2)`, `DELETED`, `OMITTED`,
`NOT YET IN FORCE`); IRA `in_force_notes` verbatim. The answer also carries
the currency caveat of every cited statute (Sarawak 2006 text, the
termination regulations) and the external statutes a cited chunk depends on.

## 4. Code

| File | Role |
|---|---|
| `src/generation/schema.py` | `GeneratedAnswer`, `Citation`, `Abstention`, `AnswerChecks`, `GeneratorInfo` |
| `src/generation/prompt.py` | `PROMPT` (ChatPromptTemplate), `build_prompt`: numbered blocks and fixed rules |
| `src/generation/citations.py` | `resolve`: markers to citations, plus the traceability checks |
| `src/generation/llm.py` | `build_chat_model` (ChatOpenAI), `invoke_with_retry`, `list_models`, `SessionExpired` |
| `src/generation/answer.py` | `Answerer`: abstention notice or the chain, then the typed answer |
| `src/generation/run.py` | batch over saved retrieval results, resumable |
| `src/generation/check.py` | connection check: server, models, one reply |
| `src/generation/smoke.py` | 7 live end-to-end checks |

Run it:

```
docker compose run --rm ml python -m src.generation.check
docker compose run --rm ml python -m src.generation.smoke
docker compose run --rm ml python -m src.retrieval.run data/eval/gold_set.jsonl data/eval/runs/<date>_retrieval.jsonl
docker compose run --rm ml python -m src.generation.run data/eval/runs/<date>_retrieval.jsonl data/eval/runs/<date>_answers.jsonl
```

## 5. Problems met

1. **URL ending.** The URL first saved in `.env` ended in `/v1/models`; the
   client appends `/chat/completions` to a `/v1` base, so it was trimmed.
2. **A login page with status 200.** When the proxy returns its login page
   as HTML, the openai SDK hands LangChain a plain string and the error is
   an unrelated `AttributeError`. Fixed with an httpx response hook that
   raises `SessionExpired` on a redirect, a 401 or an HTML content type,
   before the SDK parses anything. The cookie sits on the httpx client, not
   on `ChatOpenAI`, so it never appears in the model's repr.
3. **Versions.** The plan assumed langchain-core 0.3.x. ragas 0.4.3 had
   already installed langchain-core 1.6.9, langchain-openai 1.1.9, openai
   1.109.1 and httpx 0.28.1; these are now pinned in `requirements.txt`
   (`pip check` clean, no image rebuild).

4. **Code review findings (independent reviewer on the whole branch).**
   Verdict "ready with fixes". Fixed, each with a test that failed first:
   - Critical: the model sometimes explained and then wrote
     `INSUFFICIENT_CONTEXT`; only a bare sentinel was recognised, so 4 gold
     items (SBH-043, RDT-009, SBH-033, SWK-093) were stored as answered,
     three with no citation, and the user would have seen the raw token.
     Now the sentinel anywhere in the reply means `insufficient_context`.
   - Important: block headers labelled DELETED and NOT YET IN FORCE, but no
     rule said what the labels mean; the model stated such provisions as
     current law (SWK-184, SBH-027, SWK-092, SWK-023). Added rule 5 and the
     `non_current_citations` check (prompt `m4-v2`).
   - Important: an HTML 502/503 page from the OOD proxy (vLLM job down)
     was reported as an expired session and not retried. Now only a
     redirect, a 401 or an HTML page with a success status counts as the
     login page.
   Eight minor findings are deferred: resume after a half-written line,
   an empty reply stops the batch, an unclosed `<think>`, regex edge cases
   in the checks, the async client for M5, HTTP 429, the raw reply not
   stored. The first run's answers are kept as
   `2026-10-21_answers_m4-v1.jsonl`.

## 6. Smoke run (live, 7/7 with both `m4-v1` and `m4-v2`)

| Check | Result |
|---|---|
| Peninsular overtime rate | 1.5 times the hourly rate, cites EA s. 60A(3) |
| Peninsular overtime limit | 104 hours, cites Overtime Regulations reg. 2 |
| Sarawak maternity | 98 days, cites A1754 s. 24; the superseded 60 days is not stated |
| Sabah annual leave | 8 / 12 / 16 days, cites Sabah s. 104D(1) only |
| Maternity, no region | separates Sarawak, Sabah and Peninsular, cites all three |
| "How do I renew my passport?" | gate abstains, no model call |
| Malay question | language gate abstains, no model call |

Seen in the no-region answer: "98 days" is cited to both the superseded
Cap. 76 s. 84(1) and A1754 s. 24, and EA s. 37(1) shows as "definition of
children" (the known label issue for that subsection).

## 7. Gold set v1 answer run (77 items, hybrid_rerank, gate on, prompt m4-v2)

Files: `data/eval/runs/2026-10-21_retrieval.jsonl`, `data/eval/runs/2026-10-21_answers.jsonl`
(first run, before the review fixes: `2026-10-21_answers_m4-v1.jsonl`).

| Scope | Answered | Gate abstained | Model: insufficient context |
|---|---|---|---|
| In scope (54) | 46 | 6 | 2 |
| Out of scope (20) | 2 | 13 | 5 |
| External (3) | 1 | 2 | 0 |

- The model's refusal adds to the gate. Out of scope not answered: 13/20
  by the gate alone, 18/20 with the model's refusals. In scope not
  answered: 6/54 by the gate, 8/54 in total. These are in-sample counts at
  the calibrated threshold; the figures to report for the gate remain the
  5-fold rates (devlog 2026-10-16), and this is one run, not a calibrated
  rule. Refused by the model: JPPM-013, JTKSM-05, RDT-009, SBH-033,
  SBH-043, SWK-086, SWK-093.
- Answered in scope with expected chunks: 46; 41 cite at least one expected
  chunk.
- Citations per answer: mean 2.35, median 2. Invalid markers: 0.
  Citations outside the user's region: 0. Truncated: 0. Answered with no
  citation: 0.
- Prompt size: median 1,205 tokens, largest 3,643 (limit 16,384).
- **Rule 3 is broken in 9 of 49 answers**: the model names a section or an
  Act in its prose, often by echoing the question ("Section 20 of the IRA
  1967"). These names are not citations and are not shown as sources, but
  they are model-written legal references. Counted in `provision_mentions`.
- **Non-current law cited in 4 answers.** SBH-027 and SWK-092 now say the
  provision is not yet in force or deleted (rule 5 followed). SWK-184 says
  so too, but wrongly applies "not yet in force" to the whole of Act A1754
  (only its s. 52, Part IVa, is). SWK-152 describes "the new entitlement
  from 1 May 2025" while citing only the superseded Cap. 76 s. 105E(1).
- **Uncited sentences**: 48 in 22 answers. The count overstates the
  problem: the model often puts one marker at the end of a paragraph
  (SWK-040: three sentences counted, all from the one cited subsection).
  It also catches real cases (JTKSM-11 in the first run, below).

## 8. Manual inspection (10 answered items, seed 42, first run `m4-v1`)

Done on the first run, before the review fixes. Each displayed citation, its page and its chunk agree in 10/10 (by
construction: the fields are copied). The content was read against the
cited chunk text and the gold reference:

| Item | Verdict | Note |
|---|---|---|
| JPPM-003 | wrong | Answers "Yes" (compensation can be claimed); reference says s. 20 is a representation for reinstatement only. Built from the IRA Second Schedule (backwages limits), which retrieval ranked 2nd. A fluent, cited, wrong answer: the failure mode CLAUDE.md names. |
| JTKSM-10 | right | Names five sections in prose (rule 3). |
| JTKSM-11 | partly wrong | "An employer can ask her to return early" is not in the text; the provision lets the employee return with the employer's consent. The sentence is uncited, and the check counted it. |
| JTKSM-13 | right | |
| JTKSM-37 | right | |
| JTKSM-40 | right | |
| JTKSM-64 | right | |
| SBH-078 | partly wrong | The fine is right. "The court may order the employer to pay the wages due" is not in s. 130J, the block it cites; it most likely comes from s. 130K, which was also in context. Grounded in the context, wrongly attributed. |
| SWK-040 | right | |
| SWK-134 | right | Cites A1754 s. 26 (new s. 92B). |

Rechecked under `m4-v2`: JTKSM-11 now answers that the decision to return
early is the employee's, with the employer's agreement (right); SBH-078 now
gives only the fine (right, no misattributed sentence); JPPM-003 is still
the same wrong "Yes". The prompt change moved these answers even at
temperature 0, so the inspection of the `m4-v1` run does not carry over as
a measurement of `m4-v2`; the next inspection should be on the run that is
reported.

Faithfulness (RAGAS) should catch JTKSM-11 and maybe JPPM-003 at the
answer level, but not SBH-078: that statement is supported by the context
as a whole, only cited to the wrong block. A per-citation check (does the
cited block support its sentence?) would be needed, and is a candidate
metric to discuss with Dr Azam.

## 9. Limitations

- One run, one generator, temperature 0. No repeat runs to measure
  variation yet.
- Prompt rule 3 is followed in 82% of answers only (40/49); a stricter rule or a
  post-edit that strips section names is possible, but stripping would
  change the model's text, which faithfulness scoring then reads.
- `uncited_sentences` is a heuristic (sentence of 6+ words, no marker).
- No RAGAS answer metrics yet.
- Possible advice wording seen in RDT-006 ("your employer should pay you"),
  against rule 6; no automated advice check exists.

## 10. Next steps

1. Plan RAGAS answer metrics (faithfulness, answer relevancy) with a judge
   model; ask Dr Azam which judge.
2. Discuss a per-citation support check (SBH-078 shows why).
3. Decide on rule 3: accept and report, tighten the prompt, or strip.
4. M5: FastAPI over `Answerer` with streaming.
