# Devlog 2026-11-11: M6 answer view, notices and source panel

Branch `m6-frontend`. Plan `docs/plans/2026-11-01-m6-frontend.md` ("Amendment 2026-11-04", simplified Tasks 4 to 6).

## 1. Summary

- The author built the source panel up to the `useEffect` fetch (steps 8.1 to 8.3), then asked Claude to finish the main screen, the answer view and the source panel; the author reviews the result.
- Simplified Tasks 4, 5 and 6 are now implemented. Frontend tests: 19 passed (4 files). Type check, lint and production build clean.
- History sidebar: first left out (deferred on 2026-11-04), then built later the same day at the author's request (Section 5).

## 2. Test fixtures from the real API

`frontend/src/test/fixtures/` holds responses captured from the running API on 2026-11-11 (DeepSeek `deepseek-flash`, index `459843bf28ba`), so tests check the real shapes:

| Fixture | Case |
|---|---|
| `answer_answered.json` | "How many days of annual leave do I get?" (Peninsular): 5 citations, EA s.60E |
| `answer_abstained.json` | "How do I withdraw my EPF savings?": gate abstention, `low_score` |
| `answer_insufficient.json` | "What is the minimum wage in Malaysia?": passed the gate, model replied INSUFFICIENT_CONTEXT |
| `answer_sarawak_maternity.json` | "How long is maternity leave?" (Sarawak): cites A1754 s.24 (98 days), carries the worker/employee note |
| `provision_EA1955_s60E_1.json` | in force, pages 63 to 64 |
| `provision_SWK76_s84_1.json` | superseded, `amended_by: [A1754_s24]` |
| `provision_A1754_s24.json` | amendment, commencement 2025-05-01 |
| `provision_EA1955_s9.json` | deleted by Act 40 of 1966, with an in-force note |

Observation: the minimum-wage question (out of scope, Minimum Wages Order not held) passed the gate and was stopped by the model, not the gate. Consistent with the known 60% to 70% out-of-scope gate rate.

## 3. What was built

- **Main screen (`App.tsx`)**: header, composer card (question box with a 2,000-character limit, required region dropdown, Send), disclaimer under it, the asked question and region shown above the answer, one loading line (`aria-live`), error with Retry (resends the last request). A ref blocks a second request on a double click before React re-renders the disabled button.
- **Answer view (`AnswerView.tsx`)**: answer text with `[n]` marker buttons (only when a citation with that number exists); Sources list where each row also opens the panel and shows a status badge for non-current law (Deleted, Omitted, Amended later, Not yet in force); notices for gate abstention (backend message with the statutes held) and insufficient context, styled as information (`role="status"`, info icon, neutral colours); external dependencies ("Part of this depends on X, which GetRight does not hold"); notes.
- **Source panel (`SourcePanel.tsx`)**: one chunk at a time; title from the provision's citation; content with line breaks kept; status banner (deleted with `deleted_by`, omitted, not yet in force, superseded with a button that opens each `amended_by` chunk in the panel); commencement; notes from the source; statute, version and pages; link to the official source; the traceability note. A 404 keeps the stored citation label as the title and says the index may have changed. Each chunk is rendered with `key={chunkId}` so state starts fresh and an old text never shows under a new heading.

Tests (C7, critical behaviour only): Send rules, region sent, one request on double click, error and Retry; marker and Sources row open the right citation, unknown marker stays text, abstention lists the statutes held, insufficient context notice, notes / external dependencies / status badge; panel content and details, superseded banner and amendment link, deleted banner and note, 404.

## 4. Known limits

- DeepSeek writes markdown (`**bold**`, `- ` lists). The answer is shown as plain text (decision C5), so the asterisks show as typed. Qwen under prompt m4-v2 writes less markdown. Options: accept, or render bold and lists only (needs the author's decision; it would replace C5).
- `multiple_jurisdictions` is only in the stream's retrieval event, not in `GeneratedAnswer`, so the one-page app over `POST /api/ask` cannot show it.
- Superseded banner says "changed this provision"; per the known data issue, some unchanged subsections are also marked superseded (A1754 s.24 marks all 11 s.84 chunks).
- Not checked in a real browser by Claude (no browser available in this session); the author checks the screen.

## 5. Layout change: history sidebar and chat layout (author's decision)

After seeing the one-page version, the author asked for the question box to stay at the bottom like other AI chat apps, with the conversation above, and for the sidebar. Recorded as plan "Amendment 2026-11-11" (reverses C3 / C8 for the sidebar and layout only; history is on the CLAUDE.md Frontend list).

- `src/state/history.ts` (6 tests): browser-only history, key `getright.history.v1`, 50 entries, newest first; malformed entries dropped; full storage keeps the newest entries that fit (halving); blocked storage never throws. Region remembered in `getright.region.v1`.
- `AppSidebar.tsx`: shadcn Sidebar (collapsible; a drawer on phones that closes after a choice), New question, history list, footer "History is kept in this browser only".
- `Composer.tsx`: pinned at the bottom; auto-growing box (`field-sizing: content`, max 12 rem), region dropdown and round Send inside; Enter sends, Shift+Enter new line, Enter during IME composition ignored; disclaimer always under it.
- `App.tsx`: sidebar + scrolling middle column + composer. Sending always makes a new entry (plan D2: the API answers each question alone, so the page never shows two questions as one conversation). Retry answers the same entry. An entry with no answer and no request running (page closed mid-request) shows "Ask again". History is saved by an effect whenever entries change.
- Tests: 28 in total (5 files), 29 after the fix below. App tests cover Send rules, region sent, Enter / Shift+Enter, double click, error + Retry on the same entry, a second question as a new entry, opening an old entry, New question, history and region after a reload.
- Privacy note: the shadcn Sidebar stores its open/closed state in a `sidebar_state` cookie (UI state only, no question text). Questions and answers stay in `localStorage`.
- Bug found by the author in the browser (2026-11-12): black page, console "destroy is not a function". Cause: `useEffect(() => scrollRef.current?.scrollTo?.({ top: 0 }), [activeId])` returned the value of `scrollTo`; in recent Chrome and Edge that is a Promise, and React calls a returned value as the cleanup function. jsdom returns undefined, so the tests passed. Fix: effects use `{ }` bodies. Regression test makes `scrollTo` return a Promise (failed with the same error before the fix). Tests: 29.
- Screenshots could not be taken: the cached Playwright Chromium needs `libnss3` (not installed, needs sudo). The author checks the screen.

## 5a. Theme button and panel font (2026-11-12, author's request)

- Light / dark button (sun / moon) at the top right. Reverses the plan's "no theme switch" (recorded in the plan amendment). `src/lib/theme.ts` + `ThemeToggle.tsx`; `index.css` dark variant is now the `.dark` class instead of `prefers-color-scheme`; `index.html` sets the class before React starts so the page does not flash. Choice stored in `getright.theme.v1`, else the system setting. 1 test (30 in total).
- Source panel text is sans-serif now (was `font-serif`), same font as the rest of the app.

## 6. Next

- Author: review the code and the screen (light and dark system setting, phone width).
- Task 7: real run of the 7 M5 smoke questions in the browser, screenshots, README "Frontend" section.
- Revert `.env.example`; decide about `getMeta()` (unused); tell Dr Azam about the deferred items and the DeepSeek development generator.
