"""An in-process job registry for running a strategy-competition round from the application.

**Why in-process, in a daemon worker thread, and never a detached subprocess.** See
`strategy-program/DEFECTS.md` D3: a round launched with `nohup ... &` had no completion signal and
no log, so it was killed with `taskkill /IM python.exe` -- which killed the python process but not
the bash loop driving it, which promptly spawned a replacement. A second run was then started by
hand, and the two fought over the bar store for five consecutive windows: 135 card-runs, every one
failing, zero results written, and the log looked exactly like a legitimately ineligible field. A
thread inside this process has no shell loop above it to survive it, and `DELETE
/api/competition/jobs/{job_id}` sets a `threading.Event` the worker actually checks -- cancellation
here cancels, rather than orphaning a process the caller only *thinks* it killed.

**Why one round at a time, enforced by a process-wide lock rather than a nicety.** Concurrent rounds
are the exact disaster D3 describes: two readers of the DuckDB bar store do not queue, they both
report `IOException`s that the runner records as ordinary card failures and walks past, so a
contended round produces a report that looks complete and is silently missing every card. The host is
also memory-constrained (16 GB physical), so two rounds competing for RAM risk an `Out of Memory
Error` or Windows' own `WinError 1455` on top of the store contention. `_Registry.register` refuses a
second job while one is `"queued"`/`"running"`, atomically, and the caller sees a `409` naming the
live `job_id` -- see `run_round.sh`, which enforces the identical rule (refusing to start when any
`app.tournament` process is already alive) from outside the process; this module enforces it from
inside.

**The worker thread is a daemon.** A job outliving the test process (or, in production, an unclean
shutdown) must not keep the interpreter alive or leave a zombie thread pytest has to wait out.
`reset_registry()` exists for the same reason on the test side: it drops the module's registry and
optionally redirects where run files land, so one test's job can never leak into the next.

**Per-card failure is recorded and walked past, exactly as `app.tournament.__main__.main` does.**
Losing twenty-five completed runs because the twenty-sixth raised would be a poor trade for the small
amount of tidiness it buys. A failed card becomes a `RunResult` with `status="failed"` and the
exception text; the job's own `status` stays on track to `"succeeded"` regardless. `error` on
`JobStatus` is reserved for something that killed the *job* itself (a mandate that fails to load, for
instance) -- not for any individual card's misfortune.

**Reconciliation, at the end of every window.** D3's whole lesson is that a silent shortfall looks
identical to an empty field from the log alone. After each window this module counts the run files
actually written on disk and compares that against the number of cards it attempted, and appends both
numbers to the job's log -- the same check `run_round.sh` does from outside the process, repeated
here because a caller polling `GET /api/competition/jobs/{job_id}` has no shell log to read.

**The mandate's single-name cap is raised to 100% for the same reason `app.tournament.__main__`
raises it.** `app.paper.mandate.default_mandate()` caps one name at 25% of the book, but
`StrategyCard` never validated against that cap -- it only checks `position_pct * max_positions <=
1.0` -- so a card specifying a legitimately larger single-name weight would have every such order
rejected by the broker, and would report a result for a strategy it never actually got to run. The
tournament (and this job) deliberately loosens that one control so a card runs exactly as concentrated
as it declared itself to be, and discloses the loosening rather than hiding it: every other mandate
rule (cash, settlement, minimum clip, whole shares, slippage, fees) stays exactly as strict as the
default states. The raising is applied here, per run, and is deliberately *not* baked into
`default_mandate()` -- a mandate that already had its risk control removed would make the loosening
invisible at every call site instead of visible at each one.

**Where the mandate comes from, and why it is not the UAT persona any more.** It used to be read from
`uat/personas/pro-investor-01.setup.json`, which meant the served application loaded its production
trading constraints out of a test fixture and the Docker image had to ship a UAT tree to boot. Those
numbers now live in code in `app.paper.mandate`. They are still *the same numbers*: every result
committed under `data/rounds/` was measured with the persona's figures, so
`tests/test_paper_mandate.py` asserts the two remain equal field for field. Retuning the desk is
allowed; doing it silently, and thereby making a new round incomparable with an old one under
`strategy-program/PROTOCOL.md` §6's two-round rule, is what that test prevents.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import logging
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings
from app.paper.mandate import default_mandate
from app.paper.paperbroker import Mandate
from app.tournament.__main__ import _NOT_CARDS
from app.tournament.allocation import AllocationCard
from app.tournament.models import StrategyCard
from app.tournament.runner import run_card

__all__ = [
    "MAIN_WINDOWS",
    "MIN_ELIGIBLE_MAIN_WINDOWS",
    "MIN_ELIGIBLE_R4_WINDOWS",
    "MIN_ELIGIBLE_R5_PER_HORIZON",
    "PROVENANCE_CONSTRAINED_WINDOWS",
    "R4_MAIN_WINDOWS",
    "R5_BEAR_WINDOWS",
    "R5_HORIZON",
    "R5_LADDER_WINDOWS",
    "WINDOWS",
    "CurrentRun",
    "DeskOnlyCard",
    "InvalidRoundId",
    "JobAccepted",
    "JobAlreadyFinished",
    "JobAlreadyRunning",
    "JobCreateRequest",
    "JobList",
    "JobNotFound",
    "JobStatus",
    "RoundAlreadyExists",
    "RunResult",
    "UnknownCard",
    "UnknownTier",
    "UnknownWindow",
    "external_round_slot",
    "get_job",
    "list_jobs",
    "request_cancel",
    "reset_registry",
    "start_job",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Window matrix -- copied from `strategy-program/tools/windows.py`, NOT imported
# ---------------------------------------------------------------------------
#
# `strategy-program` is not a legal Python package name (the hyphen), so `strategy-program/tools/
# windows.py` can only be run as a plain script, never imported. `strategy-program/tools/windows.py`
# is the source of truth for this matrix -- the two must be kept in step by hand, and
# `tests/test_competition_jobs.py` asserts this copy matches that file's source text so drift between
# them fails a test rather than silently diverging.

WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    "q4-2018": (dt.date(2018, 9, 21), dt.date(2018, 12, 24), "sharp quarter-long selloff"),
    "covid": (dt.date(2020, 2, 19), dt.date(2020, 6, 30), "COVID crash and snapback"),
    "bear-2022": (dt.date(2022, 1, 3), dt.date(2022, 10, 12), "rate-driven bear"),
    "chop-2015": (dt.date(2015, 4, 7), dt.date(2016, 4, 15), "sideways"),
    "chop-2011": (dt.date(2011, 5, 26), dt.date(2012, 6, 6), "sideways, higher volatility"),
    "bull-2024": (dt.date(2024, 8, 21), dt.date(2025, 8, 20), "bull"),
    "recent": (dt.date(2025, 8, 21), dt.date(2026, 8, 18), "recent bull"),
    "gfc": (dt.date(2007, 10, 9), dt.date(2009, 3, 9), "GFC bear"),
    # Round 4's six-window matrix -- every one of these is new relative to rounds 1-3, none of them
    # appears above, by design (see `strategy-program/tools/windows.py`'s matching comment: a card is
    # frozen and the engine deterministic, so re-running it on a window it has already run recomputes
    # the same number rather than sampling anything new).
    "oil-2014": (dt.date(2014, 6, 20), dt.date(2015, 2, 11), "oil collapse and dollar surge"),
    "volmageddon-2018": (dt.date(2018, 1, 26), dt.date(2018, 4, 2), "volatility shock"),
    "taper-2013": (dt.date(2013, 5, 22), dt.date(2013, 9, 5), "rate shock, taper tantrum"),
    "recovery-2009": (dt.date(2009, 3, 10), dt.date(2010, 4, 23), "post-crisis recovery rally"),
    "inflation-2021": (dt.date(2021, 1, 4), dt.date(2021, 12, 31), "inflation onset and rotation"),
    "banks-2023": (dt.date(2023, 3, 1), dt.date(2023, 5, 31), "regional banking crisis"),
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
    "inv-2022": (
        dt.date(2022, 1, 3),
        dt.date(2024, 12, 31),
        "curve inverted through a strong bull",
    ),
    # Round 5's 27-window matrix, transcribed verbatim from `data/rounds/r5-2026-08/windows.json` --
    # the committed source of truth. Do not recompute or adjust a single date here; if that file ever
    # changes, re-transcribe from it, and let `tests/test_competition_jobs.py` /
    # `tests/test_competition_api.py` catch the drift rather than trusting eyes a second time. Mirrors
    # `strategy-program/tools/windows.py`'s identical round-5 block -- see that module's comment for
    # the full rationale (this is a *horizon ladder*, not another set of named regimes, plus a
    # six-window bear-return supplement); it is not repeated here to avoid two long comments drifting
    # apart from each other on top of the dates they already have to stay in step on.
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
    # section 2). **Unlike every other entry above these are not regime windows** -- they are one
    # market environment cut into pieces, and the only period no card could have been designed
    # against (every card is frozen with designed_through = 2026-02-13). The dates below are each
    # sub-period's own span; the runs that produce them are *cumulative* from 2026-02-17 and
    # differenced, because six independent runs would reset each card's book at every boundary
    # (DEFECTS.md D5).
    "live-1": (dt.date(2026, 2, 17), dt.date(2026, 3, 18), "live out-of-sample, weeks 1-4"),
    "live-2": (dt.date(2026, 3, 19), dt.date(2026, 4, 17), "live out-of-sample, weeks 5-8"),
    "live-3": (dt.date(2026, 4, 20), dt.date(2026, 5, 18), "live out-of-sample, weeks 9-12"),
    "live-4": (dt.date(2026, 5, 19), dt.date(2026, 6, 17), "live out-of-sample, weeks 13-16"),
    "live-5": (dt.date(2026, 6, 18), dt.date(2026, 7, 20), "live out-of-sample, weeks 17-20"),
    "live-6": (dt.date(2026, 7, 21), dt.date(2026, 8, 18), "live out-of-sample, weeks 21-25"),
}

#: Round 5's 21-window horizon ladder -- see `strategy-program/tools/windows.py`'s
#: `R5_LADDER_WINDOWS`/`R5_LADDER_WINDOW_TAGS` for the tag list and the full rationale. Derived from
#: `WINDOWS` here the same way, rather than listed a second time, so the tag list cannot drift from
#: the entries above.
R5_LADDER_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    tag: WINDOWS[tag]
    for tag in (
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
}

#: Round 5's six bear-return supplement windows -- see `strategy-program/tools/windows.py`'s
#: `R5_BEAR_WINDOWS`/`R5_BEAR_WINDOW_TAGS` for why these exist alongside, not inside, the ladder.
R5_BEAR_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    tag: WINDOWS[tag]
    for tag in (
        "b6m-1",
        "b6m-2",
        "b6m-3",
        "b1y-1",
        "b1y-2",
        "b1y-3",
    )
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


#: Each round-5 window's designed horizon -- mirrors `strategy-program/tools/windows.py`'s
#: `R5_HORIZON` exactly (same 27 keys, same values); see that module's comment for why this is carried
#: as its own mapping rather than derived from `(start, end)`. `app.api.competition`'s `/windows`
#: endpoint reads this directly to populate `WindowCatalogEntry.horizon`.
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

#: Round 5's eligibility gate, applied per horizon rather than once over the flat 27-window matrix --
#: mirrors `strategy-program/tools/windows.py`'s `MIN_ELIGIBLE_R5_PER_HORIZON` (same reasoning: a flat
#: gate cannot tell "no data at the short end" apart from "plenty of data everywhere", and 2 is the
#: largest value that still leaves the two-window `h10y` horizon reachable at all). Not enforced by
#: this module (nothing here scores a round), copied only so a caller reconciling this job registry
#: against `strategy-program/tools/windows.py` finds the same constant in both places, the same reason
#: `MIN_ELIGIBLE_MAIN_WINDOWS`/`MIN_ELIGIBLE_R4_WINDOWS` are copied above.
MIN_ELIGIBLE_R5_PER_HORIZON = 2

#: The eight round-2/3 ranked regimes only. Listed explicitly (not derived by excluding `"13f-legal"`
#: from `WINDOWS`, the way this used to be computed) because that exclusion trick stopped being
#: equivalent to "the round-2/3 matrix" once round 4's six windows were added to `WINDOWS` above --
#: excluding only `13f-legal` would now also pull in every round-4 window, and `windows`
#: empty/omitted in `JobCreateRequest` means "every window in `MAIN_WINDOWS`" (see `start_job`), so a
#: silent scope change here would silently change what an omitted-windows round-2/3-style job actually
#: runs. Matches `strategy-program/tools/windows.py`'s `R2_MAIN_WINDOWS`/`MAIN_WINDOWS` (same eight
#: tags, same values).
MAIN_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    tag: WINDOWS[tag]
    for tag in (
        "q4-2018",
        "covid",
        "bear-2022",
        "chop-2015",
        "chop-2011",
        "bull-2024",
        "recent",
        "gfc",
    )
}

#: The round-2 gate: a card eligible in fewer than this many *main* windows is unranked, not last.
#: Not enforced by this module (nothing here scores a round), copied only so a caller reconciling
#: this job registry against `strategy-program/tools/windows.py` finds the same constant in both
#: places. Unchanged by round 4's arrival -- round 2 and round 3's published results were scored
#: against 5 of 8 and that must stay reproducible; round 4's equivalent gate,
#: `strategy-program/tools/windows.py`'s `MIN_ELIGIBLE_R4_WINDOWS` (4 of 6), is not duplicated here
#: because nothing in this module enforces it either.
MIN_ELIGIBLE_MAIN_WINDOWS = 5

#: Round 4's matrix: six windows, none of which appears above. `PROTOCOL.md` §6(a) is the reason
#: they had to be new -- a card is frozen and this engine is deterministic, so re-running a card on a
#: window it has already run recomputes the same number rather than sampling anything, and a
#: promotion resting on two rounds that share windows is one measurement counted twice.
R4_MAIN_WINDOWS: dict[str, tuple[dt.date, dt.date, str]] = {
    tag: WINDOWS[tag]
    for tag in (
        "recovery-2009",
        "taper-2013",
        "oil-2014",
        "volmageddon-2018",
        "inflation-2021",
        "banks-2023",
    )
}

#: Round 4's gate, over six windows -- the same ~65% proportion as round 1's 3-of-5 and round 2's
#: 5-of-8. Kept separate from `MIN_ELIGIBLE_MAIN_WINDOWS` rather than replacing it, because rounds 2
#: and 3 were scored against 5-of-8 and their published results must stay reproducible.
MIN_ELIGIBLE_R4_WINDOWS = 4

#: Windows whose *basket* was not knowable during the period they cover, and which therefore cannot
#: be ranked against the ordinary regimes at all. This is a different property from "belongs to a
#: given round's matrix", and conflating the two is what briefly made every round-4 window render in
#: the run form as provenance-constrained. A regime window is comparable; `13f-legal` is not.
PROVENANCE_CONSTRAINED_WINDOWS: frozenset[str] = frozenset({"13f-legal"})

# ---------------------------------------------------------------------------
# Errors -- raised by `start_job`/`request_cancel`, translated to HTTP status by
# `app.api.competition_jobs`. Kept as plain exceptions here (not HTTPException) so this module has no
# FastAPI dependency and its validation can be exercised directly in tests.
# ---------------------------------------------------------------------------

_ROUND_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class InvalidRoundId(ValueError):
    """`round_id` fails `_ROUND_ID_PATTERN` -- maps to 422."""

    def __init__(self, round_id: str) -> None:
        super().__init__(
            f"round_id {round_id!r} does not match ^[a-z0-9][a-z0-9-]{{0,63}}$ "
            "(lowercase letters, digits and hyphens, starting with a letter or digit)"
        )
        self.round_id = round_id


class RoundAlreadyExists(ValueError):
    """`round_id` already has run files under its `results/` tree -- maps to 409.

    Overwriting a completed round's measurements silently is the kind of thing that costs a week;
    refusing to start is cheap by comparison.
    """

    def __init__(self, round_dir: Path, existing: list[str]) -> None:
        sample = ", ".join(existing[:5])
        super().__init__(
            f"round {round_dir} already has {len(existing)} run file(s) under results/ "
            f"(e.g. {sample}) -- refusing to overwrite a completed round's measurements"
        )
        self.round_dir = round_dir
        self.existing = existing


class UnknownCard(ValueError):
    """A requested `agent_id` is not in the library -- maps to 422, naming what is available."""

    def __init__(self, card_id: str, available: list[str]) -> None:
        super().__init__(f"unknown card {card_id!r}; available: {', '.join(available)}")
        self.card_id = card_id
        self.available = available


class DeskOnlyCard(ValueError):
    """A `desk_only` card was named in, or fell into, a tournament round's field.

    Raised rather than silently skipped, and rather than allowed. A `desk_only` card declares that
    its `designed_through` was checked against the paper desk's inception instead of
    `app.tournament.models.DESIGN_THROUGH` -- so running it in a round would score it on a window
    that opens `TRADE_START` (2026-02-17), months *before* its author's own stated design date. That
    is precisely the lookahead the design cutoff exists to prevent, and it is the shape of leak that
    invalidated three 13F cards in the prior tournament (`strategy-program/CONSTRAINTS.md`).

    Silently dropping such a card from a defaulted tier would be the other wrong answer: a round that
    quietly runs six cards when the tier holds seven reports a complete field and is not one -- the
    failure `strategy-program/DEFECTS.md` D3 records. So an explicitly requested `desk_only` card
    raises, and a tier default excludes it *and* says which ids were excluded.
    """

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(
            f"{agent_id!r} is a desk_only card and cannot run in a tournament round. Its "
            "designed_through was validated against the paper desk's inception, not the "
            "tournament's design cutoff, so scoring it on the tournament window would measure it "
            "on months of data its author already had sight of. It is scored on the desk only."
        )


class ReferenceOnlyCard(ValueError):
    """A `reference_only` card was named in, or fell into, a tournament round's field.

    Handled exactly as `DeskOnlyCard`, and for a stronger version of the same reason. A
    `reference_only` card (`app.tournament.models.StrategyCard.reference_only`) is a promoted `Thesis`
    survivor -- pre-registered, then validated on a holdout running to ~now -- so it is designed past
    every scored window's opening and is deliberately scored on *no* window. Its exemption from the
    design cutoff is only honest while nothing scores it, so a round must refuse it: raise if it was
    asked for by id, exclude-and-report if it merely sat in a defaulted tier. The two answers are the
    same ones `DeskOnlyCard` gives, so a caller sees one consistent contract for "this card is not a
    tournament card."
    """

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(
            f"{agent_id!r} is a reference_only card and cannot run in a tournament round. It is a "
            "promoted Thesis survivor, designed through its own registration date -- after this "
            "window opens -- and is kept as a reference specification, scored on no window at all. "
            "Its evidence lives in the thesis ledger (GET /api/thesis/ledger)."
        )


class UnknownTier(ValueError):
    """The `tier` used to select a default card set is not one of the library's subdirectories."""

    def __init__(self, tier: str, available: list[str]) -> None:
        super().__init__(f"unknown tier {tier!r}; available: {', '.join(available)}")
        self.tier = tier
        self.available = available


class UnknownWindow(ValueError):
    """A requested window name is not in `WINDOWS` -- maps to 422, naming what is available."""

    def __init__(self, window: str, available: list[str]) -> None:
        super().__init__(f"unknown window {window!r}; available: {', '.join(available)}")
        self.window = window
        self.available = available


class JobAlreadyRunning(RuntimeError):
    """A round is already `queued`/`running` -- maps to 409, naming the live `job_id`."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"a round is already running: job {job_id}")
        self.job_id = job_id


class JobNotFound(KeyError):
    """No job with this id in the registry -- maps to 404."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"no job {job_id!r}")
        self.job_id = job_id


class JobAlreadyFinished(RuntimeError):
    """`DELETE` on a job whose status is already terminal -- maps to 409."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id} already finished")
        self.job_id = job_id


# ---------------------------------------------------------------------------
# Wire models
# ---------------------------------------------------------------------------


class JobCreateRequest(BaseModel):
    """`POST /api/competition/jobs` request body."""

    round_id: str
    cards: list[str] = Field(default_factory=list)
    """`agent_id`s to run, resolved from every tier of the library. Empty means every card in
    `tier`."""
    windows: list[str] = Field(default_factory=list)
    """Window names from `WINDOWS`. Empty means every window in `MAIN_WINDOWS`."""
    tier: str = "base"
    """Which library subdirectory `cards`, when empty, defaults to."""


class CurrentRun(BaseModel):
    """The `(window, agent_id)` pair the worker is running right now, if any."""

    window: str
    agent_id: str


class RunResult(BaseModel):
    """One card's outcome in one window."""

    window: str
    agent_id: str
    status: Literal["ok", "failed"]

    total_return: Decimal | None = None
    """`ending_equity / starting_equity - 1`, **not** `AgentResult.total_return`.

    See `strategy-program/DEFECTS.md` D1: the metrics-engine `total_return` field was rebased to the
    first session's close rather than to starting equity for any card that filled on session one,
    which could flip its sign. The fix landed in the engine between rounds, but the ratio computed
    here from `ending_equity`/`starting_equity` is correct under both the old and the new engine --
    it is the same quantity `strategy-program/tools/score.py` uses for exactly that reason, kept
    deliberately even after the underlying fix so a round run through this job stays comparable with
    one run before it.
    """
    benchmark_return: Decimal | None = None
    excess: Decimal | None = None
    """`total_return - benchmark_return`, `None` when there is no benchmark to compare against."""
    capital_exposure: float | None = None
    trades: int | None = None
    seconds: float
    error: str | None = None
    """Exception text, when `status == "failed"`. `None` otherwise."""


class JobAccepted(BaseModel):
    """`202` response to `POST /api/competition/jobs`."""

    job_id: str
    status: Literal["queued", "running"]
    round_id: str
    total_runs: int
    created_at: dt.datetime


class JobStatus(BaseModel):
    """Full job state, returned by `GET`/`DELETE /api/competition/jobs/{job_id}` and embedded in
    `JobList`."""

    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    round_id: str
    cards: list[str]
    windows: list[str]
    total_runs: int
    completed_runs: int
    failed_runs: int
    current: CurrentRun | None = None
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    elapsed_seconds: float
    log: list[str]
    """Last `_LOG_MAXLEN` lines -- a bounded deque, not the whole run's history."""
    results: list[RunResult]
    error: str | None = None
    """Set only when something killed the job itself (e.g. the mandate failed to load) -- never for
    an individual card's failure, which is recorded in `results` instead."""


class JobList(BaseModel):
    """`GET /api/competition/jobs` response. Newest job first."""

    jobs: list[JobStatus]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

#: Every run file in this job's output is tagged with this fixed prefix, matching
#: `{tag}-{agent_id}.json` from `app.tournament.__main__`'s existing layout. That module derives its
#: tag ("r1" vs "r2") from which cards-directory a card was loaded from (the root of `--cards` vs its
#: `round2/` subdirectory) -- a distinction that exists for the frozen tournament cards directories,
#: not for `strategy-program/library/{base,variants,candidates}/`, which this job resolves cards from
#: instead. There is nothing here for that distinction to key off, so every run this job writes uses
#: the fixed tag below: `data/rounds/r2-2026-08/results/*/runs/` already shows every
#: library-sourced run tagged "r1" regardless of which library tier the card came from, for exactly
#: this reason -- the tag reflects the *cards-directory shape*, not the round number.
_TAG = "r1"

#: Auto-proposed cards, written by `app.evolution`'s searcher. Its own tier, not folded into
#: `candidates`, so a searcher can never write into the human programme's `base`/`variants`/
#: `candidates` shelves -- `strategy-program/PROTOCOL.md` section 6 governs what moves between those
#: three, and a fourth writer landing directly in one of them would make that rule unenforceable
#: within a single generation. A card leaves this tier only through `app.evolution.promotion`, which
#: applies section 6's own two-round rule before moving it into `candidates`.
#:
#: Matches `app.evolution.models.GENERATED_TIER`'s value exactly (that module is this name's
#: contract, `app.evolution/__init__.py`'s own docstring says so) but is deliberately not imported
#: from it: `app.evolution` depends on `app.tournament` -- it drives a round through this very
#: module, see `app.evolution.execute` -- not the other way around, and importing downward across
#: that boundary for the sake of one string literal would invert the package layering for no benefit.
_GENERATED_TIER = "generated"

_LIBRARY_TIERS = ("base", "variants", "candidates", _GENERATED_TIER)
_LOG_MAXLEN = 200
_HISTORY_MAXLEN = 50


def _library_root() -> Path:
    return get_settings().library_dir


def _generated_tier_dir() -> Path:
    """`data/loop/generated/` -- where `app.evolution`'s searcher writes proposed cards.

    **Not** `_library_root() / _GENERATED_TIER`, even though every other tier in `_LIBRARY_TIERS` is
    resolved that way. Matches `app.evolution.models.generated_tier_dir(get_settings())` exactly --
    that function's own docstring has the full story: `library_dir` lives under `backend/app/paper/`,
    which sits inside the read-only image layer in the container (`docker-compose.yml` bind-mounts
    only `./data`), and a loop that tried to write proposed cards there failed 1,644 of 1,673
    generations with `OSError: [Errno 30] Read-only file system` before this moved. Computed locally
    here rather than imported from `app.evolution.models` for the same layering reason `_GENERATED_TIER`
    above is a duplicated literal, not an import: `app.evolution` depends on `app.tournament`, not the
    reverse, and importing downward across that boundary for one path expression would invert it. Keep
    this in step with `app.evolution.models.generated_tier_dir` by hand, the same way `_GENERATED_TIER`
    is kept in step with `GENERATED_TIER` and `MAIN_WINDOWS` is kept in step with
    `strategy-program/tools/windows.py`.
    """
    return get_settings().data_dir / "loop" / _GENERATED_TIER


def _load_library_index() -> dict[str, tuple[str, StrategyCard]]:
    """Every card in the library, keyed by `agent_id`, tagged with which tier directory held it.

    `_NOT_CARDS` (imported from `app.tournament.__main__`) is skipped for the same reason that module
    skips it: a `provenance.json` sidecar is not a card, and `StrategyCard`'s `extra="forbid"` would
    raise a wall of validation errors naming every missing required field if it were loaded as one.

    **`_GENERATED_TIER` is the one tier this function tolerates a payload it cannot parse as a
    `StrategyCard` in.** `app.evolution`'s searcher proposes either card shape
    (`app.evolution.models.CardShape` is `"rules"` or `"allocation"`) and writes both into
    `generated/`; an `AllocationCard` payload sitting there is not a defect, it is exactly the other
    half of what that package produces, and this index only ever serves `StrategyCard`-by-`agent_id`
    lookups (`_resolve_cards`, and `/api/competition/library`'s tier listing). A payload this function
    cannot parse as a `StrategyCard` in `generated/` is therefore skipped, silently to this function's
    own caller -- `app.evolution.execute` is the module that reads a `generated/`-tier `AllocationCard`
    by dispatching on its actual shape, and it does its own parsing rather than going through this
    index at all.

    `base`/`variants`/`candidates` stay strict, on purpose: a malformed payload in one of those three
    *is* a defect (a human analyst submitted something that does not validate against the one contract
    this program holds them to), and silently skipping it here would hide a genuinely broken card the
    same way skipping any other parse error in this function would -- exactly the failure mode
    `strategy-program/DEFECTS.md` D3 warns against generalised from "a run looks complete and isn't"
    to "a library tier listing looks complete and isn't."
    """
    index: dict[str, tuple[str, StrategyCard]] = {}
    library_root = _library_root()
    for tier in _LIBRARY_TIERS:
        tier_dir = _generated_tier_dir() if tier == _GENERATED_TIER else library_root / tier
        if not tier_dir.is_dir():
            continue
        for path in sorted(tier_dir.glob("*.json")):
            if path.name in _NOT_CARDS:
                continue
            raw = path.read_text(encoding="utf-8")
            if tier == _GENERATED_TIER:
                try:
                    card = StrategyCard.model_validate_json(raw)
                except ValidationError:
                    # Not a defect -- see this function's docstring. A non-StrategyCard payload
                    # (an AllocationCard, most likely) in `generated/` is real, valid content that
                    # simply is not addressable through this StrategyCard-only index.
                    continue
            else:
                card = StrategyCard.model_validate_json(raw)
            index[card.agent_id] = (tier, card)
    return index


def _resolve_cards(requested: list[str], tier: str) -> tuple[StrategyCard, ...]:
    """`requested`, resolved against every library tier, or -- if empty -- every card in `tier`.

    An explicit `cards` list may name any `agent_id` from any of `base`/`variants`/`candidates`;
    `tier` only matters as the *default* field when `cards` is omitted, matching the API contract's
    "empty or omitted means every card in tier" wording.
    """
    index = _load_library_index()
    if requested:
        unknown = [card_id for card_id in requested if card_id not in index]
        if unknown:
            raise UnknownCard(unknown[0], sorted(index))
        # An explicitly named desk_only or reference_only card raises: the caller asked for it by id,
        # so the honest answer is why it cannot run, not a field silently one card short of what was
        # requested. Both are "not a tournament card"; each names its own reason.
        for card_id in requested:
            if index[card_id][1].desk_only:
                raise DeskOnlyCard(card_id)
            if index[card_id][1].reference_only:
                raise ReferenceOnlyCard(card_id)
        return tuple(index[card_id][1] for card_id in requested)
    if tier not in _LIBRARY_TIERS:
        raise UnknownTier(tier, list(_LIBRARY_TIERS))
    # A defaulted tier excludes desk_only *and* reference_only cards instead of raising -- "every
    # card in `candidates`" should not become unrunnable because one non-tournament card lives there
    # -- but it logs which ids it dropped and why, so a round's field is never quietly smaller than
    # the tier it claims to cover.
    excluded = sorted(
        f"{card.agent_id} ({'reference_only' if card.reference_only else 'desk_only'})"
        for card_tier, card in index.values()
        if card_tier == tier and (card.desk_only or card.reference_only)
    )
    if excluded:
        logger.info(
            "tournament: excluding %d non-tournament card(s) from tier %r: %s",
            len(excluded),
            tier,
            ", ".join(excluded),
        )
    tier_cards = sorted(
        (
            card
            for card_tier, card in index.values()
            if card_tier == tier and not card.desk_only and not card.reference_only
        ),
        key=lambda card: card.agent_id,
    )
    return tuple(tier_cards)


def _resolve_windows(requested: list[str]) -> tuple[str, ...]:
    if not requested:
        return tuple(MAIN_WINDOWS)
    unknown = [w for w in requested if w not in WINDOWS]
    if unknown:
        raise UnknownWindow(unknown[0], sorted(WINDOWS))
    return tuple(requested)


def _validate_round_id(round_id: str) -> None:
    if not _ROUND_ID_PATTERN.match(round_id):
        raise InvalidRoundId(round_id)


def _check_round_not_already_populated(round_dir: Path) -> None:
    results_dir = round_dir / "results"
    if not results_dir.is_dir():
        return
    existing = sorted(str(p) for p in results_dir.glob("*/runs/*.json"))
    if existing:
        raise RoundAlreadyExists(round_dir, existing)


def _load_mandate() -> Mandate:
    """The application's default mandate, with its single-name cap raised to 100%.

    See this module's docstring for the reasoning, which mirrors `app.tournament.__main__`'s
    `--honour-persona-cap` default: the mandate's real 25% cap was never checked by `StrategyCard`
    itself, so cards that declared a larger single-name weight than that would have every such order
    rejected by the broker and would report the result of a strategy they never actually got to run.
    Loosening the cap here is a deliberate, disclosed choice, not an oversight -- every other mandate
    rule (cash, settlement, minimum clip, whole shares, slippage, fees) is untouched.
    """
    mandate = default_mandate()
    return dataclasses.replace(mandate, max_single_name_weight=Decimal(1))


class _Job:
    """Mutable state for one round, guarded by its own lock.

    Every field below is written by (at most) one worker thread and read by any number of concurrent
    HTTP requests polling `GET`. The lock exists so a reader never observes a torn update (e.g.
    `completed_runs` incremented but the matching `results` entry not yet appended) rather than to
    prevent races between writers, since there is only ever one writer per job.

    `cards` is typed `tuple[StrategyCard | AllocationCard, ...]`, wider than `_worker`'s own path
    ever populates it (`start_job` always resolves `StrategyCard`s only, via `_load_library_index`).
    The widening is for `external_round_slot` below: `app.evolution.execute.run_generation` can drive
    a mix of both card shapes through this same job's bookkeeping, and duplicating this whole class
    for one field's type would be a worse trade than a union nothing in this module's own worker path
    ever exercises the right-hand side of.
    """

    def __init__(
        self,
        *,
        round_id: str,
        cards: tuple[StrategyCard | AllocationCard, ...],
        windows: tuple[str, ...],
        output_root: Path,
    ) -> None:
        self.job_id = uuid.uuid4().hex
        self.round_id = round_id
        self.cards = cards
        self.windows = windows
        self.output_root = output_root
        self.total_runs = len(cards) * len(windows)
        self.completed_runs = 0
        self.failed_runs = 0
        self.current: tuple[str, str] | None = None
        self.status: Literal["queued", "running", "succeeded", "failed", "cancelled"] = "running"
        self.created_at = dt.datetime.now(dt.UTC)
        self.started_at: dt.datetime | None = None
        self.finished_at: dt.datetime | None = None
        self.log: deque[str] = deque(maxlen=_LOG_MAXLEN)
        self.results: list[RunResult] = []
        self.error: str | None = None
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()

    def append_log(self, line: str) -> None:
        with self.lock:
            self.log.append(line)

    def snapshot(self) -> JobStatus:
        with self.lock:
            end = self.finished_at or dt.datetime.now(dt.UTC)
            current = (
                CurrentRun(window=self.current[0], agent_id=self.current[1])
                if self.current
                else None
            )
            return JobStatus(
                job_id=self.job_id,
                status=self.status,
                round_id=self.round_id,
                cards=[card.agent_id for card in self.cards],
                windows=list(self.windows),
                total_runs=self.total_runs,
                completed_runs=self.completed_runs,
                failed_runs=self.failed_runs,
                current=current,
                created_at=self.created_at,
                started_at=self.started_at,
                finished_at=self.finished_at,
                elapsed_seconds=(end - self.created_at).total_seconds(),
                log=list(self.log),
                results=list(self.results),
                error=self.error,
            )


class _Registry:
    """Process-wide job bookkeeping: the one-round-at-a-time lock, and a bounded history."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: _Job | None = None
        self._jobs: deque[_Job] = deque(maxlen=_HISTORY_MAXLEN)
        self._by_id: dict[str, _Job] = {}

    def register(self, job: _Job) -> None:
        """Atomically check-and-set the running slot. Raises `JobAlreadyRunning` if occupied."""
        with self._lock:
            if self._current is not None:
                raise JobAlreadyRunning(self._current.job_id)
            self._current = job
            if self._jobs.maxlen is not None and len(self._jobs) >= self._jobs.maxlen:
                evicted = self._jobs.pop()
                self._by_id.pop(evicted.job_id, None)
            self._jobs.appendleft(job)
            self._by_id[job.job_id] = job

    def running_job_id(self) -> str | None:
        with self._lock:
            return self._current.job_id if self._current is not None else None

    def finish(self, job: _Job) -> None:
        with self._lock:
            if self._current is job:
                self._current = None

    def get(self, job_id: str) -> _Job:
        with self._lock:
            job = self._by_id.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def list_jobs(self) -> list[_Job]:
        with self._lock:
            return list(self._jobs)


_registry = _Registry()
_output_root_override: Path | None = None


def _default_output_root() -> Path:
    if _output_root_override is not None:
        return _output_root_override
    return get_settings().rounds_dir


def reset_registry(*, output_root: Path | None = None) -> None:
    """Testing hook: drop every tracked job and, optionally, redirect where run files land.

    The worker thread is a daemon so it cannot keep the test process alive, but without this the
    registry's "one round at a time" lock and its job history would leak across tests in the same
    process. `output_root`, when given, becomes the default for every job started afterwards via
    `start_job` without an explicit `output_root` of its own -- the mechanism
    `tests/test_competition_jobs.py` uses to keep the whole suite off the real
    `data/rounds/`. Passing `None` restores the real default.
    """
    global _registry, _output_root_override
    _registry = _Registry()
    _output_root_override = output_root


@contextlib.contextmanager
def external_round_slot(
    round_id: str, *, total_runs: int, label: str = "evolution"
) -> Iterator[_Job]:
    """Reserve the process-wide round slot for a runner that is not this module's own worker.

    **Why this exists at all.** `app.evolution.execute.run_generation` drives one generation of
    auto-proposed cards through `app.tournament.runner.run_card` / `app.tournament.allocation.
    run_allocation` directly, on its own thread -- not through `start_job`'s daemon worker, because
    `_worker` only ever runs `StrategyCard`s (see `_load_library_index`) and a generation can contain
    `AllocationCard`s too, and because the evolution loop's own retry/promotion logic has no business
    living inside this module's worker function. What it still MUST do is take the exact same
    single-slot lock `_worker` takes, for the exact reason this module's own docstring gives
    (`strategy-program/DEFECTS.md` D3): two things driving a backtest against the bar store at once is
    the disaster this lock exists to prevent, and that is precisely as true of two *threads* in this
    one process as it is of two OS processes. A second, independent lock in `app.evolution.execute`
    would not prevent a caller from bypassing this one -- it would just be a second thing to keep in
    sync with the first, which is the load-bearing invariant of the whole system and not a place to
    improvise. This function is therefore not a new locking mechanism: it constructs a real `_Job` and
    puts it through `_Registry.register`, the identical check-and-set `start_job` itself uses.

    **What the caller gets, and what it is expected to do with it.** The yielded `_Job` starts with
    empty `cards`/`windows` (an allocation-generation's cards are not resolved from the library the
    way `start_job`'s are, so there is nothing this function could fill them with on the caller's
    behalf) and `total_runs` set from the parameter of that name, since an empty `cards`/`windows`
    tuple would otherwise compute a misleading zero. A caller that wants `GET
    /api/competition/jobs/{job_id}` to show anything more than that while the generation runs should
    set `job.cards`, `.windows` and `.output_root` itself, under `job.lock`, immediately after
    entering -- exactly the fields `_worker` would have set via `_Job.__init__` had this gone through
    `start_job` instead. Everything else (`.current`, `.completed_runs`, `.failed_runs`, `.results`,
    `.log`, `.cancel_event`, `.status`) is the same mutable, lock-guarded state `_worker` drives, and a
    caller should drive it the same way `_worker` does -- see that function for the pattern.

    **Contention and release.** `_registry.register` raises `JobAlreadyRunning` exactly as it does
    for `start_job`, naming whichever job -- from either path -- currently holds the slot; this
    function does not catch it, so it propagates to the caller immediately, before anything is
    written. The slot is released (`_registry.finish`) in a `finally`, on every exit path including an
    exception raised out of the `with` body. If the body leaves the job's own `status` still
    `"queued"`/`"running"` when that happens -- a caller that died before reaching its own
    success/failure bookkeeping -- this marks the job `"failed"` with the exception text first, so a
    crash in the caller cannot leave a job stuck reporting `"running"` forever in `GET
    /api/competition/jobs`. A caller that *does* set a terminal `status` itself before returning or
    raising leaves that status untouched; this is a safety net, not the primary way a generation is
    expected to report its own outcome.
    """
    job = _Job(round_id=round_id, cards=(), windows=(), output_root=_default_output_root())
    job.total_runs = total_runs
    _registry.register(job)
    with job.lock:
        job.started_at = dt.datetime.now(dt.UTC)
    job.append_log(f"{label}: reserved the round slot for {round_id} ({total_runs} planned run(s))")
    try:
        yield job
    except BaseException as exc:
        with job.lock:
            if job.status in ("queued", "running"):
                job.status = "failed"
                job.error = (
                    f"{label} raised without recording a terminal status: "
                    f"{type(exc).__name__}: {exc}"
                )
                job.finished_at = dt.datetime.now(dt.UTC)
        job.append_log(f"{label}: FAILED {type(exc).__name__}: {exc}")
        raise
    finally:
        _registry.finish(job)


def start_job(request: JobCreateRequest, *, output_root: Path | None = None) -> JobAccepted:
    """Validate `request`, launch its worker thread, and return immediately.

    `output_root` overrides the module-level default for this call only (see `reset_registry` for the
    process-wide override tests use when driving the job system through the HTTP layer instead of
    calling this function directly). Validation happens in this order: is a round already running
    (409, cheapest check, matches `run_round.sh`'s own first move); is `round_id` well-formed (422);
    does that round already have run files (409); do the requested cards and windows exist (422
    each). A `JobAlreadyRunning` from a race against another concurrent `POST` can still surface from
    `_Registry.register` itself, after this function's own pre-check passed -- that atomic check is
    what actually enforces the invariant; the pre-check only makes the common case fail fast without
    doing the cards/windows resolution first.
    """
    running = _registry.running_job_id()
    if running is not None:
        raise JobAlreadyRunning(running)

    _validate_round_id(request.round_id)
    root = output_root if output_root is not None else _default_output_root()
    round_dir = root / request.round_id
    _check_round_not_already_populated(round_dir)

    cards = _resolve_cards(request.cards, request.tier)
    windows = _resolve_windows(request.windows)

    job = _Job(round_id=request.round_id, cards=cards, windows=windows, output_root=root)
    _registry.register(job)

    # Everything this response reports is read *before* the worker starts, and that ordering is
    # load-bearing rather than stylistic. `JobAccepted.status` is `Literal["queued", "running"]`,
    # which is the honest contract for a 202 -- but `job.status` is mutated by the worker thread,
    # so reading it after `thread.start()` is a race: a job that fails immediately (an unreadable
    # card, a store that has gone away) or finishes very fast can already be `"failed"` or
    # `"succeeded"` by the time the next line runs. Pydantic would then reject the model *inside*
    # the request handler and the caller would get a 500 for a job that was accepted and is running
    # perfectly well. The client learns the real state from `GET /jobs/{job_id}` a moment later,
    # which is what that endpoint is for; this response only has to be true when it is sent.
    # `_Job.__init__` sets `status = "running"` and nothing has been able to change it yet, so the
    # literal below is a statement of fact rather than an optimistic guess -- and unlike reading the
    # mutable attribute, it is a fact the type checker can also confirm, since `job.status` is
    # declared as the full five-value union and cannot be narrowed by ordering alone. The assert
    # keeps the two from drifting: change the initial state and this fails loudly here.
    assert job.status == "running", f"a job is {job.status!r} before its worker has started"
    accepted = JobAccepted(
        job_id=job.job_id,
        status="running",
        round_id=job.round_id,
        total_runs=job.total_runs,
        created_at=job.created_at,
    )

    thread = threading.Thread(
        target=_worker, args=(job,), daemon=True, name=f"competition-job-{job.job_id}"
    )
    thread.start()

    return accepted


def get_job(job_id: str) -> JobStatus:
    return _registry.get(job_id).snapshot()


def list_jobs() -> JobList:
    return JobList(jobs=[job.snapshot() for job in _registry.list_jobs()])


def request_cancel(job_id: str) -> JobStatus:
    """Set the job's cancellation event. The worker notices between card runs, never mid-`run_card` --
    see this module's docstring for why interrupting a run in flight is not attempted."""
    job = _registry.get(job_id)
    with job.lock:
        if job.status not in ("queued", "running"):
            raise JobAlreadyFinished(job_id)
        job.cancel_event.set()
    job.append_log("cancellation requested")
    return job.snapshot()


def _worker(job: _Job) -> None:
    """Run every `(window, card)` pair in `job`, in window-major order, writing each result as it
    finishes and walking past any card that raises. See the module docstring for the reasoning behind
    every choice below; this function is deliberately the only place that reasoning is executed."""
    with job.lock:
        job.started_at = dt.datetime.now(dt.UTC)
    job.append_log(
        f"round {job.round_id}: {len(job.cards)} cards x {len(job.windows)} windows "
        f"= {job.total_runs} runs"
    )

    try:
        mandate = _load_mandate()
    except Exception as exc:  # a job-killing failure, recorded rather than raised
        with job.lock:
            job.status = "failed"
            job.error = f"failed to load mandate: {type(exc).__name__}: {exc}"
            job.finished_at = dt.datetime.now(dt.UTC)
        job.append_log(f"FAILED to load mandate: {type(exc).__name__}: {exc}")
        _registry.finish(job)
        return

    settings = get_settings()

    for window in job.windows:
        if job.cancel_event.is_set():
            break

        start, end, _regime = WINDOWS[window]
        runs_dir = job.output_root / job.round_id / "results" / window / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        attempted = 0

        for card in job.cards:
            if job.cancel_event.is_set():
                job.append_log(f"{window}: cancelled before {card.agent_id}")
                break

            with job.lock:
                job.current = (window, card.agent_id)
            attempted += 1
            started = time.time()

            if not isinstance(card, StrategyCard):
                # `_Job.cards` is widened to `StrategyCard | AllocationCard` so that
                # `external_round_slot` can register a job for `app.evolution.execute`, which knows how
                # to run both shapes. *This* worker only knows the rule-DSL one, and `_resolve_cards`
                # only ever hands it those, so reaching here is a programming error rather than a bad
                # card -- recorded as a failed run and walked past, exactly as any other per-card
                # failure is, rather than raising and taking the whole round down with it.
                elapsed = time.time() - started
                with job.lock:
                    job.failed_runs += 1
                    job.results.append(
                        RunResult(
                            window=window,
                            agent_id=card.agent_id,
                            status="failed",
                            seconds=elapsed,
                            error=(
                                f"{type(card).__name__} cannot be run by app.tournament.jobs' worker; "
                                "app.evolution.execute.run_generation runs this shape"
                            ),
                        )
                    )
                job.append_log(f"{window}: {card.agent_id} FAILED (unsupported card shape)")
                continue

            try:
                result = run_card(card, settings=settings, mandate=mandate, start=start, end=end)
            except Exception as exc:  # recorded and walked past, see module docstring
                elapsed = time.time() - started
                error_text = f"{type(exc).__name__}: {exc}"
                with job.lock:
                    job.failed_runs += 1
                    job.results.append(
                        RunResult(
                            window=window,
                            agent_id=card.agent_id,
                            status="failed",
                            seconds=elapsed,
                            error=error_text,
                        )
                    )
                job.append_log(f"[{window}] {card.agent_id}: FAILED {error_text}")
                continue

            elapsed = time.time() - started
            total_return = result.ending_equity / result.starting_equity - Decimal(1)
            excess = (
                total_return - result.benchmark_return
                if result.benchmark_return is not None
                else None
            )

            run_path = runs_dir / f"{_TAG}-{card.agent_id}.json"
            run_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

            with job.lock:
                job.completed_runs += 1
                job.results.append(
                    RunResult(
                        window=window,
                        agent_id=card.agent_id,
                        status="ok",
                        total_return=total_return,
                        benchmark_return=result.benchmark_return,
                        excess=excess,
                        capital_exposure=result.capital_exposure,
                        trades=len(result.trades),
                        seconds=elapsed,
                    )
                )
            job.append_log(
                f"[{window}] {card.agent_id}: ok {elapsed:.1f}s trades={len(result.trades)} "
                f"ret={float(total_return):+.2%}"
            )

        with job.lock:
            job.current = None

        # Reconcile: the runner never aborts on a failed card, so a silent shortfall -- run files
        # written not matching runs attempted -- is the failure mode to catch here, exactly as
        # `run_round.sh` does from outside the process. See `strategy-program/DEFECTS.md` D3.
        written = len(list(runs_dir.glob("*.json")))
        job.append_log(
            f"{window}: reconcile {written} run file(s) written, {attempted} run(s) attempted"
        )

        if job.cancel_event.is_set():
            break

    with job.lock:
        job.current = None
        job.finished_at = dt.datetime.now(dt.UTC)
        job.status = "cancelled" if job.cancel_event.is_set() else "succeeded"

    _registry.finish(job)
