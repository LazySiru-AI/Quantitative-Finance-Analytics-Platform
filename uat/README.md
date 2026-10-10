# UAT: persona-driven acceptance testing

A synthetic professional investor, played by Claude Haiku, is given notional capital and made to
trade the dashboard for a week. It files structured findings as it goes. Those findings are verified
against the source, synthesised into [`feedback/BACKLOG.md`](feedback/BACKLOG.md), and the next run
re-tests them.

The point is not the P&L. The point is that a user with a real job to do, real constraints and real
professional reflexes will trip over things a test suite cannot express — and will do it against the
actual ingest, lot, wash-sale and pricing code rather than a fixture.

> **Everything here is synthetic.** No trade is real, no capital is real, nothing is investment
> advice. Runs are committed precisely *because* the data is fabricated and carries no personal
> financial information.

## What is in here

| Path | Committed | What it is |
|---|---|---|
| `personas/` | yes | Persona spec (prose) and mandate (machine-readable) |
| `schema/` | yes | JSON Schema for findings and orders |
| `harness/` | yes | Paper broker, session CLI, ingest bridge, feedback plumbing |
| `runs/<run-id>/` | yes | One week: orders, fills, session journals, findings, metrics |
| `feedback/BACKLOG.md` | yes | Verified, deduped, prioritised — the loop's output |
| `sandbox/` | **no** | Disposable ledger, cache and a copy of the bar store |

## Isolation

A UAT run must never touch the user's real financial data, and the user must never find synthetic
trades in their portfolio. Both directions are enforced:

- `harness/ingest.py::sandbox_settings` **constructs** a `Settings` pointing `data_dir`, `store_dir`
  and `cache_dir` at `uat/sandbox/`. It does not read the environment, so no ordering accident can
  hand a caller the real `ledger_path`.
- `harness/serve.py` starts a **second** backend on port 8001 against the sandbox, and refuses to
  start if settings resolve anywhere else. The normal instance on 8000 keeps serving the real ledger,
  untouched.
- `frontend` runs a second dev server on 5175 via `vite --mode uat` (see `frontend/.env.uat`), which
  proxies to 8001. `npm run dev` is unchanged.
- `harness/serve.py` starts the sandbox with authentication disabled by default (`INVDASH_AUTH_ENABLED=0`),
  regardless of the real backend's own default. The sandbox holds only synthetic data, binds loopback
  only, and is driven by an automated persona rather than a person who can log in -- a login screen
  there would block the entire run and protect nothing. Pass `--auth` to leave authentication on when
  a run is deliberately testing the login flow itself; this never affects the real instance on 8000.

The sandbox needs daily bars. They are copied from `data/store/bars` — public OHLCV, nothing
personal — and gitignored as rebuildable.

## Running a week

```bash
# one-time: give the sandbox a bar store
cp -r data/store/bars uat/sandbox/store/bars
```

Start both sandbox servers (`uat-backend`, `uat-frontend` in `.claude/launch.json`), then:

```bash
export PY='PYTHONPATH="backend;." .venv/Scripts/python.exe -m uat.harness.run'

$PY init --start 2026-08-03 --end 2026-08-07
$PY brief    --run-id 2026-08-03_pro-investor-01 --session 1 --watch SPY XLE QQQ
$PY orders   --run-id 2026-08-03_pro-investor-01 --session 1 --file orders-s1.json
$PY close    --run-id 2026-08-03_pro-investor-01 --session 1 --journal "..."
$PY feedback --run-id 2026-08-03_pro-investor-01 --session 1 --file findings-s1.json
# ... sessions 2-5 ...
$PY finalize --run-id 2026-08-03_pro-investor-01
```

Each command prints JSON and nothing else, so a subagent can consume it. Sessions are separate
processes — the decision-maker between them is a subagent, not a function call — so the book lives in
`runs/<run-id>/state.json` and is reloaded each time.

`close` ingests that session's fills, so the next morning's dashboard shows the persona's own book.

## The two properties the harness guarantees

**No lookahead.** `AsOfMarket.history` takes its as-of from the instance, never from the caller, so a
session cannot widen its own window. Orders are decided on data through session *D−1*'s close and
filled at session *D*'s open. This matters more than in a backtest: the decision-maker is a language
model, and a model shown next week's close will use it while sincerely reporting that it did not.
There is no post-hoc test that separates a lucky call from a leaked one, so the leak has to be
impossible at the boundary.

**Real ingest.** Fills are rendered as a Robinhood-shaped activity CSV and loaded through
`registry.resolve → adapter.parse → sqlite.insert_transactions`. Writing to the ledger directly would
skip header detection, the adapter, provenance hashing and idempotent insertion — the four stages most
likely to be wrong. `finalize` re-imports every session export to confirm the ledger's idempotency
claim rather than trusting it.

Two deliberate departures from a real export, both in `ingest.py`'s docstring: no CUSIPs (minting
plausible security identifiers into a provenance-first ledger is worse than omitting them), and
regulatory fees as their own `FEE` rows rather than netted into the sell.

## Verifying findings — do not skip this

A persona finding is a **report**, not a fact. In the first run, **three of four reported blockers
did not reproduce**: the browser automation's synthetic clicks were not reaching React's handlers, so
working controls looked dead. Unverified, they would have topped the backlog.

```python
from uat.harness.verify import apply_verdicts
apply_verdicts(Path("uat/runs/<run-id>/feedback.jsonl"), verdicts)
```

Verdicts are `confirmed`, `partly-confirmed`, `not-reproduced`, `works-as-designed`, `unverified`,
each with the source locations read while checking. `apply_verdicts` refuses to stamp a run with a
finding it has no verdict for — a partly-verified run that looks fully verified is worse than an
obviously unverified one.

## Known harness caveats

- **Marks post-date the session.** The portfolio endpoint prices from the last stored daily close by
  design, and the store runs past the replayed week. Marks in the dashboard will legitimately
  post-date the session being traded. Not an application defect; see the backlog's "Not defects".
- **Adverse slippage is deterministic**, not random, so two runs of the same decisions agree. A UAT
  dataset that cannot be reproduced cannot confirm a fix.
- **Settlement uses weekday arithmetic**, not an exchange calendar. It exists to stop the persona
  respending proceeds in the same session; a holiday shifting settlement by a day changes no decision
  recorded here.

## Adding a persona

Copy `personas/pro-investor-01.{md,setup.json}`, change `persona_id`, the mandate and the
`feedback_focus` list. The prose spec is what the subagent reads to get into character; the JSON is
what the paper broker enforces. Nothing else needs changing — `init --persona` takes the path.

The persona's professional reflexes are the instrument. `pro-investor-01` cares about as-of
timestamps, percentage-unit ambiguity, partial totals and provenance, and those preferences are what
generated the useful findings. A vaguer persona produces vaguer feedback.
