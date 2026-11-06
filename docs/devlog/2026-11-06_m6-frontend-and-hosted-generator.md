# Devlog 2026-11-06: M6 ask form, hosted generator switch

Branch `m6-frontend`. Plan `docs/plans/2026-11-01-m6-frontend.md` ("Amendment 2026-11-04").

## 1. Summary

- Task 4 (ask form) progressed, written by the author: Send disabled without a question or region, loading state, error with Retry and `role="alert"`, required region dropdown, fixed disclaimer.
- Generator switched from the HPC (Qwen3-14B) to the DeepSeek hosted API for frontend development. Config change only, plus one bug fix in `src/generation/llm.py`.
- Backend tests: 487 passed (3 new). Frontend tests: 5 passed. Frontend type check: one unused `useEffect` import in `App.tsx` (left over, to remove).

## 2. Ask form (Task 4)

- `canSend` is a value derived on every render (question not blank, region chosen, not loading), not separate state, so it cannot disagree with the inputs.
- Region: shadcn `Select`, state `Region | null` starting at `null`, so there is no default (plan D3, core contribution 4). Values `peninsular`, `sabah`, `sarawak`; labels use the exact jurisdiction names ("Peninsular Malaysia and Labuan"). `handleSend` starts with `if (!region) return`, which also narrows the type for TypeScript.
- Error: message with `role="alert"` and a Retry button that resends the current question.

## 3. Decision: disclaimer is fixed text, not from `/api/meta`

The plan amendment's "Kept" list said the disclaimer comes from `/api/meta`. Changed (author's decision): the frontend shows a fixed copy of `DISCLAIMER` from `src/generation/schema.py`.

Reason: the rule is that the disclaimer is always visible. If it came from `/api/meta`, a failed request would need a fixed fallback anyway, so the fetch adds code and a failure path without adding safety. Cost: the text exists in two places; a comment in `App.tsx` names the Python source. `useEffect` will be learned on the source panel instead (fetch when the chosen citation changes).

## 4. Hosted generator (DeepSeek)

Why: frontend development needs answers without keeping an HPC job and session cookie alive.

Config (`config/config.yaml`, `generation`): `base_url_env: DEEPSEEK_BASE_URL`, `cookie_env: null`, `api_key_env: DEEPSEEK_API_KEY`, `model: deepseek-flash`. The HPC values stay in `.env`; the switch-back settings are in a comment in the config. `/v1/models` on 2026-11-06 lists `deepseek-flash` and `deepseek-v4-pro`; `deepseek-chat` is still accepted as an alias but is not listed, so the check script rejected it.

**Not for reported results.** All M4 numbers (gold v1, prompt m4-v2) are Qwen3-14B on the HPC. Answers made with DeepSeek record `generator.model = deepseek-flash`, so they can be told apart. Using it beyond development needs Dr Azam's agreement. Questions now go to a third-party service: use made-up test questions only.

## 5. Bug: hosted API reported as "OOD session expired"

Symptom: `python -m src.generation.check` printed "OOD session expired ..." with a valid DeepSeek key, although a direct request with the key returned 200 and chat calls worked.

Cause: two HPC-only assumptions in `llm.py`.
1. `list_models` sent only the cookie, never the API key, so DeepSeek answered 401.
2. The OOD login-page hook (`_check_login`) was always on and turns any 401 into `SessionExpired`. For a hosted API there is no session; a 401 means a rejected key.

Fix (test first, 3 tests failed for the right reason, then passed):
- `_client` adds the login-page hook only when a cookie is configured.
- `list_models` sends `Authorization: Bearer <key>` when `api_key_env` is set.

Effect: with a hosted API a bad key now gives `GeneratorError("generator returned HTTP 401 ...")` (API status 502) instead of the misleading 503 "expired cookie". The HPC path is unchanged (existing cookie tests pass).

New tests in `tests/unit/test_llm.py`: list_models sends the key and no cookie; a hosted 401 on list_models is an HTTP error, not `SessionExpired`; a hosted 401 on chat is a `GeneratorError`, not `SessionExpired`, and is not retried.

## 6. Answer view (Task 5, started)

- `src/components/AnswerView.tsx` takes the `GeneratedAnswer` as a prop; `App.tsx` renders it when there is a result (asking and showing are separate components).
- Sources list: `.map` over `answer.citations`, keyed by `chunk_id`. Each row shows `[number] citation section_title` and the jurisdiction, all from API fields. The number comes from `citation.number`, not the list position, so it always matches the `[n]` in the text.
- Markers: the answer text is split on `/(\[\d+\])/` (the capture group keeps the markers as pieces), then each piece is drawn as text or as a button. A piece becomes a button only when a citation with that number exists (`citations.find`), so an unknown marker stays plain text. The button's `title` shows the citation label on hover.
- Step 8.1 (in progress): clicking a marker stores the citation in `selected` state; a temporary line shows it. Next: the shadcn Sheet panel (8.2), then loading the provision text (8.3).
- Learning approach changed during the session: the author writes the code in small steps (about 5 lines each) with a check after each.

## 7. Next

- Step 8.2: source panel (shadcn Sheet) showing the selected citation; then 8.3: fetch `/api/provisions/{chunk_id}` with `useEffect`.
- Concept 7: notices by status (abstained with statutes held, insufficient context, external dependencies, notes).
- `getMeta()` in `client.ts` is unused since the disclaimer became fixed text: remove or keep for a later Help page.
- `.env.example` is left uncommitted: it blanks `COMPOSE_PROJECT_NAME` and adds a commented HPC node URL. Revert it.
- Consider rotating the DeepSeek key (it was printed once in a tool output during debugging).
