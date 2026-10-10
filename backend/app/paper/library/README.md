# Strategy library

The standing field: strategies promoted out of the tournament for repeated validation.

**This directory lives inside the application, and that is deliberate.** It moved here from
`strategy-program/library/` on 2026-08-21, because the application trades from it — `app.paperdesk`
runs `base/` forward on live bars, and `app.tournament.jobs` resolves a round's field from all four
tiers. Cards are application configuration that a research programme happens to author; leaving them
in a research directory made the served app, and its Docker image, depend on a tree with no reason to
be deployed. `Settings.library_dir` locates this directory relative to the package rather than the
repository root, so it travels with an install; `INVDASH_LIBRARY_DIR` points at your own instead.

The programme itself — the protocol, the window matrix, the round records — is still in
`strategy-program/`, and `PROTOCOL.md` §6 remains the rule for moving a card between the tiers below.

Cards here are **not** tournament submissions. The tournament's cards are frozen under
`strategy-program/rounds/<round>/cards/` and must never be edited, because they are the record of what
each analyst committed to before seeing any result. These are working copies, free to change, versioned
by this repo's history.

Every card loads as a `StrategyCard` (`backend/app/tournament/models.py`) and runs through the same
harness. From the application, that is the Competition tab at `/competition`, which launches a round
in-process with progress and a cancel button. From a shell:

```bash
PYTHONPATH="backend;." .venv/Scripts/python.exe -m app.tournament \
  --cards backend/app/paper/library/base \
  --out strategy-program/rounds/<round>/results/<window-tag> \
  --persona uat/personas/pro-investor-01.setup.json \
  --start <ISO> --end <ISO> --skip-pdf
```

The `--persona` flag is still how the *CLI* gets its mandate, and it still reads the UAT persona file.
The served application does not: it uses `app.paper.mandate.default_mandate()`, which reproduces those
same numbers in code. `tests/test_paper_mandate.py` asserts the two stay equal, because every result
committed under `strategy-program/rounds/` was measured with the persona's figures and a silent
divergence would make a new round incomparable with an old one.

## The two base strategies

**Changed 2026-08-21, when the research phase closed.** `base/` now holds `B-momentum` and `C-trend`;
`A-rotation` moved to `candidates/`. The move was directed by the program's owner rather than decided
by the scorecard, and `PROTOCOL.md` §6 records it as such — `C-trend` has one round of evidence where
the promotion rule requires two on differing windows. Read its place here as a decision about where to
point attention, not as a claim the rule was satisfied.

| id | from | why it is here |
|---|---|---|
| `B-momentum` | tournament `a03-momentum` | Beat SPY in all three prior windows: +87.72% in-sample, +31.97% blind, +119.30% over three years, and held a positive median across round 2's eight regimes. Median hold 69 bars — it holds winners rather than capping them. |
| `C-trend` | `a01-trend` r1, run as `c05-trend` | The trend book: `close > sma(200)` regime filter plus an `ema(20)/ema(50)` trigger on nine AI/semi names, 12% stop, 120-day cap. Right under half the time and profitable regardless — winners 4.1× losers, held a median 118 days against 16 for losers. |

`A-rotation` (tournament `a07-rotation`) was the other card to beat SPY in all three prior windows —
+104.85% / +40.71% / +145.08% — and is now a candidate. It failed nothing; it was displaced.

**A's universe order is changed from the submitted card, and this is the one substantive edit in the
library.** The runner fills in the order symbols appear in `universe` whenever more names qualify
than there are slots, and a07 was submitted in alphabetical order — an accident, which its own
author flagged as "an arbitrary tiebreak, not a 'buy the leader' mechanism." `A-rotation` instead
orders by trailing 12-month return measured through the design cutoff 2026-02-13:
`MU INTC AMD TSM SOXX NVDA AVGO QCOM MRVL`.

**Read that change with the sensitivity result beside it.** Twelve orderings of the identical card
were run over the full three years (`docs/tournament/results/a07-order/`):

| | return |
|---|---|
| best of 10 random orderings | +161.83% |
| relative-strength order (now `A-rotation`) | **+158.74%** |
| median random ordering | +142.21% |
| alphabetical, as submitted | +145.08% |
| worst of 10 random orderings | +107.98% |

Ordering alone moves the result across a **53.9-point spread, σ = 21.2 points**. Relative strength
ranks 9th of 10 against random draws — better than the alphabet, and *inside* the noise, not beyond
it. The ordering fix is a defensible design-time choice, not a demonstrated improvement, and any
future comparison involving A must treat ±20 points as the floor on its uncertainty.

## Variants to compete

Each isolates **one** decision. They are recorded here before being run, so that whatever wins is a
pre-registered hypothesis rather than a search result.

| id | change from base | the question |
|---|---|---|
| `A1-alpha-order` | universe back to alphabetical | Control. Reproduces the submitted card exactly. |
| `A2-cash-headroom` | 4 slots × 22% (was 3 × 30%) | A logged 50–203 cash rejections depending on order. Does relieving the cash squeeze help, or does holding a 4th name dilute? |
| `A3-no-target` | take-profit removed (was 20%) | B's author measured that take-profits amputate the winners that carry a momentum book. A uses one. Does A's 20% cap cost it more than it protects? |
| `A4-tight-stop` | 8% stop (was 12%) | A's worst trade lost 19.9% against a 12% stop, because stops fill at the next open. Does a tighter stop help or just harvest noise? |
| `B1-with-target` | 25% take-profit added | B explicitly rejected take-profits on measured grounds. This tests that rejection directly — B's best trade was NVDA +185.1%, which a target would have cut at 25%. |
| `B2-hold-90` | 90-day cap (was 180) | Ten of B's 41 exits were time-stops. Is the long leash earning its exposure? |
| `B3-concentrated` | 4 slots × 22% (was 6 × 15%) | Does B's edge concentrate in its best signals, or does it need breadth? |
| `B4-tight-stop` | 8% stop (was 12%) | Same question as A4, on a slower book. |

## Candidates for re-validation

Promoted because each has a specific claim worth testing again, not because of headline return.

| id | from | claim being tested |
|---|---|---|
| `A-rotation` | tournament `a07-rotation` | Former base. Beat SPY in all three prior windows and posted +95.28% in `recent`, but its three-year margin sits inside the **53.9-point** universe-ordering spread, so the margin that made it an incumbent may be an artifact of the order its symbols are listed in. That is the claim now being re-tested. |
| `D-13f-newbuys` | `a12-13f-newbuys` r1 | Returned **+56.93% against +11.99%** on a window that is ~72% out-of-sample — the most genuinely blind result in the project. Smallest sample, strongest provenance. |
| `E-asymmetric` | `a10-asymmetric` r1 | +59.53% against +28.46% over its legal window, on a 22.98% drawdown. A low win rate by design; needs a long window to be judged at all. |
| `F-fastrev` | `a09-fastrev` r1 | Held positions only **28% of the time**. Judged as a market substitute it fails; judged as a satellite sleeve it may not. Should be scored against cash-adjusted terms, not raw benchmark. |
| `G-volatility` | `a05-volatility` r1 | The only card besides A and B to beat the blind window. Lost in-sample. 174 trades — the largest sample among the winners. |
| `H-trend-diversified` | `a01-trend` r2 | The cross-asset book. Gave up 32 points of return for a −7.75% drawdown against C's −10.66%. The insurance case, still untested by an accident. |
| `r40-rsi-confirm-slots6` | round 40 (`data/rounds/r40-2026-09/cards/`) | **Directed promotion, 2026-09-09 — not a scorecard promotion, and NOT seated on any book.** `purpose = trading`; the base breakout `close crosses_above bb_mid(20,2)` with an RSI-confirmation conjunct on `_TAXABLE_GROWTH`. The sole positive cell of the persona confirmation-conjunct round: arm-minus-control +4.82pp median adjusted excess (the round's best), the divergence negative control landing at −0.04pp exactly as predicted. That +4.82pp is inside the 21.2pp floor, so round 40's own rule says the conjunct does **not** pay for itself; it is here under observation because it is the family's only directional positive, not because it cleared a gate. Carries a −17.2pp worst window (the higher-median 3-slot sibling's is −30.7pp). **Seated on the trading book by owner direction on 2026-09-09** (`app.paperdesk.desk.AGENT_IDS`), the third directed seat there beside `C-trend` and `I-13f-duquesne-2026q2`; the desk discloses it as a candidate seated by decision (`PROTOCOL.md` §9, `data/rounds/r40-2026-09/REPORT.md`). |
| `r34-ma-crossover-on` | round 34 (`data/rounds/r34-2026-09/cards/`) | **Directed promotion, 2026-09-09 — not a scorecard promotion.** `purpose = roth`; the 10/30 EMA crossover inside a 200-day filter on eight industry ETFs (`XME XRT XHB XSD XOP XBI ITA VNQ`) that share no ticker with any taxable card. Best cell of the disjoint sector family: median adjusted excess +1.24pp, hit rate 5 of 8, worst window −9.95pp, Pareto frontier. That margin is inside the 21.2pp floor by a factor of seventeen and its own plan pre-registered "nothing promoted"; it is here because the owner directed it, recorded in `PROTOCOL.md` §9 beside `C-trend`. Advances only by the rule: two qualifying rounds on differing windows, margins outside the floor. |

## Real-world constraints the harness enforces

These are already enforced by the runner and broker. They are recorded because a strategy that looks
good only when one of them is relaxed is not a strategy.

**Information timing**
- **13F filings become public up to 45 days after quarter end.** A filing may be acted on from its
  **filing date**, never its period date. `as_of` must be passed on every institutional call.
- **NPORT-P is ~60 days.** Registered funds file NPORT, not 13F — an ETF does not file a 13F.
- §13(f) covers US-listed equities only. Puts and calls appear as separate lines: Scion's four
  largest disclosed holdings, 95% of that book, are option lines. A long copy of that book takes the
  opposite of the trade.
- **A 13F-derived universe may only be used in a window that starts after the filing date it was
  derived from.** The lookahead guard does *not* enforce this — it checks that an indicator is causal
  on symbols already chosen, and cannot know when the *basket* became knowable. This is a rule for
  whoever configures the run, and it is the one constraint here that is enforced by discipline rather
  than by code.

**Execution**
- Decisions use data strictly before the decision session; fills happen at the **next session's open**.
- **Stops are evaluated against the previous close**, not the intraday low, because the
  decision-maker cannot see the session's low. Stop-outs land later and worse than an intraday check
  implies — A's worst trade lost 19.9% against a 12% stop.
- Deterministic adverse slippage; commissions and fees charged; whole shares only; minimum clip
  enforced; cash settlement respected.
- **No dividends.** Benchmark and strategies alike trade price only. SPY returned +75.40% price-only
  over three years against +81.32% total return, so every margin measured here flatters the strategy
  by roughly six points over three years.
- **The universe is fixed for the whole run.** The engine cannot rotate a universe mid-window, which
  is a material limitation for any signal that refreshes — a 13F strategy in this harness is a single
  stale snapshot held for the whole window, not a live strategy.

**A risk control currently relaxed** — the persona mandate caps a single name at 25% of the book. The
tournament raised that to 100% so concentrated cards could run as written; `A-rotation` at 30% and
`A2`/`B3` at 22% depend on it. Runs that keep the real cap use `--honour-persona-cap`, and any result
quoted without it should say so.

## Window matrix

One window is one draw. The point of the matrix is a distribution.

| tag | window | sessions | SPY (price) |
|---|---|---|---|
| `full` | 2023-08-21 → 2026-08-18 | 751 | +75.40% |
| `insample` | 2023-08-21 → 2026-02-13 | 624 | +55.81% |
| `blind` | 2026-02-17 → 2026-08-18 | 127 | +12.84% |
| `y1` | 2023-08-21 → 2024-08-20 | ~252 | — |
| `y2` | 2024-08-21 → 2025-08-20 | ~252 | — |
| `y3` | 2025-08-21 → 2026-08-18 | ~247 | — |
| `h1`…`h6` | six consecutive ~125-session halves | ~125 each | — |

Each window carries **its own benchmark**, computed by the runner over that window's own sessions.
Never compare a short-window return to the three-year +75.40%.

**Eligibility floors.** Not every card can run in every window; a card whose universe holds a symbol
without enough history raises `GuardFailed` rather than running on partial data.

| card | earliest legal start | bound by |
|---|---|---|
| A, B, C, F, G, H and all A/B variants | 2023-08-21 | — |
| `E-asymmetric` | **2025-01-07** | NBIS, first bar 2024-10-21 |
| `D-13f-newbuys` | **2025-12-04** | SNDK, first bar 2025-02-13 |

`D` additionally must not start before **2025-11-14**, the filing date its universe was derived from.
The guard floor happens to be later, so it binds first — but do not rely on that if D's universe
is ever changed.

## Scoring rules, carried over

- Benjamini-Hochberg across **every** strategy tried in a comparison, never within a subgroup. A
  correction over 8 when 16 were run is the failure the correction exists to prevent.
- The binomial test used for p-values is **two-sided against a fair coin**. It flags win rates far
  below 50% as strongly as those above, and a long-only book in a rising market clears or fails it
  for reasons unrelated to skill. **q-values here are not evidence of skill.**
- Rank strategies on their behaviour across the matrix, not on the best single window.
- Report exposure beside every return. Over 2023-2026 exposure correlates with return at ρ = 0.648;
  a strategy that beat the benchmark while 95% invested has demonstrated less than the number suggests.

## What the tournament established, so it is not re-litigated

- **13F, as a signal, did not work** — four independent tests, including a conviction basket at
  −3.93% and a 52% beat rate on fresh initiations. `D` is here on the strength of its *window*, not
  because the signal was vindicated.
- **`a08-slowtrend` has never traded** in any window tested. Its `ema(300)` gate has never opened.
  It is not in this library.
- **Round one beat round two in all ten head-to-head pairs**, in a window where SOXX returned
  +228.88% against SPY's +81.32%. That is a fact about the window, not about concentration. `H` is
  here to keep the other side of that question alive.
