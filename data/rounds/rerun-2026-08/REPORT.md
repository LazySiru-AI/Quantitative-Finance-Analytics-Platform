# Re-running rounds 1–14 on today's engine

**Not investment advice.** Simulated books on a paper account. I am not a licensed financial adviser
and none of this is a recommendation about real capital.

Run 2026-08-24 by `strategy-program/tools/rerun_matrix.py`.

---

## What this is not

This directory is **not** rounds 1–14's results. Those trees are untouched.

`PROTOCOL.md` §6(a) forbids treating a re-run as new evidence, and the reason is structural: Gate A
reads round 5, Gate S′ reads rounds 2, 4 and 5, rounds 6–12 are selection rounds scored over those
frozen matrices, and two of them ended in owner overrides argued from specific figures in them.
Re-scoring the matrices underneath would retroactively invalidate seven rounds of reasoning and both
overrides at once.

## The question it does answer

> How much of the programme's recorded history is a property of the engine rather than of the
> strategies?

A card is frozen. The machine that scores it is not — D1's rebasing correction, D2's
`capital_exposure` split from session-presence `exposure`, D4's full-history lookback,
`_undilute_exposure`, and round 14's `rank_by` all landed after most of these rounds ran.

## Method

930 distinct `(card, window)` cells across rounds 1–14, covering 1,051 stored run files. A pair is
deterministic, so each was run once and compared against every stored copy. Each cell reused **its
own original `starting_equity`**, read from the stored result rather than today's `PURPOSE_SPECS` —
the trading seed moved from $50,000 to $100,000 on 2026-08-24, and running an old cell at the new
seed would have folded a capital change into a measurement of engine drift.

Serial, 2.5s/cell, 920 cells in ~38 minutes. Zero failures.

## Headline

    compared 1051 stored copies
      identical to 1e-9 : 989/1051 (94.1%)
      median |drift|    :  0.0000 pp
      worst  |drift|    : 74.6369 pp

**Every one of the 62 non-identical comparisons is explained, and none of them is engine drift.**

## The 60: this tool reproduced a defect the programme already retired

All 60 sit in `live-2` through `live-6` and all come from round 11.

Those are six contiguous one-month out-of-sample windows. Round 11 originally scored them the way
every other matrix is scored — as independent runs — and then found that doing so **resets the book
at every boundary**, so a card entering `live-4` already holding positions from `live-3` is instead
started from cash. That is `DEFECTS.md` **D5**, and its own entry is blunt about the consequence:
"a table of numbers that looks complete and measures something other than what it says."

Round 11 replaced the instrument and kept the invalid output as evidence at
`data/rounds/r11-2026-08/results-independent-INVALID/`.

`rerun_matrix.py` runs each window independently from cash. So it rebuilt the retired instrument.

**Proof, rather than inference:** every one of the 90 cells in the retired `-INVALID` tree matches
this re-run *exactly*.

    INVALID-tree cells compared : 90
      identical to my re-run    : 90
      different                 : 0

So the largest apparent "drift" in this whole exercise — `B3-concentrated` on `live-4` going from
+74.64% to 0.00% — is not the engine disagreeing with itself. It is a card that carried a winning
position into a window, measured by an instrument that hands it cash at the door instead. The 0.00%
figures are cells where no entry signal fired inside a single month, so nothing was ever bought.

This is worth recording rather than quietly fixing: a generic re-runner will reproduce D5 by
default, because running windows independently is the obvious implementation and is wrong for any
period that was originally scored as one continuous book.

## The 2: a bar revision, not the engine

| card | window | source | stored → re-run | drift |
|---|---|---|---|---|
| `C-wide` | recent | r3 | 5.64% → 5.92% | +0.29 pp |
| `B-wide` | recent | r3 | 12.77% → 13.00% | +0.24 pp |

Both ran 249 sessions before and after, so this is not a window-length change.

The first hypothesis was slot contention — round 14 measured a 53.9-point spread over twelve
orderings of one card, and `-wide` cards have the most headroom. **That was falsified by the data:**
`c16-dispersion-wide` has the highest headroom in the round (8) and reproduced exactly, and
`B-momentum` shares `B-wide`'s universe size and headroom and also reproduced exactly.

| card | universe | slots | headroom | verdict |
|---|---|---|---|---|
| `c16-dispersion-wide` | 12 | 4 | 8 | same |
| `B-momentum` | 12 | 6 | 6 | same |
| `B-wide` | 12 | 6 | 6 | **moved** |
| `C-trend` | 9 | 5 | 4 | same |
| `C-wide` | 9 | 5 | 4 | **moved** |

What actually separates them is the symbol list. **`AAPL` and `MSTR` are the only two symbols held
by the moved cards and by none of the eight that reproduced.** And `AAPL`'s bar file carries
`fetched_at: 2026-08-22T22:00:57Z`, one day *after* round 3's run files were written on 2026-08-21.

Stated at the strength the evidence supports: this is **consistent with** a bar revision in `AAPL`
between round 3's run and today, and is not consistent with an engine change, which would not
confine itself to the two cards holding one symbol. It is not *proven*, because the pre-revision
bars no longer exist to diff against.

## Conclusion

**Engine drift across rounds 1–14 is zero on every cell measured the same way it was measured
originally.** 989 of 1,051 stored figures reproduce bit-for-bit; the 60 that do not are this tool
reproducing a retired instrument, and the remaining 2 are the only two cards holding a symbol whose
bars were re-fetched after the round ran.

The record is robust. Nobody had checked, and the check was worth running — but the reason it took
three hypotheses to explain 62 cells is that the first two were wrong, and both were wrong in the
direction of blaming the engine.
