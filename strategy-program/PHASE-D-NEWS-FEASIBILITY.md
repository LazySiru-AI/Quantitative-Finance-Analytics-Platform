# Phase D-news — a feasibility result, reported before the study

*Written 2026-08-26.* This is not the D-news study. It is the answer to whether D-news can be run
as pre-registered, produced by probing the upstream it depends on before building anything on top
of it. The answer is **no, not across the window matrix**, and the reason is a fixed property of
GDELT rather than anything this programme can engineer around.

`AGENTS-INTEGRATION-PLAN.md` Phase D is the gate on Phases E and F. It splits in two:

> - **D-news**, runnable as soon as snapshot storage and the event-study wiring exist. […]
> - **D-social**, not runnable yet. Needs a snapshot table written on a schedule, and time to pass.

Both preconditions for D-news now hold — `app.market.social_history` shipped 2026-08-24, and
`app/backtest/forward.py` has `forward_returns`, `independent_mask`, `independent_count` and
`hit_rate`, with Benjamini–Hochberg correction in `app/timeframes/stats.py`. So D-news was next.

## The premise that turned out to be half true

The plan's reason for believing D-news was runnable:

> News is different and better: GDELT's DOC API accepts `startdatetime`/`enddatetime`, so a news
> *volume* series is available historically today.

The first clause is correct. `mode=timelinevolraw` with `startdatetime`/`enddatetime` returns one
bucket per day, each carrying a matched-article count and the total GDELT indexed that day. Verified
live: `q4-2018` (2018-09-21 → 2018-12-24) returns **95 daily buckets** spanning exactly the window.

The second clause — "available historically" — is where it breaks. **GDELT's DOC 2.0 archive begins
2017-01-01.** Anything earlier is refused with a plain-text body, `Invalid query start date.`

That boundary was established by bisection against the live endpoint on 2026-08-26, not read off
documentation:

| requested start | result |
|---|---|
| 2008-01-01 | `Invalid query start date.` |
| 2011-08-01 | `Invalid query start date.` |
| 2014-01-01 | `Invalid query start date.` |
| 2016-06-01 | `Invalid query start date.` |
| 2016-12-15 | `Invalid query start date.` |
| **2017-01-01** | **JSON** |

## What that does to the matrix

`WINDOWS.md` defines eight main windows. Five are inside GDELT's archive; three end entirely before
it and can never be answered by this upstream at all.

| tag | window | reachable |
|---|---|---|
| `gfc` | 2007-10-09 → 2009-03-09 | **no** |
| `chop-2011` | 2011-05-26 → 2012-06-06 | **no** |
| `chop-2015` | 2015-04-07 → 2016-04-15 | **no** |
| `q4-2018` | 2018-09-21 → 2018-12-24 | yes |
| `covid` | 2020-02-19 → 2020-06-30 | yes |
| `bear-2022` | 2022-01-03 → 2022-10-12 | yes |
| `bull-2024` | 2024-08-21 → 2025-08-20 | yes |
| `recent` | 2025-08-21 → 2026-08-18 | yes |

**The three that are gone are not a random three.** They are the deepest drawdown available and
*both* sideways windows — the ones `WINDOWS.md` calls "round 2's most important addition", added
precisely because round 1 held two bears and a crash and nothing that went nowhere.

Two numbers make the consequence concrete, both read from the code rather than estimated
(`app.tournament.jobs`, `app.evolution.models`):

- `MIN_ELIGIBLE_MAIN_WINDOWS = 5`. Five reachable windows means the study sits **exactly on the
  eligibility floor with zero slack** — one upstream hiccup on one window and it is ineligible.
- The default holdout is `("covid", "q4-2018")`. Holding those out the way every other study here
  does leaves **three** windows for selection, which is below the floor outright.

So D-news cannot be run under this programme's own rules while also holding out a test set. It can
be run on five windows with no holdout, or on three with one, and neither is what was
pre-registered.

## Why this is a result and not an obstacle

`PROTOCOL.md`'s anti-overfitting constitution exists to stop exactly the move that would rescue this
study: quietly running the five windows that work, reporting a q-value, and letting the reader
assume the matrix was the matrix. The surviving five are **all post-2017 and contain no crisis
deeper than COVID**. A "news volume predicts returns" finding measured only there is a finding about
one regime era wearing the clothes of a cross-regime result.

This is the same shape as D-social's blocker, and the plan already said the right thing about that
one: it is "the anti-p-hacking constitution working as designed", and the alternative "would have
looked completely normal in the output". The difference is only that D-social is blocked by time,
which passes, and D-news is blocked by an archive boundary, which does not.

Round verdicts here are conditional on the window mix — round 3 was 6-of-8 falling and round 4 was
2-of-6 rising, and identical cards reversed between them. A study that silently drops both sideways
windows has changed the mix before it starts.

## What was built anyway, and why

`GdeltProvider.fetch_volume_series(query, *, start, end)` (`app/market/providers/gdelt.py`), with
`NewsVolumePoint` and `NewsVolumeSeries` in `app/market/news_models.py`. Sixteen tests in
`tests/test_provider_gdelt.py`, driven from a live capture at
`tests/fixtures/news/gdelt_timeline_volraw.json`.

Building the fetcher is worth it under every branch below, and it is what makes the finding above
reproducible rather than a claim in prose. Three design points carry the finding into the code so a
later caller cannot lose it:

- **`COVERAGE_START` is a named constant with the bisection recorded next to it**, not an inline
  `2017`. The next person to widen a window meets the reason.
- **A request starting before coverage is clamped, and the result reports the gap** —
  `requested_start_before_coverage`, mirroring `social_history.read_range`'s guard. Refusing instead
  would push callers toward a `try/except` that swallows a window silently; putting the gap in the
  *result* means a study must either report it or actively discard it. A window entirely before
  coverage returns zero points without sending a request at all, which also keeps the caller off
  GDELT's 5-second-per-IP throttle for a question that has no answer.
- **Two counts, never their ratio.** `matched` and `indexed_total` are both kept, because GDELT's
  monitored corpus grows year over year and a raw count is not comparable across windows without its
  denominator. Same rule as `SocialSnapshot` carrying counts and no score.

## The branch, which is the owner's to pick

1. **Run D-news on the five reachable windows, no holdout, and label it what it is** — a post-2017
   result that says nothing about sideways markets or a deep crisis. Cheapest. Its honest conclusion
   can only ever be conditional.
2. **Run it on three selection windows with `covid`/`q4-2018` held out**, accepting that it is below
   `MIN_ELIGIBLE_MAIN_WINDOWS` and therefore cannot clear the gate as written. This preserves the
   holdout discipline and openly fails the eligibility rule instead of quietly failing the matrix.
3. **Find an upstream with real historical depth.** The boundary is GDELT's, not news's. This is the
   only branch that answers the question as asked, and it is the only one that costs real money —
   every archive reaching 2008 is commercial.
4. **Cancel D-news and, with it, Phases E and F.** The plan already reserves this: *"If the answer is
   no, Phase C still stands and Phases E and F are cancelled rather than built. That branch must stay
   genuinely on the table."* Note this is not the plan's "no" — that meant *measured and found
   absent*. This is *not measurable at the stated scope*, which is weaker evidence for cancelling.

**Recommendation: (1), reported strictly as conditional, and only if Phases E/F are wanted for other
reasons.** The honest prior stated in the plan is that sentiment as a signal is "weak and crowded".
Spending money on branch (3) to buy a better-powered test of a hypothesis nobody believes is the
wrong purchase; running branch (1) cheaply and letting a null result stand as a *conditional* null is
proportionate. What must not happen is branch (1) reported as though it were the matrix.

## Reproducing this

```bash
.venv/Scripts/python.exe -m pytest tests/test_provider_gdelt.py -q
```

The boundary itself is a live property and is deliberately **not** asserted against the network in
the suite — no test in `tests/test_provider_gdelt.py` makes a network call. To re-probe it, request
`startdatetime=20161215000000` and `20170101000000` from
`https://api.gdeltproject.org/api/v2/doc/doc` and compare the bodies, pacing requests at least 8
seconds apart. GDELT's throttle is stickier than its own message claims.
