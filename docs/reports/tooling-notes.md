# Tooling and orchestration notes

Written for whoever runs the next batch of work on this repo — human or agent. Everything here was
learned by doing it wrong at least once.

> **2026-08-12 correction.** The "secret scan before every commit" line under Verification checklist
> below described a discipline, not a mechanism: at the time it was written there was no git hook, no
> `.pre-commit-config.yaml`, and no CI enforcing it — a security audit caught the gap. There is now a
> real hook (`.pre-commit-config.yaml`, `detect-secrets` + `ruff`, installed via `pre-commit install`
> — see `MIGRATION.md`). The paragraph below is corrected to say so; it is not just a claim anymore,
> but keep in mind a hook is opt-in per clone until someone runs the install step.

## Environment facts that cost time to rediscover

- **There is no bare `python` on PATH.** Use `.venv\Scripts\python.exe`. `python`/`python3` resolve
  to Windows Store stub aliases that fail silently in confusing ways.
- **`pytest` must run from `backend/`.** `backend/pyproject.toml` sets `testpaths = ["../tests"]`. Run
  it from the repo root and you get spurious collection errors that look exactly like pre-existing
  breakage. Two separate agents reported "8 pre-existing collection errors" that were this and
  nothing else.
- **`npm` is not on PATH.** Use `"/c/Program Files/nodejs/npm.cmd"` or prepend `C:\Program
  Files\nodejs`.
- **Vite binds 5174, not the 5173** in `.claude/launch.json`, when 5173 is taken. Measure, don't
  assume.
- `pytest -q` sometimes does not render its final summary line for the full multi-file run in this
  terminal. `-p no:warnings` without `-q`, or `-v`, gives a reliable count. A missing summary is not
  a missing result.
- **Docker is not installed here**, and there is no WSL distribution to reach a daemon through. The
  compose files are written and unverified — see `docs/DOCKER.md`.

## The orchestration pattern

Opus orchestrates, Sonnet workers implement in parallel on file-disjoint shards, manager verifies
everything itself before committing. Over this session that ran about a dozen workers.

**What earned its keep:**

- **Worker reports are claims, not facts.** Every "tests pass" got re-run by the manager. Several
  were right; the ones that were not mattered enormously. A worker reported the responsive layout
  fixed with 21 measurements; re-measuring confirmed it. A worker justified a design decision with a
  mechanism that did not exist in the code; reading the loop to check surfaced the most serious
  defect of the session.
- **Briefs must carry verified facts, not remembered ones.** Every brief in this session quoted real
  file:line and real command output. The one time a brief carried a wrong claim — an earlier session
  told an agent that recursive indicators are not prefix-invariant and asked for a tolerance — the
  wrong claim went straight into the code. Probe first, brief second.
- **Tell workers what a good refusal looks like.** Several of the best outcomes were workers
  declining: the citation-contract worker declined the hedge deny-list and pinned the gap with a
  test; the container worker refused to claim a build it could not run; the cache worker declined to
  add a decorative parameter to `reverse_conditioning` after checking it was already batched. Briefs
  that say "declining is an acceptable answer if you say why" get better judgement than briefs that
  imply every listed item must ship.
- **Ask for the margin, not just the pass.** "Zero survivors across 700 null series" is much less
  informative than "zero survivors, and the closest near-miss reached holdout p=0.0113 and was
  stopped by the sample-size floor at 19 observations." The second tells you which guard is
  load-bearing.

**What went wrong, and the rule that came out of it:**

- **File-disjointness is not enough when a module is injected as a `Protocol` collaborator.**
  `backtest/scan.py` was fenced to one worker; `backtest/service.py` declares a `Scan` Protocol and
  a lazy `_default_scan()` returning that module. Widening the signature broke a file nobody owned.
  **Before sharding, grep for the module name in `Protocol` declarations and `_default_*()` factories,
  and include those files in the same shard.**
- **A worker that finds an error outside its fence should say so, not fix it.** That is what made the
  break above visible — one worker refused to claim a clean `mypy` and isolated its own files to
  prove the error was not its. Put that instruction in every brief.
- **Session limits kill background agents mid-flight**, sometimes with partial work on disk and a
  final message that reads like success. Four died at once here. Recovery is: `git status`, then run
  the full verification, then read the diff of whatever changed — do not trust the last thing the
  agent said it was about to do. In this case one had written a test file missing its `import math`,
  and one had left a parametrized case that could not pass by construction.
- **Give exactly one worker the browser.** Two agents driving the preview pane collide. Combining the
  UI-checklist walk with the design review into a single browser-owning shard worked well.
- **The browser pane goes unresponsive intermittently.** `computer` screenshots failed for one worker
  mid-run. `read_page` and `javascript_tool` kept working. Fall back rather than stall, and say which
  claims rest on measurement versus on a screenshot.

## Driving these engines from a script

Notes from the research run, which is the least-travelled path in the codebase:

- **`_bars_frame` is private to `app/thesis/loop.py`** and there is no exported equivalent. Any
  caller wanting to drive the loop from an in-memory frame has to reimplement it. Worth exporting.
- **`build_scan` and `build_event_study` read bars from the store internally** with no way to inject
  a frame. Driving them against synthetic or borrowed data means calling
  `events.event_study` / `guards.check` / `scan.scan` directly and assembling the result by hand.
  An injectable `bars` parameter — the way `loop.run` already has one — would remove that.
- **Always point `Settings(store_dir=...)` at a temp directory for research runs.** A holdout is one
  look, ever, per ticker, and it is stateful in `store/thesis.sqlite`. A careless run permanently
  burns the real one. The research run in `docs/research/` used an isolated store and verified
  afterwards that production still held only the Phase 9 SOXL row.
- `scipy` is deliberately absent. Statistics are hand-implemented so they stay auditable. Do not add
  it; extend the hand-rolled functions instead.

## Verification checklist before any commit

```
cd backend
..\.venv\Scripts\python.exe -m pytest -p no:warnings
..\.venv\Scripts\python.exe -m ruff check .
..\.venv\Scripts\python.exe -m mypy --strict app
cd ../frontend && npm run typecheck && npm run build
```

Then the secret scan. As of 2026-08-12 this is an actual pre-commit hook
(`.pre-commit-config.yaml`, `detect-secrets` against `.secrets.baseline`, plus a `ruff check` hook)
rather than a manual step — run `pre-commit install` once per clone (see `MIGRATION.md`) and it fires
automatically on every `git commit`. It is not enforced server-side, so a clone that skipped the
install step, or a commit made with `--no-verify`, gets none of this. As a manual backstop regardless
of whether the hook is installed: confirm the `.env` key appears in **zero** staged files, `.env`
itself is not staged, and no `data/`, `.sqlite`, `.duckdb` or `.parquet` path is staged.

## The recurring defect shape, for whoever reviews next

Across three rounds of QA the same shape kept appearing: **a claim that outran its code.** A
docstring describing a layer that did not exist. A comment reasoning correctly about a failure and
then fixing it at one call site instead of on the type. A cache constructed, threaded through two
layers, and deleted. A falsification criterion recorded, hashed, required — and never evaluated.

These survive review because the code *reads* as though the work were done. The check that catches
them is not "does this look right" but **"what would fail if this were not true?"** — and if the
answer is nothing, that is the bug.
