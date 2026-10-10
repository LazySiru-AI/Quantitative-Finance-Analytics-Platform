# Retired

Cards kept on disk with a note recording what retired them. Retirement is not deletion — a card that
could not be tested is evidence about the matrix as much as about the card.

## `D-13f-newbuys`

**Retired after round 2.** `PROTOCOL.md` §6: zero trades in every window of two consecutive rounds.

It cleared **no window in either round**, including the `13f-legal` window built specifically for it.
Its `sma(200)` entry needs roughly 239 bars of prior history, and `SNDK` — first bar 2025-02-13 —
falls about ten weeks short even for a window starting 2025-11-17.

This is worth recording rather than dismissing. In the tournament that preceded this program, the
card it derives from produced **+56.93% against a +11.99% benchmark** on a window that was roughly
72% out-of-sample — the most genuinely blind result the project has ever produced. That result is now
unreproducible in the current matrix, not because it was refuted but because the card cannot be run.

Two things would make it testable again, and either is a legitimate round-3 experiment: a shorter
moving average, or the same rule on a universe without `SNDK`. Both change the card, so both would
enter as a new candidate rather than as this one.

---

# Retired after round 3 — the round-4 trim

The field had grown to 35 measured cards. `strategy-program/ROUND-4-PLAN.md` §3 trims it to nine
returning entries; this is the log of what left and why.

**Every figure below is median adjusted excess** — return minus `capital_exposure × benchmark`, the
metric that survives scrutiny (`DEFECTS.md` D2). Raw excess flatters a book that sat in cash through
a bear market, and three rounds running it has told a story that exposure correction dissolved.

**Nothing here is deleted.** A retired card keeps its file, its result history under `data/rounds/`,
and the reason it stopped competing. Several are explicitly invited back re-cut.

## The A family — five cards, retired together

`A-rotation`, `A1-alpha-order`, `A2-cash-headroom`, `A3-no-target`, `A4-tight-stop`

| card | median | worst | hit | mean exposure |
|---|---|---|---|---|
| `A-rotation` | −7.2% | −27.4% | 43% | 0.49 |
| `A1-alpha-order` | −4.8% | −30.0% | 43% | 0.49 |
| `A2-cash-headroom` | −9.2% | −22.8% | 43% | 0.47 |
| `A3-no-target` | −2.9% | −27.4% | 43% | 0.47 |
| `A4-tight-stop` | −7.3% | −27.8% | 43% | 0.49 |

Every one negative, every one with the field's **highest capital exposure**, and every one with a
worse-than-coin-flip hit rate. That combination is the precise failure this programme was built to
detect: they read acceptably on raw return because they were heavily invested through a rising
market, and they lose once that exposure is paid for.

### Amended 2026-08-22 after round 4 — the sentence above was regime-conditional

The paragraph above states a structural claim. Round 4 re-ran all five cards, unchanged, on its six
windows as a control arm, and falsified it as written. See `data/rounds/r4-2026-08/REPORT.md` §7.

| card | median | worst | hit | mean exposure | rank in the round-4 field |
|---|---|---|---|---|---|
| `A-rotation` | **+4.20%** | **+0.20%** | **100%** | 0.77 | **2nd of 19** |
| `A4-tight-stop` | +4.20% | +0.20% | 100% | 0.76 | 3rd |
| `A3-no-target` | +3.02% | −0.74% | 80% | 0.77 | 6th |
| `A2-cash-headroom` | +2.58% | −0.97% | 80% | 0.72 | 8th |
| `A1-alpha-order` | +0.40% | −6.50% | 60% | 0.76 | 12th |

(Five windows: `recovery-2009` is structurally ineligible for all five, `AVGO`'s first bar being
2009-08-06.)

The reason is the matrix, not the cards. Round 3's eight windows carried a **mean benchmark return of
−9.45%**, six of eight falling; round 4's six carry **+17.13%**, two of six falling. A heavily-invested
book loses the first and wins the second mechanically. `A-rotation` and `A4-tight-stop` finish ahead
of `B-momentum` here on the Borda composite.

What survives of the retirement, and what does not:

- **Survives.** These are still the most heavily invested books ever measured in this programme, at
  more than twice any card kept, and the scorer flags all five `incommensurable_exposure = yes` —
  their numbers are not like-for-like against the rest of the field in either direction. They really
  did lose badly on a bear-weighted matrix. And `A1`, `A2` and `A3` remain dominated by their own
  base on both matrices, so the variants' retirement stands on its own numbers.
- **Does not survive.** *"They lose once that exposure is paid for"*, stated without a condition. It
  should have read *"…on a matrix where six of eight benchmarks fall."* The exposure correction was
  applied here too, and after it they are positive.

`A-rotation` therefore stays on disk as an available **high-exposure comparator** rather than as a
card judged unfit. It is not recommended, it has been measured on two matrices and nothing else, and
any round that fields it should say which of the two its own windows resemble.

### Un-retired 2026-08-22 by round 6

`A-rotation` was moved back to `library/candidates/` and seated on the paper desk by round 6's
selection rule -- it was first at both the 6-month and 1-year rungs of round 5's horizon ladder and
cleared both selection gates. See `data/rounds/r6-2026-08/SELECTION.md`.

Read that alongside the same document's section 6: over the 55 live sessions from 2026-06-01,
`A-rotation` is **last of ten at -12.77%**, holding NVDA, AVGO and TSM at 99% of its book. The card
with the best short-horizon backtest in the programme has the worst out-of-sample result in it. The
four variants (`A1`, `A2`, `A3`, `A4`) stay retired.

`A-rotation` was a **base strategy** until 2026-08-21, promoted on a prior tournament's +145% three-
year figure. Round 2 measured it properly and it has not recovered. Its own margin then sat inside
the 53.9-point universe-ordering spread that `PROTOCOL.md` §7 documents, so the number that promoted
it was never distinguishable from noise.

The four variants go with it for a structural reason rather than on their own numbers: a variant
exists to attribute **one decision** against its base. With the base demoted and negative, there is
no baseline left to attribute to. Any of these questions can be re-asked against `B-momentum`.

## Negative after exposure correction, across every round run

- **`c02-volatility`** — −1.3%, hit **12%**: positive in one window out of eight.
- **`c03-breakout`** — −3.1%, hit 25%.
- **`c04-riskmanaged`** — −1.5%, hit 25%, exposure 0.45. The name promises risk management the
  numbers do not show; it is neither defensive nor profitable.
- **`c08-generalist`** — −0.6% at exposure **0.59**, the highest in the field. A book that invested
  the most and still finished behind the benchmark it was measured against.
- **`c15-volatility-wide`** — −1.2%, worst −20.8%, and the only card here retired partly on a
  **falsified thesis**. Its memo pre-registered `gfc` as its worst window, reasoning that 2008's
  financials had genuinely impaired balance sheets. `gfc` came back its *best*. Round 3 showed why:
  Lehman, Bear Stearns, Washington Mutual and Countrywide are absent from a present-day index, so the
  card could only buy the banks that survived. The analyst was right about the world and the backtest
  was wrong — the single clearest survivorship demonstration in the project, and worth keeping for
  that even as the card leaves.
- **`c17-defensive-trend-wide`** — −0.6%, hit 38%. Answered a good question (does the trend mechanism
  travel outside the AI complex?) in the negative: it kept `C-trend`'s exact entry rule and lost
  9.0 points of median to it.

## Not a strategy — a spectator

**`c12-meanrev-wide`** — −0.1%, **17 trades across eight windows**, mean exposure **0.02**.

A book 2% invested is not being tested. Its +55.3% raw `gfc` excess on a *single trade* is the
clearest illustration in the project of why raw excess is the wrong headline: it did not beat the
crisis, it declined to attend.

## Dominated within its own family

**`B1-with-target`** — +4.6%, hit 50%. Beaten by `B2-hold-90`, `B3-concentrated` and `B4-tight-stop`
on median *and* hit rate. It tested a take-profit against `B-momentum`, whose own memo had already
argued against one with pre-registered evidence — capping gains cut mean per-signal return from
roughly 20% to 2–9%. The question is answered twice over.

## Near-zero and dominated

`c01-meanrev` (+0.4%), `c05-trend` (+0.2%), `c10-momentum` (+0.4%), `c16-dispersion-wide` (+0.3%).

None is broken. Each is beaten on all three axes by a card kept in the same discipline, and a field
slot is a real cost — every card multiplies the Benjamini-Hochberg denominator that every other
card's significance is judged against.

`c16-dispersion-wide` is the one that stings. It was round 3's deliberate breadth experiment: one
name per sector, mean pairwise correlation 0.245 against the incumbents' 0.49–0.52, with an ordering
argument built from measured correlation rather than an arbitrary tiebreak. It finished 7th of 10.
**Its finding is kept even though the card is not** — diversifying *inside* a card did not work,
while pairing uncorrelated *strategies* did. That result is what `ROUND-4-PLAN.md` §1 is built on.

## Structurally unrankable — invited back re-cut

- **`E-asymmetric`** — eligible in **1** window of eight.
- **`F-fastrev`** — 2 windows.
- **`G-volatility`** — 3 windows, and **+12.6% median** across them.

All below the 5-of-8 gate, and a card's universe is fixed, so re-running changes nothing. `G-volatility`
is the loss here: a genuinely promising number that cannot be ranked. It was designed when 86 stored
symbols reached 2004; **380 do now**. A re-cut with a long-history universe would be a welcome round-4
submission, and it would be a *new* card with its own two-round clock, not this one's record resumed.

## Provenance-constrained

**`c06-13f-momentum`** is legal only in the `13f-legal` window, so it can never clear a gate defined
over the eight regime windows. It remains the standing worked example for the provenance rule: round
1 ranked it on four windows that predated the 13F filings its universe came from, and a human reader
caught it, which is not a control. `WINDOWS.md` now enforces it in code.
