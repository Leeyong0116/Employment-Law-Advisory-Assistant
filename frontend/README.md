# GetRight frontend

Browser interface over the M5 API. It only presents what the pipeline already
does; it adds no features of its own (plan `docs/plans/2026-11-01-m6-frontend.md`).

Run and check commands: see the root `README.md`, section "Frontend".

Notes:
- Versions are pinned exactly (`.npmrc` has `save-exact=true`).
- TypeScript is 5.9.3, not 7: `openapi-typescript` 7.13 requires TypeScript 5.
- `src/components/ui/` is shadcn/ui source (Radix base, Nova preset). Lint
  warnings in those files come from upstream and are left as they are.
- Dark mode follows the system setting (`prefers-color-scheme`); there is no switch.
- The Geist font is bundled from npm (`@fontsource-variable/geist`); nothing
  loads from a CDN at runtime.
