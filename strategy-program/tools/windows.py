"""The round-2 window matrix, and whether a given card is legally allowed to run in each window.

See `strategy-program/WINDOWS.md` for the regime rationale -- this module only implements the
mechanism that document describes: a card may run in a window only when every symbol in its
universe has enough history *before* the window starts to (a) let its indicators finish warming up
and (b) hand the lookahead guard the 40 post-warmup bars it needs to demonstrate causality
(`app.backtest.guards._MIN_BARS_FOR_CAUSALITY`). A card that fails that is not merely disadvantaged
in a window, it is disqualified from it -- run there anyway and every early trade is decided on an
indicator that has not settled.

**That is a question about symbols, and it is not the only eligibility question there is.** A card
whose universe was itself *derived* from a point-in-time source -- a 13F filing, above all -- cannot
legally trade a window that starts before that source existed, no matter how much price history its
symbols happen to have. Round 1 ranked a 13F-derived card on four windows that all began before the
2025-11-14 filing date its universe came from; every symbol had decades of price history, so the
symbol-level check above passed cleanly, and nothing else asked the different question of whether
the *basket* was knowable yet. That was caught by a human reader of the round-1 report, not by this
module. `eligible_windows`'s optional `universe_knowable_from` parameter is the fix: a window
starting before that date is ineligible regardless of what the price-history check concludes. See
`resolve_universe_knowable_from` for where that date comes from.

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/windows.py \\
        --cards backend/app/paper/library/base --cards backend/app/paper/library/variants \\
        --cards backend/app/paper/library/candidates

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name (the
hyphen), so it can only be invoked by file path, with `backend` and the repo root already on
``PYTHONPATH`` for the `app.*` imports this module makes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from app.backtest.guards import _MIN_BARS_FOR_CAUSALITY
from app.config import Settings, get_settings
from app.db import duck
from app.indicators import registry as indicator_registry
from app.rules import grammar
from app.tournament.models import StrategyCard

if TYPE_CHECKING:
    import duckdb

    from app.rules.nodes import IndicatorRef

__all__ = [
    "ALL_WINDOWS",
    "MAIN_WINDOWS",
    "MIN_ELIGIBLE_MAIN_WINDOWS",
    "MIN_ELIGIBLE_R4_WINDOWS",
    "MIN_ELIGIBLE_R5_PER_HORIZON",
    "PROVENANCE_REASON_PREFIX",
    "PROVENANCE_SIDECAR_FILENAME",
    "R2_MAIN_WINDOWS",
    "R4_MAIN_WINDOWS",
    "R5_BEAR_WINDOWS",
    "R5_HORIZON",
    "R5_LADDER_WINDOWS",
    "WINDOWS",
    "eligible_windows",
    "load_provenance_sidecar",
    "max_indicator_period",
    "resolve_universe_knowable_from",
    "symbol_first_bar",
]

#: The canonical window matrix, in the order `strategy-program/WINDOWS.md` presents it -- deliberately
#: cheapest-first, so a run cut short still yields the widest regime coverage available for the
#: sessions it managed -- plus the 13F special case appended last. Each entry is
#: ``(start, end, regime)``. Dict order is significant here (Python 3.7+ dicts are ordered): it is the
#: display order for every table this module prints, and it is the order
#: `strategy-program/WINDOWS.md` itself uses, so a reader can follow the two side by side.
#:
#: Round 1's five-window matrix held two bears, a crash and two bulls, and no directionless regime at
#: all -- several analysts pre-registered whipsaw as the regime they feared most, and not one of them
#: could be tested on it, which means those predictions went unscored rather than merely unconfirmed.
#: `chop-2015` and `chop-2011` close that hole: both were found by scanning 30 years of SPY for
#: windows that go nowhere while moving constantly (`chop-2015` returns -0.04% across 260 sessions at
#: 16.6% annualised volatility; `chop-2011` returns -0.05% at 22.9%), every figure verified directly
#: against SPY. They are deliberately **not** the cheaper, more obvious choices -- 2015-05 to 2016-02
#: (-14.0%) and 2011-04 to 2011-12 (-7.8%) -- because both of those are corrections relabelled as
#: chop, which is exactly the wrong regime to add when the matrix is already short two bears.
#:
#: ``"13f-legal"`` is **not** one of the eight ranked round-2 regimes -- see its own entry below. It
#: lives in this dict because callers that want "every window this module knows about, whichever
#: list" (the `--cards` matrix in `main`, for instance) should not have to remember to merge two
#: mappings; the ones who specifically want just the ranked regimes use `MAIN_WINDOWS` instead.
WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    "q4-2018": (dt.date(2018, 9, 21), dt.date(2018, 12, 24), "sharp quarter-long selloff"),
    "covid": (dt.date(2020, 2, 19), dt.date(2020, 6, 30), "COVID crash and snapback"),
    "bear-2022": (dt.date(2022, 1, 3), dt.date(2022, 10, 12), "rate-driven bear"),
    "chop-2015": (dt.date(2015, 4, 7), dt.date(2016, 4, 15), "sideways"),
    "chop-2011": (dt.date(2011, 5, 26), dt.date(2012, 6, 6), "sideways, higher volatility"),
    "bull-2024": (dt.date(2024, 8, 21), dt.date(2025, 8, 20), "bull"),
    "recent": (dt.date(2025, 8, 21), dt.date(2026, 8, 18), "recent bull"),
    "gfc": (dt.date(2007, 10, 9), dt.date(2009, 3, 9), "GFC bear"),
    # Round 4's six-window matrix. Every one of these is new relative to rounds 1-3 -- none of them
    # appears in the round-2/3 matrix above -- by design: `strategy-program/PROTOCOL.md` section 6(a)
    # notes that a card is frozen and the engine deterministic, so re-running a card on a window it has
    # already run recomputes the same number rather than sampling anything new. Round 4 exists to
    # confirm `B2-hold-90` and `c14-riskmanaged-wide` on windows they have never seen, so bringing back
    # any round-2/3 window here would silently turn a confirmation round into the same measurement
    # counted twice.
    "oil-2014": (dt.date(2014, 6, 20), dt.date(2015, 2, 11), "oil collapse and dollar surge"),
    "volmageddon-2018": (dt.date(2018, 1, 26), dt.date(2018, 4, 2), "volatility shock"),
    "taper-2013": (dt.date(2013, 5, 22), dt.date(2013, 9, 5), "rate shock, taper tantrum"),
    "recovery-2009": (dt.date(2009, 3, 10), dt.date(2010, 4, 23), "post-crisis recovery rally"),
    "inflation-2021": (dt.date(2021, 1, 4), dt.date(2021, 12, 31), "inflation onset and rotation"),
    "banks-2023": (dt.date(2023, 3, 1), dt.date(2023, 5, 31), "regional banking crisis"),
    # Not part of either round's main matrix. Exists only for cards whose universe was assembled from a
    # 13F filing -- a universe that cannot possibly reach back to the GFC or COVID by construction,
    # since the filing itself postdates them. Excluded from `R2_MAIN_WINDOWS`/`R4_MAIN_WINDOWS` (and
    # therefore from the gates in `eligible_windows`/`MIN_ELIGIBLE_MAIN_WINDOWS`/
    # `MIN_ELIGIBLE_R4_WINDOWS`) so a 13F card is never scored as if this special-case window were one
    # of its real regime draws.
    "13f-legal": (dt.date(2025, 11, 17), dt.date(2026, 8, 18), "13F-legal window"),
    # Round 22's three curve windows. Selected on the *treatment* -- periods in which `T10Y2Y`
    # actually crosses zero -- rather than on equity regime, which is what every window above was
    # chosen on and why round 21's macro gate blocked 81 of 1,716 sessions and measured nothing.
    # See `strategy-program/ROUND-22-PLAN.md` §1a for why selecting on the treatment is not the
    # selection-on-outcome failure round 4 documents, and §2 for the fourth candidate that was
    # discarded. `inv-2000` opens 1999-12-02 rather than at the inversion because the nine sector
    # SPDRs begin 1998-12-21 and `sma(200)` needs 199 bars of warmup plus the guard's 40-bar
    # minimum -- see that document's Amendment 1.
    "inv-2000": (dt.date(1999, 12, 2), dt.date(2001, 6, 29), "curve inverted, equities falling"),
    "inv-2006": (dt.date(2006, 3, 1), dt.date(2007, 12, 31), "curve inverted, equities rising"),
    "inv-2022": (dt.date(2022, 1, 3), dt.date(2024, 12, 31), "curve inverted through a strong bull"),    # Round 5's 27-window matrix, transcribed verbatim from `data/rounds/r5-2026-08/windows.json` --
    # the committed source of truth. Do not recompute or adjust a single date here; if that file ever
    # changes, re-transcribe from it, and let `tests/test_competition_jobs.py` /
    # `tests/test_competition_api.py` catch the drift rather than trusting eyes a second time.
    #
    # Unlike every matrix above, round 5 is not a set of named historical regimes -- it is a *horizon
    # ladder*: the same handful of anchor dates (2013-09, 2014-02, 2016-02, 2018-02/08, 2020-02/08,
    # 2021-02, 2022-02/08, 2023-02, 2025-02/08) sliced to 6-month, 1-year, 3-year, 5-year and 10-year
    # lengths, so a card's edge can be read as a function of run length rather than of which crisis it
    # landed in. The 21 entries below are that ladder (`"ladder"` in the source JSON, mirrored here as
    # `R5_LADDER_WINDOWS`); `R5_HORIZON` records each one's designed length (`"6m"|"1y"|"3y"|"5y"|
    # "10y"`), which is metadata this module's plain `(start, end, label)` tuple has no field for.
    #
    # The six `"bear"`-arm entries after them (`R5_BEAR_WINDOWS`) exist because the ladder's anchor
    # dates were chosen to build a clean nested/overlapping structure, not to hunt for drawdowns -- at
    # the 6m/1y horizons that leaves the ladder's own coverage of "how does this card do when SPY is
    # actually down" thin (only `h1y-5`, 2022, has a negative `spy_return` among the eighteen 6m/1y
    # ladder windows). Every `bear` window's `spy_return` in the source JSON is negative by
    # construction; they supplement the ladder rather than replace any of it, and are kept in their own
    # dict/matrix (`"r5-bear"` in `app.api.competition`, not folded into `"r5-ladder"`) so a caller
    # asking for "the ladder, horizon by horizon" does not silently absorb the bear arm's downward bias.
    "h10y-1": (dt.date(2013, 9, 3), dt.date(2023, 8, 31), "decade, early endpoint"),
    "h10y-2": (dt.date(2016, 2, 16), dt.date(2026, 2, 13), "decade, recent endpoint"),
    "h5y-1": (dt.date(2013, 9, 3), dt.date(2018, 8, 31), "half-decade, early"),
    "h5y-2": (dt.date(2016, 2, 16), dt.date(2021, 2, 12), "half-decade, middle"),
    "h5y-3": (dt.date(2021, 2, 16), dt.date(2026, 2, 13), "half-decade, recent"),
    "h3y-1": (dt.date(2014, 2, 18), dt.date(2017, 2, 15), "three years, 2014-17"),
    "h3y-2": (dt.date(2017, 2, 16), dt.date(2020, 2, 14), "three years, 2017-20"),
    "h3y-3": (dt.date(2020, 2, 18), dt.date(2023, 2, 15), "three years, 2020-23"),
    "h3y-4": (dt.date(2023, 2, 16), dt.date(2026, 2, 13), "three years, 2023-26"),
    "h1y-1": (dt.date(2014, 2, 18), dt.date(2015, 2, 17), "one year, 2014"),
    "h1y-2": (dt.date(2016, 2, 16), dt.date(2017, 2, 15), "one year, 2016"),
    "h1y-3": (dt.date(2018, 2, 16), dt.date(2019, 2, 15), "one year, 2018"),
    "h1y-4": (dt.date(2020, 2, 18), dt.date(2021, 2, 17), "one year, 2020"),
    "h1y-5": (dt.date(2022, 2, 16), dt.date(2023, 2, 15), "one year, 2022"),
    "h1y-6": (dt.date(2025, 2, 18), dt.date(2026, 2, 13), "one year, 2025"),
    "h6m-1": (dt.date(2014, 8, 18), dt.date(2015, 2, 17), "six months, H2 2014"),
    "h6m-2": (dt.date(2016, 8, 16), dt.date(2017, 2, 15), "six months, H2 2016"),
    "h6m-3": (dt.date(2018, 8, 16), dt.date(2019, 2, 15), "six months, H2 2018"),
    "h6m-4": (dt.date(2020, 8, 18), dt.date(2021, 2, 17), "six months, H2 2020"),
    "h6m-5": (dt.date(2022, 8, 16), dt.date(2023, 2, 15), "six months, H2 2022"),
    "h6m-6": (dt.date(2025, 8, 18), dt.date(2026, 2, 13), "six months, H2 2025"),
    "b6m-1": (dt.date(2019, 9, 20), dt.date(2020, 3, 23), "six months into the covid low"),
    "b6m-2": (dt.date(2021, 12, 15), dt.date(2022, 6, 16), "six months into the 2022 bear"),
    "b6m-3": (dt.date(2018, 6, 25), dt.date(2018, 12, 24), "six months into the Q4-2018 low"),
    "b1y-1": (dt.date(2021, 12, 28), dt.date(2022, 12, 28), "the 2022 bear year"),
    "b1y-2": (dt.date(2019, 3, 22), dt.date(2020, 3, 23), "one year into the covid low"),
    "b1y-3": (dt.date(2015, 2, 11), dt.date(2016, 2, 11), "the 2015-16 growth scare"),
    # Round 11's live matrix: the out-of-sample period 2026-02-17 to 2026-08-18, cut into six
    # contiguous sub-periods on SPY's own session calendar (`strategy-program/ROUND-11-PLAN.md`
    # section 2). **Unlike every other entry above, these are not regime windows** -- they are one
    # market environment cut into pieces, and the only period no card could have been designed
    # against (every card is frozen with designed_through = 2026-02-13). The dates below are each
    # sub-period's own span; the runs that produce them are *cumulative* from 2026-02-17 and then
    # differenced, because six independent runs reset each card's book at every boundary
    # (`strategy-program/DEFECTS.md` D5).
    "live-1": (dt.date(2026, 2, 17), dt.date(2026, 3, 18), "live out-of-sample, weeks 1-4"),
    "live-2": (dt.date(2026, 3, 19), dt.date(2026, 4, 17), "live out-of-sample, weeks 5-8"),
    "live-3": (dt.date(2026, 4, 20), dt.date(2026, 5, 18), "live out-of-sample, weeks 9-12"),
    "live-4": (dt.date(2026, 5, 19), dt.date(2026, 6, 17), "live out-of-sample, weeks 13-16"),
    "live-5": (dt.date(2026, 6, 18), dt.date(2026, 7, 20), "live out-of-sample, weeks 17-20"),
    "live-6": (dt.date(2026, 7, 21), dt.date(2026, 8, 18), "live out-of-sample, weeks 21-25"),
}

#: Tags of round 5's 21 ladder windows, in `WINDOWS`' display order -- see the comment above their
#: entries in `WINDOWS` for what the ladder is and why it is not another set of named regimes.
R5_LADDER_WINDOW_TAGS: tuple[str, ...] = (
    "h10y-1",
    "h10y-2",
    "h5y-1",
    "h5y-2",
    "h5y-3",
    "h3y-1",
    "h3y-2",
    "h3y-3",
    "h3y-4",
    "h1y-1",
    "h1y-2",
    "h1y-3",
    "h1y-4",
    "h1y-5",
    "h1y-6",
    "h6m-1",
    "h6m-2",
    "h6m-3",
    "h6m-4",
    "h6m-5",
    "h6m-6",
)

#: The 21-window horizon ladder only. Derived from `WINDOWS` via `R5_LADDER_WINDOW_TAGS` rather than
#: listed a second time so the two cannot drift apart, the same reasoning `R4_MAIN_WINDOWS` uses.
R5_LADDER_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    tag: WINDOWS[tag] for tag in R5_LADDER_WINDOW_TAGS
}

#: Tags of round 5's six bear-supplement windows, in `WINDOWS`' display order -- see the comment above
#: their entries in `WINDOWS` for why these exist alongside, not inside, the ladder.
R5_BEAR_WINDOW_TAGS: tuple[str, ...] = (
    "b6m-1",
    "b6m-2",
    "b6m-3",
    "b1y-1",
    "b1y-2",
    "b1y-3",
)

#: The six bear-supplement windows only. Derived from `WINDOWS` via `R5_BEAR_WINDOW_TAGS` for the same
#: anti-drift reason as `R5_LADDER_WINDOWS`.
R5_BEAR_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    tag: WINDOWS[tag] for tag in R5_BEAR_WINDOW_TAGS
}

#: Tags of round 11's six live sub-periods, in `WINDOWS`' display order. Kept as its own named matrix
#: rather than folded into any round-5 arm because it answers a different question: those arms sample
#: deliberately different market regimes, these six are one regime cut into pieces to get a hit rate
#: out of the single period no card could have been fitted to.
R11_LIVE_WINDOW_TAGS: tuple[str, ...] = (
    "live-1",
    "live-2",
    "live-3",
    "live-4",
    "live-5",
    "live-6",
)

#: The six live sub-periods only. Derived from `WINDOWS` via `R11_LIVE_WINDOW_TAGS` for the same
#: anti-drift reason as `R5_LADDER_WINDOWS` and `R5_BEAR_WINDOWS`.
R11_LIVE_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    tag: WINDOWS[tag] for tag in R11_LIVE_WINDOW_TAGS
}
#: Round 22's three curve windows -- the ones in which `T10Y2Y` actually crosses zero.
#:
#: A named matrix of its own rather than folded into `MAIN_WINDOWS`, because it is selected on a
#: different axis: every window in `MAIN_WINDOWS` was chosen on an *equity* regime, and round 21
#: measured what that costs a rates-based test -- its gate blocked 81 of 1,716 sessions and 24 of 32
#: (form, window) pairs came back byte-identical. These three are chosen on the *treatment*.
#:
#: **Not a ranked matrix.** Three windows is below `MIN_ELIGIBLE_MAIN_WINDOWS`, deliberately: the
#: alternative was slicing the 782-day 2022-24 inversion into three to reach five, which would
#: manufacture independence out of one regime. Round 22 reports each window on its own and computes
#: no median across them. See `strategy-program/ROUND-22-PLAN.md` sections 1a and 2.
R22_CURVE_WINDOW_TAGS: tuple[str, ...] = ("inv-2000", "inv-2006", "inv-2022")

R22_CURVE_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    tag: WINDOWS[tag] for tag in R22_CURVE_WINDOW_TAGS
}


#: Each round-5 window's designed horizon -- `"6m"`, `"1y"`, `"3y"`, `"5y"` or `"10y"` -- transcribed
#: from `data/rounds/r5-2026-08/windows.json`'s own `"horizon"` field. This is not derivable from a
#: window's `(start, end)` pair without re-parsing the tag (`h3y-2`'s actual span is 754 sessions,
#: not a clean "3 years" in calendar terms -- session counts and calendar spans wobble around holidays
#: and leap years the same way `sessions` does in the source JSON), so it is carried as its own
#: mapping rather than computed. Every key here is also a key in `R5_LADDER_WINDOWS` or
#: `R5_BEAR_WINDOWS`, and every key in either of those dicts appears here -- both duplicated matrices
#: describe the same 27 windows, just grouped differently.
R5_HORIZON: dict[str, str] = {
    "h10y-1": "10y",
    "h10y-2": "10y",
    "h5y-1": "5y",
    "h5y-2": "5y",
    "h5y-3": "5y",
    "h3y-1": "3y",
    "h3y-2": "3y",
    "h3y-3": "3y",
    "h3y-4": "3y",
    "h1y-1": "1y",
    "h1y-2": "1y",
    "h1y-3": "1y",
    "h1y-4": "1y",
    "h1y-5": "1y",
    "h1y-6": "1y",
    "h6m-1": "6m",
    "h6m-2": "6m",
    "h6m-3": "6m",
    "h6m-4": "6m",
    "h6m-5": "6m",
    "h6m-6": "6m",
    "b6m-1": "6m",
    "b6m-2": "6m",
    "b6m-3": "6m",
    "b1y-1": "1y",
    "b1y-2": "1y",
    "b1y-3": "1y",
}

#: Round 5's eligibility gate, applied *per horizon* rather than once over the whole 27-window matrix
#: the way `MIN_ELIGIBLE_MAIN_WINDOWS`/`MIN_ELIGIBLE_R4_WINDOWS` apply over rounds 2-4's flat
#: matrices. A single flat gate does not mean anything here: round 5's question is "how does this
#: card's edge move across horizons", and a card that ran cleanly across all six 10y-or-longer-style
#: slots but never cleared warmup for a single 6m window would still pass a flat "N of 27" gate while
#: having nothing to say about the short end of the ladder at all -- the aggregate for that horizon
#: would rest on zero measurements dressed up as a real result. Gating per horizon instead means each
#: horizon's own aggregate (median return, hit rate, whatever `score.py` computes for it) is backed by
#: at least this many independent draws before it is reported as meaningful.
#:
#: 2 is the floor, not a round number picked for its own sake: `h10y` has only two windows total
#: (`h10y-1`, `h10y-2`), so any gate above 2 would make the 10-year horizon permanently ungatable --
#: no card could ever clear it, which would silently turn "the 10y aggregate needs more data" into
#: "no card is ever eligible for 10y", a very different and much worse claim. 2 is therefore the
#: largest value that still leaves every horizon, including the thinnest one, reachable at all.
MIN_ELIGIBLE_R5_PER_HORIZON = 2

#: Tags of the eight round-2/3 ranked regimes, in `WINDOWS`' display order. Listed explicitly (not
#: derived by excluding `"13f-legal"` from `WINDOWS`) because that exclusion trick stopped being
#: equivalent to "the round-2/3 matrix" the moment `R4_MAIN_WINDOWS`' six tags were added to `WINDOWS`
#: alongside it -- excluding only `13f-legal` would now also pull in every round-4 window. An explicit
#: tag list can't silently pick up a window from a later round the way that derivation could.
R2_MAIN_WINDOW_TAGS: tuple[str, ...] = (
    "q4-2018",
    "covid",
    "bear-2022",
    "chop-2015",
    "chop-2011",
    "bull-2024",
    "recent",
    "gfc",
)

#: The eight round-2/3 ranked regimes only -- what `eligible_windows`' round-2/3 gate counts against
#: `MIN_ELIGIBLE_MAIN_WINDOWS`. Derived from `WINDOWS` via `R2_MAIN_WINDOW_TAGS` rather than listed a
#: second time so the two cannot drift apart. This is the historical name and the historical eight
#: windows -- round 2 and round 3's published results were scored against this exact set, so its
#: meaning does not change now that round 4 exists; `R4_MAIN_WINDOWS` is the new, separate set for
#: round 4's gate.
MAIN_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    tag: WINDOWS[tag] for tag in R2_MAIN_WINDOW_TAGS
}

#: `MAIN_WINDOWS` under its round-scoped name -- the same eight-window dict, exposed alongside
#: `R4_MAIN_WINDOWS` so a reader asking "which round does this window matrix belong to" finds a
#: symmetric pair of names instead of one round-scoped name and one legacy one.
R2_MAIN_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = MAIN_WINDOWS

#: Tags of the six round-4 regimes, in `WINDOWS`' display order. See the comment above their entries
#: in `WINDOWS` for why every one of them is new relative to rounds 1-3.
R4_MAIN_WINDOW_TAGS: tuple[str, ...] = (
    "oil-2014",
    "volmageddon-2018",
    "taper-2013",
    "recovery-2009",
    "inflation-2021",
    "banks-2023",
)

#: The six round-4 regimes only -- what `eligible_windows`' round-4 gate counts against
#: `MIN_ELIGIBLE_R4_WINDOWS`. Derived from `WINDOWS` via `R4_MAIN_WINDOW_TAGS` rather than listed a
#: second time so the two cannot drift apart.
R4_MAIN_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    tag: WINDOWS[tag] for tag in R4_MAIN_WINDOW_TAGS
}

#: Every window `eligible_windows` can be asked about, every round and the special-case alike. Provided
#: as an explicit name distinct from `WINDOWS` for callers who want to say "all of them" at the call
#: site without relying on a reader already knowing `WINDOWS` happens to include the 13F case.
ALL_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = dict(WINDOWS)

#: The round-2 gate (`strategy-program/WINDOWS.md`; round-1's was 3 of 5 in
#: `rounds/r1-2026-08/BRIEF.md` section 3). Same 60% proportion, binding harder against the larger
#: eight-window matrix: a card eligible in fewer than this many `R2_MAIN_WINDOWS` windows is reported
#: as unranked, not last. Unchanged by round 4's arrival -- round 2 and round 3's published results were
#: scored against 5 of 8 and that must stay reproducible, so round 4 gets its own constant
#: (`MIN_ELIGIBLE_R4_WINDOWS`) instead of this one being redefined.
MIN_ELIGIBLE_MAIN_WINDOWS = 5

#: The round-4 gate. Round 4's matrix is six windows, not eight, so the round-2 gate's 5-of-8 (62.5%)
#: proportion doesn't carry over as the same number -- the equivalent share of six is 4 (66.7%, the
#: nearest whole-window count at or above 62.5% of 6), so a card eligible in fewer than this many
#: `R4_MAIN_WINDOWS` windows is reported as unranked, not last, the same way `MIN_ELIGIBLE_MAIN_WINDOWS`
#: does for the round-2/3 matrix.
MIN_ELIGIBLE_R4_WINDOWS = 4

#: Prefix `eligible_windows` uses for a provenance-blocked window's reason string. Fixed and
#: recognisable so a caller that cannot import this module -- `strategy-program/tools/score.py`,
#: which duplicates it rather than importing across the hyphenated `strategy-program/tools/`
#: directory, same as it does for `MAIN_WINDOW_TAGS` -- can tell a provenance rejection apart from an
#: ordinary price-history one without parsing a date back out of free text.
PROVENANCE_REASON_PREFIX = "universe knowable only from"

#: Sidecar filename `resolve_universe_knowable_from` falls back to reading when `StrategyCard` has no
#: `universe_knowable_from` field yet. Lives alongside the cards it describes: one file per cards
#: directory, shaped `{agent_id: "YYYY-MM-DD"}`.
PROVENANCE_SIDECAR_FILENAME = "provenance.json"

#: Trading-to-calendar day conversion used to turn a bar count into a "first bar must be no later
#: than" deadline. `_MIN_BARS_FOR_CAUSALITY` and every indicator's warmup are bar counts; the bar
#: store's first-bar dates are calendar dates, and the two units have to meet somewhere. 252/365 is
#: the conventional US-market trading-day fraction.
_TRADING_DAYS_PER_YEAR = 252
_CALENDAR_DAYS_PER_YEAR = 365


def _bars_to_calendar_days(bars: int) -> int:
    """Convert a bar count to a calendar-day span, rounded conservatively.

    `math.ceil` rather than a plain int-divide: eligibility should err toward wrongly excluding a
    borderline card from a window over wrongly admitting one that cannot actually complete its
    warmup before the window starts. Rounding down would occasionally do the latter.
    """
    return math.ceil(bars * _CALENDAR_DAYS_PER_YEAR / _TRADING_DAYS_PER_YEAR)


def symbol_first_bar(conn: duckdb.DuckDBPyConnection, settings: Settings) -> dict[str, dt.date]:
    """First stored daily-bar session date for every symbol the bar store has.

    ``conn`` must have been opened with ``read_only=True`` (`duck.connect(settings.analytics_path,
    read_only=True)`). This module never opens a connection of its own -- it is meant to run
    alongside up to six other analyst agents reading the same store concurrently, and the *default*
    connection takes a write lock that turns concurrent reads into an `IOException` indistinguishable
    from a missing ticker (`strategy-program/WINDOWS.md`, "Data access rule"). Read-only connections
    are the verified-safe case; this function does not re-verify the caller's choice because DuckDB's
    Python connection object does not expose whether it was opened read-only.

    Symbols come from the directory listing under ``interval=1d`` (`duck.stored_symbols`, which reads
    the ``symbol=<SYM>`` partition names rather than querying anything) so a symbol with a partition
    directory but a since-emptied Parquet file is still visited and simply contributes nothing, rather
    than silently vanishing from the result the way a query-only approach would leave it out. Symbols
    with no bars at all (an empty frame) are omitted from the returned mapping entirely -- callers
    (`eligible_windows`) treat "absent from this dict" as "no stored history", which is the same
    conclusion either path leads to.
    """
    first: dict[str, dt.date] = {}
    for symbol in duck.stored_symbols(settings.bars_dir, duck.Interval.DAY):
        frame = duck.read_bars(conn, settings.bars_dir, symbol, duck.Interval.DAY)
        if frame.empty:
            continue
        # `ts` (not `date` -- see the module's own BAR_COLUMNS docstring) is a UTC timestamp; the
        # connection pins TimeZone='UTC' (see `duck.connect`), so `.date()` reads off the correct
        # session date rather than a day that has been rotated by the host's local timezone.
        first[symbol] = frame["ts"].min().date()
    return first


def _spec_text(ref: IndicatorRef) -> str:
    """Render a parsed `IndicatorRef` back to the registry's ``name:arg1,arg2`` spec syntax.

    Mirrors `app.backtest.guards._spec_text`, which does the same thing for the same reason (turning
    an AST node back into the string `app.indicators.registry.request` accepts) but is private to
    that module. Duplicating these few lines here was judged cheaper and less coupling-prone than
    importing another module's underscore-prefixed helper across a package boundary.
    """
    parts: list[str] = []
    for arg in ref.args:
        if isinstance(arg, float) and arg.is_integer():
            parts.append(str(int(arg)))
        else:
            parts.append(str(arg))
    return f"{ref.name}:{','.join(parts)}" if parts else ref.name


def max_indicator_period(expr: str) -> int:
    """The largest lookback (in bars) any indicator referenced in ``expr`` needs before it settles.

    **Parsed with the real grammar** (`app.rules.grammar.parse` + `.indicator_refs`), not a regex --
    the grammar already has to solve "find every indicator call in this expression" correctly for the
    evaluator, and re-deriving that with a pattern over ``name(args)`` risks drifting from it on
    exactly the cases that make the grammar non-trivial (nested calls inside arithmetic, an indicator
    name that is itself a glued parameter like `sma20`, an output suffix like `bb_upper`).

    **Warmup is computed via the real indicator registry**
    (`app.indicators.registry.request(...).spec.warmup(params)`), not by hand-picking "the period
    argument" per indicator family. Once an `IndicatorRef`'s arguments are known, resolving it through
    the registry reuses the exact, tested warmup formula each indicator already ships --
    `sma`/`ema`/`rsi`/`atr` take `period - 1` or `period` depending on the indicator (see
    `app.indicators.momentum._rsi_warmup`'s docstring for why RSI differs by one from SMA/EMA/ATR),
    `macd` takes `(slow - 1) + (signal - 1)` rather than the naive `slow + signal - 1` (see
    `app.indicators.trend._macd_warmup`), `bb` takes `period - 1`, and the whole `swing`/
    `rsi_at_swing`/`macd_at_swing` family takes its `lookback` as the *last* positional argument
    (`app.indicators.swing.SWING_SPEC.params` etc.) with a warmup of `2 * lookback` or more. Every one
    of those is exactly the per-family mapping this function would otherwise have had to hardcode by
    argument position -- the registry already encodes it via each spec's own `ParamSpec` ordering, so
    asking it directly is less code and cannot drift from the formulas the backtest guard itself uses
    (`app.backtest.guards._causality_findings` calls the identical `request.spec.warmup(...)`).

    Returns ``0`` for an expression with no indicator calls at all (e.g. ``close > open``) -- a rule
    with no indicators has no warmup to wait out, and likewise for an empty expression. ``exit`` is
    legitimately empty on any card closed by a take-profit or a hold cap instead of a rule, so this
    is an ordinary input rather than a malformed one; the parser raises on it, so it never reaches
    the parser.
    """
    if not expr.strip():
        return 0
    tree = grammar.parse(expr)
    refs = grammar.indicator_refs(tree)
    if not refs:
        return 0
    periods: list[int] = []
    for ref in refs:
        request = indicator_registry.request(_spec_text(ref))
        periods.append(request.spec.warmup(request.params))
    return max(periods)


def eligible_windows(
    card: StrategyCard,
    first_bars: Mapping[str, dt.date],
    windows: Mapping[str, tuple[dt.date, dt.date, str]],
    *,
    universe_knowable_from: dt.date | None = None,
) -> dict[str, bool | str]:
    """Which of ``windows`` ``card`` is legally allowed to run in.

    A window is eligible when **every** symbol in ``card.universe`` has a first bar early enough to
    supply the indicator warmup (the larger of `max_indicator_period(card.entry)` and
    `max_indicator_period(card.exit)` -- a card is blocked by whichever of its two rules needs more
    history) plus the `_MIN_BARS_FOR_CAUSALITY` post-warmup bars the lookahead guard needs, converted
    to calendar days conservatively via `_bars_to_calendar_days`.

    Returns, per window tag, either ``True`` (eligible) or a `str` explaining why not -- naming the
    *binding* symbol (the one in the universe with the latest first bar, since if that symbol clears
    the deadline every other symbol in the universe necessarily does too) and its first-bar date, e.g.
    ``"NBIS first bar 2024-10-21, needs <= 2019-03-15"``. A symbol with no stored bars at all fails
    every window identically and is reported by name rather than folded into the date-based message,
    since "no data" and "not enough history yet" are different findings for an analyst to act on.

    **``universe_knowable_from``** is a second, independent eligibility question -- see the module
    docstring. When given, any window whose start date is before it is ineligible *regardless* of
    what the price-history check above concluded for that window, because a basket assembled from a
    point-in-time source cannot have been chosen before that source existed no matter how much price
    history its symbols happen to carry. The reason string names both dates explicitly, e.g.
    ``"universe knowable only from 2025-11-14, window starts 2020-02-19"``
    (`PROVENANCE_REASON_PREFIX`), and it overrides a `True` from the price-history check as readily as
    it overrides a price-history rejection -- a window can be legitimately blocked for either reason,
    or both, and the provenance reason is the one worth surfacing since it is the one a person is
    least likely to have checked by hand. `None` (the default) leaves every window's eligibility
    exactly as the price-history check alone determined it -- the behaviour before this parameter
    existed, for cards with no point-in-time provenance to enforce.
    """
    missing = sorted(symbol for symbol in card.universe if symbol not in first_bars)
    if missing:
        reason = f"{missing[0]} has no stored bars"
        if len(missing) > 1:
            reason += f" (also missing: {', '.join(missing[1:])})"
        result: dict[str, bool | str] = dict.fromkeys(windows, reason)
    else:
        binding_symbol = max(card.universe, key=lambda s: first_bars[s])
        binding_date = first_bars[binding_symbol]

        warmup_bars = max(max_indicator_period(card.entry), max_indicator_period(card.exit))
        required_bars = warmup_bars + _MIN_BARS_FOR_CAUSALITY
        lead_days = _bars_to_calendar_days(required_bars)

        result = {}
        for tag, (start, _end, _regime) in windows.items():
            deadline = start - dt.timedelta(days=lead_days)
            if binding_date <= deadline:
                result[tag] = True
            else:
                result[tag] = (
                    f"{binding_symbol} first bar {binding_date.isoformat()}, "
                    f"needs <= {deadline.isoformat()}"
                )

    if universe_knowable_from is not None:
        for tag, (start, _end, _regime) in windows.items():
            if start < universe_knowable_from:
                result[tag] = (
                    f"{PROVENANCE_REASON_PREFIX} {universe_knowable_from.isoformat()}, "
                    f"window starts {start.isoformat()}"
                )

    return result


def load_provenance_sidecar(cards_dir: Path) -> dict[str, dt.date]:
    """Parse ``<cards_dir>/provenance.json`` -- ``{agent_id: "YYYY-MM-DD"}`` -- the fallback source
    for a card's ``universe_knowable_from`` date when `StrategyCard` has no such field yet (see
    `resolve_universe_knowable_from`). ``{}`` when the file does not exist, which is the ordinary case
    for a cards directory holding no point-in-time-derived cards at all.
    """
    path = cards_dir / PROVENANCE_SIDECAR_FILENAME
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object of {{agent_id: 'YYYY-MM-DD'}}")
    return {agent_id: dt.date.fromisoformat(value) for agent_id, value in raw.items()}


def resolve_universe_knowable_from(card: StrategyCard, cards_dir: Path | None) -> dt.date | None:
    """The date ``card``'s universe became knowable, from whichever of two sources has it.

    **Preferred: the `StrategyCard` model itself**, via ``getattr(card, "universe_knowable_from",
    None)`` rather than a direct attribute access -- this module does not *assume* the field exists on
    `backend.app.tournament.models.StrategyCard` (another agent may be adding it there; this module
    checks rather than assumes, and works identically whether or not that has landed yet).

    **Fallback: the sidecar file** `<cards_dir>/provenance.json` (`load_provenance_sidecar`), keyed by
    `card.agent_id`, for as long as the model has no such field. ``cards_dir`` is the directory the
    card's own JSON file lives in -- `main` passes ``path.parent`` for each card, so a multi-root
    ``--cards`` invocation (base, variants, candidates) can carry a different sidecar per directory
    rather than one shared file.

    Returns `None` -- not today's date, not a guess -- when neither source has a date for this card,
    which is the ordinary case for a card whose universe was not derived from a point-in-time source
    at all. `eligible_windows` treats `None` as "no provenance constraint," leaving every window's
    eligibility exactly as the price-history check alone determined it.
    """
    from_model = getattr(card, "universe_knowable_from", None)
    if from_model is not None:
        if not isinstance(from_model, dt.date):
            raise TypeError(
                f"{card.agent_id}.universe_knowable_from is {from_model!r}, expected a date"
            )
        return from_model
    if cards_dir is None:
        return None
    return load_provenance_sidecar(cards_dir).get(card.agent_id)


def _load_cards(roots: list[Path]) -> list[tuple[Path, StrategyCard]]:
    """Every `*.json` card under each of ``roots``, sorted for a stable report order.

    The provenance sidecar lives *in* the cards directory by design -- it is per-card metadata and
    belongs beside what it describes -- so it has to be skipped explicitly here. `StrategyCard`
    forbids extra fields, so loading it as a card fails with a wall of twelve validation errors that
    names every missing required field and buries the actual cause.
    """
    found: list[tuple[Path, StrategyCard]] = []
    for root in roots:
        for path in sorted(root.glob("*.json")):
            if path.name == PROVENANCE_SIDECAR_FILENAME:
                continue
            found.append((path, StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))))
    return found


def _format_cell(value: bool | str, *, width: int) -> str:
    if value is True:
        return "OK".ljust(width)
    text = "FAIL"
    return text.ljust(width)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cards",
        type=Path,
        action="append",
        required=True,
        help="directory of *.json StrategyCard files; may be passed more than once",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="also write the eligibility map as {agent_id: {window_tag: true|reason}}, which is the "
        "shape score.py's --eligibility expects. Without it the scorecard cannot tell a card that "
        "was barred from a window from one that should have run there and did not, and those are "
        "very different failures.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    cards = _load_cards(args.cards)
    if not cards:
        print("no cards found under " + ", ".join(str(r) for r in args.cards))
        return 1

    with duck.connect(settings.analytics_path, read_only=True) as conn:
        first_bars = symbol_first_bar(conn, settings)

    tags = list(ALL_WINDOWS)
    widths = {tag: max(len(tag), 4) for tag in tags}

    header = "agent_id".ljust(28) + "  " + "  ".join(tag.ljust(widths[tag]) for tag in tags)
    header += "  main_ok  gate"
    print(header)
    print("-" * len(header))

    reasons: list[str] = []
    n_gate_pass = 0
    eligibility_map: dict[str, dict[str, bool | str]] = {}
    n_main = len(MAIN_WINDOWS)
    for path, card in cards:
        universe_knowable_from = resolve_universe_knowable_from(card, path.parent)
        elig = eligible_windows(
            card, first_bars, ALL_WINDOWS, universe_knowable_from=universe_knowable_from
        )
        eligibility_map[card.agent_id] = dict(elig)
        cells = "  ".join(_format_cell(elig[tag], width=widths[tag]) for tag in tags)
        n_main_ok = sum(1 for tag in MAIN_WINDOWS if elig[tag] is True)
        gate = "PASS" if n_main_ok >= MIN_ELIGIBLE_MAIN_WINDOWS else "FAIL"
        if gate == "PASS":
            n_gate_pass += 1
        row = f"{card.agent_id.ljust(28)}  {cells}  {str(n_main_ok).rjust(5)}/{n_main}  {gate}"
        print(row)
        for tag in tags:
            if elig[tag] is not True:
                reasons.append(f"  {card.agent_id} / {tag}: {elig[tag]}")

    print()
    print(f"{len(cards)} cards, {n_gate_pass} clear the gate of "
          f"{MIN_ELIGIBLE_MAIN_WINDOWS} eligible main windows")
    if reasons:
        print()
        print("reasons:")
        for line in reasons:
            print(line)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(eligibility_map, indent=2), encoding="utf-8")
        print()
        print(f"wrote {args.json}")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
