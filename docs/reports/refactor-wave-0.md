# Refactor Wave 0 — guard, copy, and interaction primitives

Date: 2026-09-05. Executes Phase P and Phase 0 of `docs/APP-UX-REFACTOR-ANALYSIS.md`, plus the
interaction-primitive groundwork (0.7) the later waves build on. No page layout changed in this
wave; this is the safe, mechanical foundation.

## What landed

### Personal information (Phase P)
- **Ignore rules** for `docs/local/`, `data/vault/`, `data/i18n_cache/`, `data/round33/*.log` —
  the last three were untracked but *unignored*, one `git add -A` from being committed.
- **Real-ledger documents relocated** to the ignored `docs/local/`: `HANDOFF.md`, `MIGRATION.md`,
  and six reports (`phase-1..3`, `import-path`, `uat-runs-3-5`, `uat-runs-6-8`) that quoted the
  owner's own per-lot figures, account slugs or ACAT control numbers. Each keeps a tracked stub
  that preserves the *ratios* (e.g. "92 of 1,042 disposals carry no cost basis, holding 82% of the
  reported gain") and drops the dollars. `docs/reports/LOCAL-REPORTS.md` indexes what moved. Reports
  whose only figures are institutional 13F totals or synthetic paper-book seed capital stayed put.
- **Contact e-mail → setting.** The owner's address was a literal in four provider User-Agent
  strings. It is now `Settings.contact_email` (`INVDASH_CONTACT_EMAIL`), read at request time; the
  real value lives only in the gitignored `.env`. SEC EDGAR's fair-access policy needs a real
  address at runtime, which is exactly why it cannot be a tracked literal.
- **Windows username scrubbed** from 25 tracked files — prose to `<repo>`/`<user>`, shell scripts to
  `%~dp0`/derived paths, Python scripts to `Path(__file__).resolve().parents[N]`, recorded log/JSON
  paths to `<user>`. the tracked-tree username scan is now clean.
- **Agent briefs genericised**: the 15 `.claude/agents/*.md` files no longer narrate the owner's
  broker names as *their* accounts or carry per-account row counts; every bit of adapter, tax and
  fixture guidance stayed.
- **A guard, `tools/check_no_pii.py`**, registered in pre-commit beside `detect-secrets` (which sees
  keys, not money/e-mail/username). It runs in two modes: **default** enforces only the two leaks
  with zero legitimate occurrence — the Windows username and any e-mail in `backend/**` /
  `strategy-program/**` — so it exits 0 on the tree today and fires only on a regression;
  **`--strict`** additionally flags dollar figures in docs and account slugs, which flag hundreds of
  legitimate pre-existing occurrences and are the repository-goes-public decision recorded in
  `docs/BEFORE-PUBLISHING.md`, not a per-commit gate. The split is why the hook is shippable.
- **`docs/BEFORE-PUBLISHING.md`** records that `origin` is private, that all five branches are
  pushed, and that going public requires first deciding on the corporate-e-mail-in-history question
  (a `git filter-repo` rewrite + force-push, the one irreversible step) — stated as a precondition.

### Copy (Phase 0.1, partial)
- The load-error sentences that were copied across nine shards now have one home in `common`:
  `apiError`, `cannotReachApi`, `couldNotLoad`, `couldNotLoadThis`, `loadingWhat`. Adopting these at
  the call sites (deleting the ~30 per-shard copies) is a mechanical follow-up left for a page wave,
  since each call site is on a page another wave rewrites.

### Interaction primitives (Phase 0.7)
The `docs/APP-UX-REFACTOR-ANALYSIS.md` §3.6 contract, built and unit-tested, ready for adoption:
- **`useUrlState(key, fallback, {valid, history})`** — selection state in the query string; a stale
  or hostile value falls back rather than throwing; two hooks on one page never clobber each other's
  params; setting the fallback clears the key.
- **`FolderTabs`** — the "pick one of ≤ 8" control, badged and tone-coded, full WAI-ARIA tabs
  keyboarding (arrows wrap, Home/End), horizontal-scroll overflow. `FOLDER_TAB_MAX = 8` is the
  threshold above which a caller uses a dropdown instead.
- **`Skeleton`** — shaped placeholders with a polite live message and optional progress count.
- **`ConfirmSheet`** — a focus-trapped confirm dialog with a "what will change" preview and a busy
  state, for the mutations that commit silently today.
- **`Toast` / `ToastRegion` / `useToasts`** — a live-region toast stack with Undo.
- A new `interaction` message shard carries their strings.

## Verification (run by the orchestrator over the combined tree)
- Frontend `tsc --noEmit`: clean.
- New primitive + hook + i18n tests: 112 pass; catalog 2,985 keys, 0 over the prose budget.
- Full frontend suite: 1,389 pass. Three failures, none from this wave: two (Institutions fund
  selector, PaperDesk inception) are full-suite contention flakes that pass in isolation (112/112);
  one (`/backfill` route) is a concurrent session's in-flight feature, not wired yet.
- Backend: `ruff` clean, `mypy` clean on the four changed modules, 313 provider/institution tests
  pass, every scrubbed Python file compiles, `thesis_loop_results.json` still parses, settings load.
- PII guard: default mode exits 0 on the tree; a planted `backend/` e-mail and a planted username
  both trip it; strict mode still reports the 714 pre-publishing items.

## Deliberately not in this commit
- `strategy-program/tools/phase_b_daily.cmd` — its username scrub is entangled with a concurrent
  session's substantial `--no-launch` rewrite of the same file; it lands with that session's commit.
  The working-tree username scan stays clean.
- Adopting the new `common.*` error keys and the interaction primitives into pages — that is the
  page-rewrite waves (1 and 2), which run file-disjoint against these primitives.
