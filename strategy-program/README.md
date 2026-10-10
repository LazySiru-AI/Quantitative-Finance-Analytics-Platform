# Strategy Program

A continuously-looped competition for trading strategies, run against the investing dashboard's own
backtest harness. Analyst agents design strategy cards; the cards are traded blind across a matrix of
market regimes; the results promote and demote strategies in a standing library; the next round runs
against a harder field and a longer record.

It began as a side project that read the dashboard's bar store and reused `backend/app/tournament`
and `backend/app/backtest`, and wrote nothing the application read. **That second half stopped being
true on 2026-08-21**, when `/api/competition` and `/paper-desk` shipped and began reading this
directory. Two things followed, in that order.

**The library left.** The strategy cards now live in `backend/app/paper/library/`, because the
application trades from them: `app.paperdesk` runs `base/` forward on live bars every time the tab is
opened, and `app.tournament.jobs` resolves a round's field from all four tiers. Cards are application
configuration that a research programme happens to author, and keeping them in a research directory
meant the served app — and its Docker image — depended on a tree that had no reason to be deployed.
`Settings.library_dir` locates them relative to the package, with an `INVDASH_LIBRARY_DIR` override
for pointing at your own. The trading mandate left for the same reason and now lives in code, at
`backend/app/paper/mandate.py`.

**Then the rounds left too.** They now live in `data/rounds/`, reached through
`Settings.rounds_dir` (`INVDASH_ROUNDS_DIR` to point elsewhere). A round is *generated output that
grows* — the application writes it, and each one is megabytes of run files — which is a different kind
of thing from the library's fixed, hand-authored cards, and it belongs in the data directory the app
already owns rather than inside the installed package. `data/rounds/` is tracked in git and there is a
long comment in `.gitignore` making sure it stays that way; it contains no financial data, only
backtest output over public prices.

**What is left here is the programme itself**: the protocol, the window matrix, the constraints, the
defects the programme found in the engine, and the offline tools. Rules and instruments, not results.
The served application no longer resolves a single path into this directory — `tests/test_deployment_paths.py`
is what holds that line — so nothing here has to be deployed for the dashboard to run.

## Layout

```
strategy-program/
  README.md         you are here
  PROTOCOL.md       the loop: phases, anti-overfitting rules, promotion and demotion
  WINDOWS.md        the regime window matrix, symbol history tiers, the eligibility gate
  CONSTRAINTS.md    real-world constraints, and which are enforced by code vs by discipline
  DEFECTS.md        engine defects the programme found, with reproductions
  tools/
    windows.py      window matrix and per-card eligibility
    score.py        the scorecard
    attribution.py  which trades produced a card's number, exactly
    run_round.sh    the shell runner (refuses to start if a round is already live)
```

Neither the field nor the results are in this tree any more:

```
backend/app/paper/          shipped with the application
  mandate.py                the desk's trading constraints, in code
  library/
    README.md               the field, and the question each card asks
    base/                   the two primary strategies: B-momentum and C-trend
    variants/               one-decision variations on A and B, each pre-registered
    candidates/             promoted from earlier rounds, awaiting confirmation
    retired/                kept on disk with a note recording what retired them

data/rounds/                written by the application, tracked in git
  r1-2026-08/
    BRIEF.md                what the analysts were given
    cards/                  submissions, frozen at the end of the design phase
    memos/                  each analyst's reasoning, written before any result existed
    results/                runner output: one trade log per card per window
    reports/                one report per card, from that card's own trade logs
    REPORT.md               the round report
```

`rounds/<id>/results/<window>/runs/` is a published interface — `/api/competition` reads that exact
shape — so renaming it breaks a page.

## The two base strategies

Two rounds ran, and the research phase closed on 2026-08-21 with these two:

| id | from | why it is here |
|---|---|---|
| `B-momentum` | tournament `a03-momentum` | Beat SPY in all three windows the prior tournament tested (+87.72% in-sample, +31.97% blind, +119.30% over three years) and held its median through round 2's eight regimes. Median hold 69 bars — it holds its winners rather than capping them, and its own memo shows a take-profit would have amputated the minority of large trades its edge lives in. |
| `C-trend` | round 1 `c05-trend` | A trend book on a nine-name AI/semi universe: `close > sma(200)` as a regime filter, `ema(20)/ema(50)` as the trigger, 12% stop, 120-day cap. Right less than half the time and profitable anyway — winners 4.1× losers, held a median 118 days against 16 for losers. |

`A-rotation`, the prior incumbent, moved to `candidates/`. It was the other card to beat SPY in all
three prior windows (+104.85% / +40.71% / +145.08%), and it did not fail anything; it was displaced by
a decision, not by a scorecard.

**All three are held at arm's length, and `C-trend`'s promotion is the weakest link in the library.**
It has one round of evidence where §6 requires two on differing windows, and it was promoted by
direction rather than by rule — recorded as such in `PROTOCOL.md` §6, deliberately, so nobody later
reads its presence in `base/` as evidence it has not got. `A-rotation`'s three-year margin sits inside
a **53.9-point** spread attributable to universe ordering alone, and every prior-tournament figure
above was measured in a single continuous bull market where exposure explained most of the field's
returns.

The full library, including the eight variants and six candidates and the question each one asks, is
in [`backend/app/paper/library/README.md`](../backend/app/paper/library/README.md).

## What this program corrects

The tournament that preceded it established one thing above all others: **rank correlation between
in-sample return and blind return was Spearman ρ = 0.162.** Performance on the data an author studied
predicted almost nothing about performance on data nobody had seen.

It had three structural weaknesses, and this program attacks each directly.

| weakness | correction |
|---|---|
| **One regime.** Every result came from a single continuous bull market with no down calendar year. Its own report said the regimes the strategies feared "still have not occurred." | A regime matrix reaching back to 2007 — the GFC, COVID, and 2022's bear. 86 symbols have the history to be tested against all of it. |
| **Exposure masquerading as skill.** Exposure correlated with three-year return at ρ = 0.648. | Ranking on exposure-adjusted excess: return minus `exposure × benchmark`. |
| **A selected universe.** Analysts were confined to 43 tickers the user already traded, in a window where the semiconductor complex tripled. | The universe is open. Analysts pick from all 173 symbols with bars — and universe choice determines which regimes a card can be tested in, so breadth of history becomes the analyst's own trade-off to make. |

The gate that ties the third correction together: **a card eligible in fewer than three of the five
main windows is unranked.** Its numbers are published; it is excluded from the ranking. Nobody is told
which symbols to pick. Everyone is told in advance what a narrow, recent universe costs.

## Running a round

**From the application: the Competition tab.** `/competition` lists the library and every past round's
leaderboard against SPY, drills into which trades produced each number, and launches a round with
progress and a cancel button. The runner behind it (`app.tournament.jobs`) is in-process and holds a
single-slot lock — one round at a time, no shell loop to orphan.

**From a shell**, still supported, and the concurrency caveat is now smaller than it was. `DEFECTS.md`
D3 is fixed: store reads are in-memory and no longer collide, so phases 3–5 are not serial for
correctness reasons. What limits them is the 16 GB host. The reconciliation step below is **not**
optional either way — the runner walks past a failed card by design, so a shortfall is silent.

```bash
PYTHONPATH="backend;." .venv/Scripts/python.exe -m app.tournament \
  --cards strategy-program/rounds/r1-2026-08/cards \
  --out data/rounds/r1-2026-08/results/<window-tag> \
  --persona uat/personas/pro-investor-01.setup.json \
  --start <ISO> --end <ISO> --skip-pdf
```

One invocation per window. **After every invocation, check the output for `FAILED` and reconcile the
number of files in `results/<tag>/runs/` against the number of cards submitted.** Then:

```bash
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
  --results data/rounds/r1-2026-08/results --json scorecard.json
```

## Reading a result from this program

Three habits, each earned by a specific mistake already made in this project:

1. **Read exposure beside every return.** A card that beat its benchmark while 95% invested has
   demonstrated less than the number suggests.
2. **Read the worst window beside the median.** The median is a summary; the worst window is the part
   that would actually have happened to you.
3. **Check the margin against the ordering floor.** Any comparison between two cards decided by less
   than roughly 20 points of three-year return may be an artifact of the order symbols were listed in.
