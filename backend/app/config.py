"""Runtime configuration and filesystem layout.

Paths are resolved relative to the repository root so the app behaves the same whether it is started
from `backend/`, from the repo root, or by the test suite.
"""

from __future__ import annotations

import functools
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[2]

#: A literal copy of `app.market.live.DEFAULT_WATCH_IDLE_SECONDS`, used only by
#: `Settings.livefeed_keepalive_seconds`'s validator. Copied rather than imported because
#: `app.market.live` imports this module -- importing it back here would be a cycle -- and a bare
#: magic number in the validator would silently stop meaning anything the day that constant moved.
#: `tests/test_market_livefeed.py` asserts the two are equal, which is what keeps the copy honest.
_LIVEFEED_KEEPALIVE_CEILING_S = 600.0


class Settings(BaseSettings):
    """Application settings, overridable by environment variables or a .env file.

    Every path can be redirected, which is what lets tests run against a temporary directory without
    touching the user's real data.
    """

    model_config = SettingsConfigDict(
        env_prefix="INVDASH_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- filesystem -------------------------------------------------------
    repo_root: Path = REPO_ROOT
    data_dir: Path = REPO_ROOT / "data"
    """Raw broker exports. Gitignored: contains real financial data."""

    store_dir: Path = REPO_ROOT / "data" / "store"
    """Derived stores. Rebuildable from `data_dir`, therefore disposable."""

    cache_dir: Path = REPO_ROOT / "data" / "cache"
    """Provider response cache. Disposable."""

    library_dir: Path = Path(__file__).resolve().parent / "paper" / "library"
    """The strategy card library `app.paperdesk` and `app.tournament` read from.

    Resolved relative to *this module*, not `REPO_ROOT`. Every other path above is a `REPO_ROOT`
    join, which is correct for those -- they are the user's own data, and `REPO_ROOT` is right on a
    developer's checkout where `data/` sits beside `backend/`. The library is different: it ships
    *inside* the `app.paper` package (see `backend/app/paper/library/`, and the package-data entry
    in `backend/pyproject.toml` that puts its JSON files in a built wheel), so its location cannot
    depend on where the repository root happens to be relative to the installed package -- a real
    `pip install .` has no `strategy-program/` beside it at all. `Path(__file__).parent / "paper" /
    "library"` names the same directory under any install layout, which is the whole point of moving
    the library inside the package rather than leaving it in a sibling research directory.

    Still overridable via `INVDASH_LIBRARY_DIR`, the same as every other directory here, so a user
    can point the app at their own card set without editing the package.
    """

    rounds_dir: Path = REPO_ROOT / "data" / "rounds"
    """Strategy-tournament round records: `app.tournament.jobs` writes them, `app.tournament.results`
    reads them back to serve past leaderboards.

    A `REPO_ROOT` join, like `store_dir` and `cache_dir` above, not derived from `data_dir` -- each of
    those three is its own independent field with its own env var, so setting `INVDASH_DATA_DIR` alone
    does not move any of them; this follows that established pattern rather than improving on it.

    Also unlike `library_dir`: a round is *generated output*, not fixed configuration that ships with
    the app. The library is a bounded, hand-authored, read-only-at-runtime card set that belongs inside
    the package (`Path(__file__).parent / "paper" / "library"`). Rounds are the opposite -- the app
    writes them, one round is megabytes of run files, and they keep growing, so they belong in the data
    directory, not inside a package a real `pip install` puts somewhere read-only. This is exactly what
    `INVDASH_DATA_DIR` and the Docker image's `/data` bind mount already exist for.

    Overridable via `INVDASH_ROUNDS_DIR`, which is what the Docker image sets.
    """

    defects_file: Path = REPO_ROOT / "strategy-program" / "DEFECTS.md"
    """The programme's own record of defects found in the backtest engine, read by
    `app.tournament.findings` to answer "what did this round hit".

    **Optional content, and deliberately not shipped in the Docker image.** `backend/Dockerfile`
    copies the application and nothing else -- `strategy-program/` was removed from it on purpose
    when the card library moved into `app/paper/library/` and the round records moved into
    `data/rounds/`. This file is neither: it is hand-authored programme documentation that lives
    beside the research it documents, and a container has no use for it unless an operator chooses
    to mount it.

    Its absence is a supported state, not a degraded one. `app.tournament.findings` skips a file it
    cannot find, and the `sources` list on the findings response names only the files actually read
    -- so a reader can always tell whether defect entries were unavailable rather than merely absent
    from a round. `tests/test_deployment_paths.py` records the same reasoning in
    `NOT_COPIED_ON_PURPOSE`.

    Overridable via `INVDASH_DEFECTS_FILE`, which is how a deployment that *does* want defect
    entries points at a mounted copy.
    """

    # --- market data ------------------------------------------------------
    contact_email: str = "set-INVDASH_CONTACT_EMAIL@example.invalid"
    """The address SEC EDGAR's fair-access policy requires in every request's ``User-Agent`` --
    it 403s a generic or default client identity, and its documented format is an app name plus a
    real, reachable contact address (see `app.institutions.edgar` and
    `app.market.providers.sec_edgar`'s module docstrings). Yahoo's chart provider reuses the same
    value for the same reason it uses an honest, non-spoofed `User-Agent` at all -- see
    `app.market.providers.yahoo`'s module docstring.

    A real address has to be real at runtime, which is exactly why it cannot be a literal in a
    tracked file: this repository is public-adjacent source, and a hard-coded personal e-mail
    address baked into `git blame` forever is not something a fix can later undo. The default above
    is an obvious, non-deliverable placeholder on purpose -- SEC will 403 a request that carries it,
    which fails loudly instead of quietly leaking a real person's address to every deployment that
    forgets to set this. Set `INVDASH_CONTACT_EMAIL` in `.env` to the address SEC should actually be
    able to reach.
    """

    fred_api_key: SecretStr | None = None
    """Optional, and genuinely optional -- not a degraded mode.

    FRED exposes two endpoints. The JSON API at ``api.stlouisfed.org`` requires this key. The CSV
    download at ``fred.stlouisfed.org/graph/fredgraph.csv`` requires **no key and serves the same
    full history** -- ``DGS10`` comes back to 1962 either way. So an unset key costs a little
    convenience, not coverage, and the Yahoo proxies exist for when FRED itself is unreachable
    rather than for when the key is absent.

    :class:`SecretStr` so the value cannot leak through a ``repr`` -- pydantic renders settings
    objects in full inside pytest failure output and FastAPI tracebacks, and a plain string would
    put the key in any log that captures one.
    """

    @property
    def fred_key(self) -> str | None:
        """The FRED key in plaintext, for use at the HTTP call site only."""
        return self.fred_api_key.get_secret_value() if self.fred_api_key else None

    refresh_on_startup: bool = True
    """Whether `app.market.refresh.refresh_market_data` is started from the application's `lifespan`
    on every server start, sweeping stale bars for the macro movers, every ledger holding and every
    other stored symbol on a background thread. See that module's docstring for the full design
    (priority order, staleness gate, pacing, wall-time cap).

    **Defaults to `True`**, because the owner asked for the app's data to be refreshed when the
    server starts, and a feature that is off unless you know to switch it on does not do that.

    The feature makes real HTTP requests to Yahoo (and, via `app.market.macro.build_snapshot`, FRED
    and CNN), so the test suite must never inherit it. That is enforced where it belongs -- in
    `tests/conftest.py`'s `settings` fixture, which sets `INVDASH_REFRESH_ON_STARTUP=0` alongside
    the other `INVDASH_*` redirections, so every test that exercises the real `lifespan` through
    `with TestClient(app) as ...:` gets a no-op. Shipping a `False` production default instead would
    have made the suite pass by making the feature not happen, which is the wrong place to pay the
    cost. Set `INVDASH_REFRESH_ON_STARTUP=0` in `.env` to opt a deployment out.
    """

    social_snapshot_scheduler_enabled: bool = False
    """Whether `app.market.social_history.start_scheduler` runs a recurring daemon thread from the
    application's `lifespan`, appending one social-sentiment snapshot per watched symbol every
    `social_snapshot_interval_hours`. See that module's docstring for what "watched symbol" means
    (the same `macro._MOVERS`-derived watchlist `app.market.refresh`'s one-shot startup sweep already
    uses for its own single social pass, so there is one social watchlist in the app, not two that
    can drift) and why a *recurring* clock -- not one snapshot per server restart -- is the piece
    `strategy-program/AGENTS-INTEGRATION-PLAN.md` Phase D-social names as missing: StockTwits and
    Reddit serve only a live window with no historical query, so a sentiment history can only be
    built forward, one tick at a time, from here.

    **Defaults to `False`**, unlike `refresh_on_startup` above, and that difference is deliberate
    rather than merely cautious. `refresh_on_startup` can default `True` in production because
    `tests/conftest.py`'s `settings` fixture explicitly disables it via `INVDASH_REFRESH_ON_STARTUP=0`
    before any test runs the real `lifespan`. Nothing sets a `social`-prefixed override there, so a
    `True` default here would start a real background thread -- and, once the interval elapsed,
    real StockTwits/Reddit requests -- inside every other test file's `with TestClient(app) as
    ...:`. `False` is therefore the only default that keeps the suite's network usage at zero without
    an edit to that fixture. Set `INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED=1` in `.env` to opt a
    deployment in, the mirror image of how `refresh_on_startup` is opted *out*.
    """

    social_snapshot_interval_hours: float = 6.0
    """How often the scheduler above takes one pass over its watchlist, in hours -- not minutes, and
    that unit is deliberate. StockTwits and Reddit are free, keyless, public endpoints with no SLA
    and no historical backfill to fall back on if they start throttling: asking more often does not
    buy a denser series, it buys a faster path to a block, which costs the series far more than a
    coarser cadence ever does -- this is a politeness constraint on the provider as much as it is a
    choice about data density. Six hours (four ticks a day) is frequent enough that a trend becomes
    legible across weeks of accumulation while staying comfortably polite. Overridable via
    `INVDASH_SOCIAL_SNAPSHOT_INTERVAL_HOURS`.
    """

    # --- paper live quotes ----------------------------------------------------
    paperlive_enabled: bool = True
    """Whether `GET /api/paperlive/quotes` and `GET /api/paperlive/stream` serve real data at all.
    `False` answers both routes with `503` rather than `404` -- the routes stay registered and
    documented either way; only the data behind them is switched off. See
    `app.api.paperlive._require_enabled`. Overridable via `INVDASH_PAPERLIVE_ENABLED`.
    """

    paperlive_transport: str = "poll"
    """Which `app.market.live.LiveQuoteSource` backs the paper-live routes. `"poll"` (the default)
    drives `PollingQuoteSource` alone. `"stream"` drives `YahooStreamQuoteSource`, which still falls
    back to polling on its own the moment it cannot prove its decoded frames are real -- see that
    class's docstring for exactly what "prove" means.

    Defaults to `"poll"` because `YahooStreamQuoteSource`'s WebSocket frame decoding was never
    verified against a real captured frame: the live probe that produced this shard's brief connected
    to `wss://streamer.finance.yahoo.com/?version=2` successfully but received zero frames in 20
    seconds, because it ran at 02:51 ET on a Sunday with the market closed. The polling transport is
    therefore the one this application can stand behind; the streaming transport is an opt-in,
    best-effort optimisation until someone verifies it against real bytes. See
    `app.market.live`'s module docstring. Overridable via `INVDASH_PAPERLIVE_TRANSPORT`.
    """

    @field_validator("paperlive_transport")
    @classmethod
    def _paperlive_transport_is_known(cls, value: str) -> str:
        if value not in {"poll", "stream"}:
            raise ValueError(f"paperlive_transport must be 'poll' or 'stream', not {value!r}")
        return value

    paperlive_poll_seconds: float = 5.0
    """Poll cadence, in seconds, `PollingQuoteSource` uses while a watched symbol's most recently
    seen `Quote.market_state` is `"REGULAR"`. Deliberately faster than the 30-second TTL
    `app.market.cache._META_LOOKUP_TTL` gives the *shared, cached* quote path would make meaningful
    -- which is exactly why `app.market.live.build_polling_registry` builds this source its own
    registry around an uncached `httpx.Client` rather than reusing `default_registry()`'s cached one;
    see that function's docstring for the full reasoning. Overridable via
    `INVDASH_PAPERLIVE_POLL_SECONDS`.
    """

    paperlive_idle_poll_seconds: float = 60.0
    """Poll cadence, in seconds, for a watched symbol whose most recently seen `market_state` is
    anything other than `"REGULAR"` (`PRE`, `POST`, `CLOSED`, or not yet known). Slower on purpose:
    a closed market's last price does not move between polls, so refreshing it at the same cadence
    as an open one would just be six times the Yahoo traffic for zero new information. Overridable
    via `INVDASH_PAPERLIVE_IDLE_POLL_SECONDS`.
    """

    # --- live feed (the agent-facing keep-warm quote daemon) ------------------
    livefeed_enabled: bool = False
    """Whether `app.market.livefeed.start` launches the keep-warm daemon at startup.

    **Off by default, and that default is about cost, not confidence.** The daemon exists so an
    agent (or a future trading loop) asking for a live quote gets a cached one instead of paying a
    synchronous provider round trip -- which means it keeps the whole watchlist subscribed
    *continuously*: every held ledger symbol plus `app.market.macro._MOVERS` plus
    `livefeed_watchlist`, re-subscribed every `livefeed_keepalive_seconds` so
    `app.market.live.PollingQuoteSource` never evicts them. That source polls every watched symbol
    at `paperlive_poll_seconds` (5s) for as long as any of them reports a `REGULAR` market state, so
    turning this on with a 60-symbol ledger is roughly 12 Yahoo requests a second, all day, whether
    or not a single person or agent is looking at any of it. Reading one quote on demand
    (`app.market.livefeed.latest`, and the `live_quote` evidence section built on it) does **not**
    require this flag -- that is one request, paid by the caller who wanted it. This flag is
    specifically the standing background subscription, so it is opt-in. Set
    `INVDASH_LIVEFEED_ENABLED=1` to turn it on.
    """

    livefeed_watchlist: str = ""
    """Extra symbols the keep-warm daemon should hold open, comma-separated (`"SPY,QQQ,BTC-USD"`).

    Empty by default: the daemon already derives its watchlist from the ledger's own priceable
    instruments and the macro movers, so this is for the symbols nothing else in the application
    knows to care about -- a candidate an agent is watching but does not hold. Overridable via
    `INVDASH_LIVEFEED_WATCHLIST`.
    """

    livefeed_keepalive_seconds: float = 120.0
    """How often the keep-warm daemon re-subscribes its watchlist, in seconds.

    **This has to stay comfortably below `app.market.live.DEFAULT_WATCH_IDLE_SECONDS` (600s), which
    is the point of the daemon.** That constant is how long `PollingQuoteSource` keeps polling a
    symbol nobody has asked about before dropping it; the daemon's whole job is to be the thing that
    keeps asking, so a keepalive interval at or above the eviction window would let every symbol
    fall out of the watch set between two ticks and defeat the feature silently -- the daemon would
    still report `running`, and every quote would still be a cold synchronous fetch. 120s is a fifth
    of the eviction window, so four consecutive ticks can fail before anything is evicted.

    The upper bound is validated below against `_LIVEFEED_KEEPALIVE_CEILING_S`, a literal copy of
    `DEFAULT_WATCH_IDLE_SECONDS` -- copied rather than imported because `app.market.live` imports
    *this* module, and `tests/test_market_livefeed.py` asserts the two are equal so the copy cannot
    drift. Overridable via `INVDASH_LIVEFEED_KEEPALIVE_SECONDS`.
    """

    @field_validator("livefeed_keepalive_seconds")
    @classmethod
    def _livefeed_keepalive_is_below_the_eviction_window(cls, value: float) -> float:
        if value <= 0:
            raise ValueError(f"livefeed_keepalive_seconds must be positive, not {value!r}")
        if value >= _LIVEFEED_KEEPALIVE_CEILING_S:
            raise ValueError(
                f"livefeed_keepalive_seconds must be below {_LIVEFEED_KEEPALIVE_CEILING_S} seconds "
                "(app.market.live.DEFAULT_WATCH_IDLE_SECONDS, the interval after which "
                f"PollingQuoteSource evicts an unrequested symbol), not {value!r}"
            )
        return value

    # --- live agent decisions (the opt-in grounded-decision daemon) -----------
    live_decisions_enabled: bool = False
    """Whether `app.agentdesk.live_loop.start` runs a daemon that asks the model for a grounded
    buy/sell/hold *opinion* on a watchlist, from live quotes, during regular market hours.

    **Off by default, and for the strongest version of the reason `persona_trader_enabled` and
    `workflow_autopilot` are off by default: this daemon spends money unattended, on a timer, with
    nobody confirming any individual call.** Every tick fires one grounded model call per watched
    symbol, so a ten-symbol watchlist at the default half-hour cadence is ~130 calls across a trading
    day whether or not anybody looks at one of them. The on-demand `POST /api/agentdesk/live/decide`
    route works regardless of this flag; only the standing cadence is gated by it.

    **This produces decisions, never trades.** Nothing in `app.agentdesk.live_loop` places, stages or
    fills an order -- it writes a JSONL record and serves it back. Set `INVDASH_LIVE_DECISIONS_ENABLED=1`
    to opt a deployment in.
    """

    live_decisions_interval_minutes: float = 30.0
    """How often the live-decisions daemon ticks, in minutes.

    Half-hourly, not per-minute: a grounded model call takes seconds and costs money, and the whole
    point of the feature is a periodic *opinion* on a live tape, not a high-frequency signal this
    application has no evidence it could act on. Validated at >= 1 below -- a sub-minute cadence would
    spend faster than a person could read the output, and a non-positive one reaching `Event.wait`
    would busy-loop rather than schedule. Overridable via `INVDASH_LIVE_DECISIONS_INTERVAL_MINUTES`.
    """

    @field_validator("live_decisions_interval_minutes")
    @classmethod
    def _live_decisions_interval_is_at_least_a_minute(cls, value: float) -> float:
        if value < 1:
            raise ValueError(
                f"live_decisions_interval_minutes must be at least 1, not {value!r}"
            )
        return value

    live_decisions_symbols: str = ""
    """Which symbols the daemon decides on each tick, comma-separated (`"AAPL,MSFT,SPY"`).

    Empty by default, which means "whatever the ledger actually holds" -- `app.market.refresh.
    _held_symbols`, capped at `live_decisions_max_symbols`. Naming symbols here is how a deployment
    points the daemon at candidates it does not hold. Overridable via `INVDASH_LIVE_DECISIONS_SYMBOLS`.
    """

    live_decisions_max_symbols: int = 10
    """Ceiling on how many symbols one tick decides on when `live_decisions_symbols` is empty and the
    watchlist is derived from the ledger.

    A ledger with sixty priceable instruments would otherwise mean sixty model calls every tick. Ten
    bounds the per-tick spend to something `live_decisions_cap_usd` can actually cover, and the
    explicit `live_decisions_symbols` list is the way to choose *which* ten rather than raising this.
    Overridable via `INVDASH_LIVE_DECISIONS_MAX_SYMBOLS`.
    """

    live_decisions_cap_usd: Decimal = Decimal("1.00")
    """Spend ceiling for one tick, in dollars, shared across every symbol that tick decides on --
    threaded through a single `app.agents.models.AgentBudget`, so the tick stops the moment the cap is
    reached rather than continuing down the watchlist.

    A `Decimal`, like `translate_budget_usd`, because it is passed straight into `AgentBudget.cap_usd`
    with no parsing step. Per *tick*, not per day: `model_spend_daily_cap_usd` remains the aggregate
    backstop, and the daemon checks it before every call. Overridable via
    `INVDASH_LIVE_DECISIONS_CAP_USD`.
    """

    live_decisions_model: str = "claude-haiku-4-5-20251001"
    """Model each live decision uses. Mirrors `app.agents.models.DEFAULT_MODEL` (and both desks'
    `DESK_DEFAULT_MODEL`) by literal value -- a direct import would be circular, as
    `persona_trader_model` above notes -- for the same reason those chose it: this is a high-volume,
    short-turn call, so the cheapest/fastest tier is the right default. Overridable via
    `INVDASH_LIVE_DECISIONS_MODEL`.
    """

    paperdesk_live_fills: bool = False
    """Whether `app.paper.paperbroker.PaperBroker.submit` may fill an order against a live quote
    (`app.market.live`) when the fill date has not happened yet and no stored open can exist for it --
    the newest session's own decision, which today simply never executes because `fill_date`'s bar has
    not been synced (see `app.paperdesk.desk`'s module docstring on why the desk's trading window ends
    at the latest *stored* session).

    **Default `False`, and with it off the broker's behaviour is byte-identical to before this flag
    existed** -- `submit`'s live-quote branch is only reached when a caller passes it a
    `live_quote_source` at all, and nothing wires one in while this is off. A live fill is priced off
    whatever the market happens to be doing at the moment the request is served, so it is not
    reproducible the way every other fill in this application is -- turning it on is an explicit
    acknowledgment that the newest session's numbers can now change between two reads of the same
    page. Overridable via `INVDASH_PAPERDESK_LIVE_FILLS`.
    """

    # --- tax ----------------------------------------------------------------
    ordinary_income_tax_rate: float | None = None
    """The user's actual marginal federal rate on ordinary income, expressed as a fraction of 1 --
    ``0.24`` for the 24% bracket, never ``24``. Unset by default: nothing in this app requires a
    real person to disclose their tax bracket to run a backtest.

    `app.thesis.strategycard.build_tax_impact` reads this for the short-term side of its tax-drag
    estimate. When it is ``None`` that function falls back to the top federal statutory bracket as
    a directional upper bound on tax cost for most filers, not this user's actual rate -- and
    records which of the two happened on `app.thesis.models.TaxImpact.rate_basis`, so a UI can
    never render an assumed bracket as if it were a computed personal figure.
    """

    long_term_capital_gains_tax_rate: float | None = None
    """Same as `ordinary_income_tax_rate`, for the long-term capital-gains side. Unset by default,
    same fallback-to-statutory-upper-bound behaviour, same fraction-of-1 convention."""

    @field_validator("ordinary_income_tax_rate", "long_term_capital_gains_tax_rate")
    @classmethod
    def _rate_is_a_fraction_of_one(cls, value: float | None) -> float | None:
        """Reject anything outside ``[0.0, 1.0]``.

        The one realistic way this field gets misconfigured is typing the bracket as a percentage
        -- ``37`` meaning "37%" -- rather than the fraction this field actually expects. Silently
        accepting that multiplies the modelled tax drag by a hundred and the resulting after-tax
        return would be wrong by an amount large enough to look like a bug in the tax engine
        itself, not in the one number a person typed into `.env`.
        """
        if value is not None and not (0.0 <= value <= 1.0):
            raise ValueError(
                f"tax rate must be a fraction between 0.0 and 1.0, not a percentage -- got "
                f"{value!r}. Use 0.37, not 37, for a 37% bracket."
            )
        return value

    # --- ingest -------------------------------------------------------------
    ingest_max_rows: int = 100_000
    """Hard ceiling on data rows `app.ingest.provenance.read_rows` will load from one broker CSV.

    `read_rows` has to materialise the whole file into a list before any adapter sees it -- 380 of
    Robinhood's 491 real rows carry a newline inside a quoted field, which rules out any row-by-row
    streaming reader that does not already buffer the full file. Without a ceiling, a corrupted or
    accidentally-huge file dropped into `data/` is read in full and only fails much later with an
    opaque `MemoryError` (or, on a machine with enough swap, a silent multi-minute stall) instead of a
    clear, immediate error naming the file.

    The real broker exports measured for this app range from a few rows (a slim SoFi taxable account) to
    about a thousand (Webull's combined Cash/Margin/ROTH order history). ``100_000`` is roughly 100x that
    largest real file -- chosen to be so far outside anything a personal brokerage export could
    plausibly produce that it can never fire on legitimate use (even importing a decade of daily
    trades across every account type this app supports would not approach it), while still bounding a
    pathological file to a few hundred megabytes at most. This is local-only tooling reading the
    user's own files, so the bound exists to turn a silent resource exhaustion into an actionable
    error, not to defend against an adversarial upload.
    """

    # --- paper desk -----------------------------------------------------------
    paperdesk_agent_ids: tuple[str, ...] | None = None
    """Which strategy cards `app.paperdesk.desk` trades, and in what order -- ``None`` (the
    default) defers entirely to that module's own `AGENT_IDS` constant, the three cards this desk
    has always run. Unset by default for the same reason `ordinary_income_tax_rate` above is: the
    fallback the code already has is the right behaviour for everyone who has not deliberately
    chosen otherwise, so nothing here should have to be configured just to keep today's desk
    running exactly as it always has.

    Overridable via ``INVDASH_PAPERDESK_AGENT_IDS``, a JSON array of agent ids -- e.g.
    ``INVDASH_PAPERDESK_AGENT_IDS='["B-momentum","C-trend","c14-riskmanaged-wide","D-new"]'`` --
    since pydantic-settings parses an env var into a complex type (a tuple, here) by reading it as
    JSON rather than splitting on commas. Every id named must resolve to a card somewhere under
    `library_dir`; `app.paperdesk.desk` fails loudly, naming the missing id and where it looked,
    rather than silently trading a roster short one member -- see that module for why a quietly
    incomplete desk is indistinguishable from a card that simply holds cash.
    """

    @field_validator("paperdesk_agent_ids")
    @classmethod
    def _roster_is_not_empty(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        """Reject an explicitly empty roster.

        ``None`` (unset) is the ordinary case and means "use the built-in default" -- see this
        field's docstring. Setting the variable to ``'[]'``, though, is not "use the default," it
        is a roster of zero cards, and a desk with zero cards would render as an empty page with no
        indication anything is wrong. That is exactly the kind of silent, empty-by-accident state
        this application's settings validators exist to catch before it reaches a page (see
        `_rate_is_a_fraction_of_one` above for the same principle applied to a tax rate typed as a
        percentage).
        """
        if value is not None and not value:
            raise ValueError(
                "paperdesk_agent_ids must not be an empty list -- leave INVDASH_PAPERDESK_AGENT_IDS "
                "unset entirely to fall back to app.paperdesk.desk.AGENT_IDS, rather than setting it "
                "to '[]'."
            )
        return value

    # --- agent workflow desk -------------------------------------------------
    workflow_autopilot: bool = False
    """Whether `app.workflow.loop.start` actually launches the daily-cadence daemon thread that fills
    yesterday's staged workflow orders and resolves matured candidate observations, once a day near the
    market open, with no person in the loop. See that module's docstring for the full shape (an
    in-process `threading.Thread(daemon=True)` with a `threading.Event` stop signal, never a detached
    subprocess -- the same precedent `app.evolution.loop`'s own module docstring traces back to
    `strategy-program/DEFECTS.md` D3).

    **Defaults to `False`, the same choice `social_snapshot_scheduler_enabled` makes and for the same
    reason.** `refresh_on_startup` can default `True` because it only ever *reads* market data; this
    flag's daemon *trades* -- it fills real (paper) orders on a schedule with no person confirming any
    individual day's fills -- which is exactly the kind of behaviour that must be turned on
    deliberately, per deployment, never inherited silently from a library default. `False` also keeps
    `tests/conftest.py`'s `settings` fixture honest without needing its own override: nothing sets
    `INVDASH_WORKFLOW_AUTOPILOT` there, so every test building `Settings` through `get_settings()`
    already gets a no-op autopilot for free, the same way an unset `social`-prefixed override does.
    Set `INVDASH_WORKFLOW_AUTOPILOT=1` in `.env` to opt a deployment in.
    """

    paperdesk_autopilot_seat: bool = True
    """Whether the Paper Desk seats the Agent Workflow's autopilot card on the trading book.

    Defaults `True`: unlike `workflow_autopilot` above (a daemon that *trades* on a schedule and so
    must be opted into), this only *renders* a book that already exists on disk -- it fills no order
    and spends nothing, so a page that shows the workflow's own paper record by default is the useful
    default. Set `INVDASH_PAPERDESK_AUTOPILOT_SEAT=0` to hide the seat entirely -- read by
    `app.paperdesk.desk.seats`, the one place the id is appended to the trading roster (see
    `app.paperdesk.autopilot.AUTOPILOT_AGENT_ID`). Turning it off is exactly the one-line-edit
    unseat that seat's own docstring describes, moved into configuration because -- unlike a
    hand-authored *card* seat, whose reasoning belongs in code beside it -- which of the workflow's
    four study books to show is a per-deployment viewing choice, not a strategy decision."""

    paperdesk_autopilot_source: str = "screen:full_workflow"
    """Which of the workflow's paper books the autopilot seat renders, as ``"<universe_source>:<arm>"``
    -- ``universe_source`` one of ``card``/``screen``, ``arm`` one of the four
    `app.workflow.book_models.WorkflowArm` values.

    Defaults to the screened full-workflow book: the researched, gated pipeline (regime -> card select
    -> screen -> research -> gate -> stage) over the dynamically-screened universe, which is the actual
    "combination of strategy" the seat exists to show. An operator who wants to watch a different book
    -- the ungated `screen:raw_signal` null arm, say, or the fixed-universe `card:full_workflow` --
    sets `INVDASH_PAPERDESK_AUTOPILOT_SOURCE` rather than editing code.

    **A malformed value degrades to the default book, logged, never a crash.** This knob only chooses
    which already-persisted book to display; a typo in it must pin the seat to the default, not take
    the whole Paper Desk page (or the app's startup) down -- so it is validated at *read* time in
    `app.paperdesk.autopilot`, gently, rather than by a raising field validator here. See
    `app.paperdesk.autopilot`'s source resolver for the exact fallback."""

    # --- influencer personas --------------------------------------------------
    vault_dir: Path = REPO_ROOT / "data" / "vault"
    """Obsidian-compatible markdown vault the persona feature writes its memory into. Personas live
    under `<vault_dir>/influencers/<slug>/`. A `REPO_ROOT` join like `store_dir`, and its own field
    with its own env var, so it moves independently of `INVDASH_DATA_DIR`. Point it at an existing
    Obsidian vault to edit persona notes alongside the rest of your notes; overridable via
    `INVDASH_VAULT_DIR`.
    """

    backfill_tasks_dir: Path = REPO_ROOT / ".backfill-tasks"
    """Git-ignored working folder the *task packets* generated by `app.personas.backfill` land in.

    A `REPO_ROOT` join like `vault_dir` above, with its own env var (`INVDASH_BACKFILL_TASKS_DIR`),
    because it is a throwaway hand-off staging area rather than tracked state: one Markdown file per
    un-ingested video, pasted by hand into an external agent, and read back by
    `app.personas.backfill_ingest` (which needs the *same* folder to recover the transcript a pasted
    reply must be grounded against). It is a `Settings` field rather than a CLI constant precisely
    because two sides -- the generator and the result-ingest -- have to agree on it, and the in-app
    Backfill page is a third.
    """

    persona_ingest_cap_usd: str = "5"
    """Per-ingest-job spend ceiling on model calls, a decimal string (the house money convention).
    One ingest job summarises up to `persona_backfill_max` transcripts; this bounds what a single
    backfill can cost even if every video is long. Overridable via `INVDASH_PERSONA_INGEST_CAP_USD`.

    Set to ``5`` rather than a lower round number because a full 20-video backfill of a channel of
    long transcripts was measured at ~$3 (Korean captions run longer, and the grounding gate's retries
    add to it), so a $2 ceiling stopped such a channel around its thirteenth video. Five dollars clears
    a 20-video backfill with headroom while still bounding a runaway.
    """

    persona_chat_cap_usd: str = "2"
    """Per-thread spend ceiling on model calls for persona chat (Phase 9), a decimal string (the
    house money convention). Enforced by `app.personas.service.chat_turn` as a 409 once a thread's
    accumulated `ChatThread.spent_usd` reaches this, and passed as-is to
    `app.agents.models.AgentBudget(cap_usd=...)` for each individual grounded call, per
    `docs/INFLUENCER-CONTRACT.md`'s "Phase 9" budget rule. Lower than `persona_ingest_cap_usd` because
    one turn is one short grounded call, not a whole channel's worth of summarisation. Overridable via
    `INVDASH_PERSONA_CHAT_CAP_USD`.
    """

    persona_chat_model: str = "claude-haiku-4-5-20251001"
    """Model used for each persona chat turn. Mirrors `app.agents.models.DEFAULT_MODEL` by literal
    value rather than by importing it: `app.agents.models` imports `Settings` from this module, so an
    import the other way would be circular. Overridable via `INVDASH_PERSONA_CHAT_MODEL`.
    """

    persona_backfill_max: int = 50
    """Hard ceiling on how many videos one ingest job will pull from a channel when no explicit
    `video_urls` are given. The owner's current per-channel request is 20 (passed as the job's
    `limit`); this is the ceiling that `limit` is clamped to, so a mistaken `limit=100000` cannot
    fetch and summarise a whole channel. Overridable via `INVDASH_PERSONA_BACKFILL_MAX`.
    """

    persona_trader_decision_cap_usd: str = "1"
    """Per-decision model spend ceiling for the persona paper trader (`app.personas.trader`), a decimal
    string. One weekly decision is a single grounded call; a dollar is generous headroom for a
    Haiku/Sonnet call plus grounding retries. Overridable via `INVDASH_PERSONA_TRADER_DECISION_CAP_USD`.
    """

    persona_trader_backfill_cap_usd: str = "15"
    """Aggregate model spend ceiling for one persona trader BACKFILL run (weekly decisions from
    inception to today), a decimal string. A ~9-month weekly backfill is ~36 calls at ~$0.06 each
    (~$2) per persona; $15 clears all five with headroom while bounding a runaway. The process-wide
    `model_spend_daily_cap_usd` is the harder aggregate backstop. Overridable via
    `INVDASH_PERSONA_TRADER_BACKFILL_CAP_USD`.
    """

    persona_trader_model: str = "claude-haiku-4-5-20251001"
    """Model each persona trading decision uses. Mirrors `app.agents.models.DEFAULT_MODEL` by literal
    value (a direct import would be circular, as `persona_chat_model` above notes). Overridable via
    `INVDASH_PERSONA_TRADER_MODEL`.
    """

    persona_trader_enabled: bool = False
    """Whether `app.personas.trader_loop.start` runs a daemon that advances every persona's paper
    trader forward one weekly decision as new sessions arrive.

    **Defaults to `False`, the same opt-in shape `persona_refresh_enabled` / `workflow_autopilot` use,
    and for the same reason: this daemon spends money unattended.** Each advance is a grounded model
    call with no person confirming it, so it must be turned on deliberately, per deployment. The
    on-demand decide/backfill endpoints work regardless of this flag; only the automatic forward
    cadence is gated by it. Set `INVDASH_PERSONA_TRADER_ENABLED=1` to opt in.
    """

    # -- Manager desk (docs/MANAGER-DESK-PLAN.md) ------------------------------------------------

    manager_brief_cap_usd: str = "3"
    """Model spend ceiling for ONE manager brief (all of its grounded stages together), a decimal
    string. A brief is ~4 calls over a 15-25k-char evidence text; $3 is generous headroom with
    grounding retries. Commissions (child runs) are capped separately below. Overridable via
    `INVDASH_MANAGER_BRIEF_CAP_USD`.
    """

    manager_commission_cap_usd: str = "6"
    """Per-child ceiling for research the manager commissions (a Trading Agents run is ~$5), a
    decimal string; handed to the child as its own `budget_usd`. Overridable via
    `INVDASH_MANAGER_COMMISSION_CAP_USD`.
    """

    manager_chat_cap_usd: str = "2"
    """Per-thread ceiling for the manager chat, a decimal string, enforced as a 409 once the thread's
    `spent_usd` reaches it -- the same shape `persona_chat_cap_usd` uses. Overridable via
    `INVDASH_MANAGER_CHAT_CAP_USD`.
    """

    manager_autonomy: str = "propose"
    """How far the manager may act on its own research plan: `"propose"` (default -- it lists the
    runs it would commission and a person clicks Run) or `"auto_bounded"` (it starts the kinds named
    in `manager_unattended_kinds` itself, within `manager_brief_cap_usd`). Everything else needs a
    click either way. Overridable via `INVDASH_MANAGER_AUTONOMY`.
    """

    manager_unattended_kinds: str = "persona_chat,vibedesk"
    """Comma-separated commission kinds the manager may start WITHOUT a click when
    `manager_autonomy="auto_bounded"`. Trading Agents and Workflow runs (~$5 each) are deliberately
    not in the default. Overridable via `INVDASH_MANAGER_UNATTENDED_KINDS`.
    """

    manager_model: str = "claude-haiku-4-5-20251001"
    """Model for every manager stage and chat turn. Mirrors `app.agents.models.DEFAULT_MODEL` by
    literal (a direct import would be circular, as `persona_chat_model` notes). Overridable via
    `INVDASH_MANAGER_MODEL`.
    """

    manager_synthesis_model: str = ""
    """Optional override for the `synthesis` stage only (e.g. a Sonnet id for a better cross-source
    read while triage/brief stay on Haiku). Empty means "same as `manager_model`". Overridable via
    `INVDASH_MANAGER_SYNTHESIS_MODEL`.
    """

    manager_autopilot_enabled: bool = False
    """Whether `app.manager.loop.start` runs an in-process daemon that produces one
    `window="yesterday"` brief each session day at `manager_brief_time_et`.

    **Defaults to `False`, the same opt-in shape every other money-spending daemon here uses
    (`workflow_autopilot`, `persona_trader_enabled`, ...).** A brief is several grounded model calls
    with no person confirming them. It must run inside the server process -- launching child research
    from a detached scheduled process crashes (see `strategy-program/tools/phase_b_daily.cmd`). The
    on-demand brief/changes/chat endpoints work regardless of this flag. Set
    `INVDASH_MANAGER_AUTOPILOT_ENABLED=1` to opt in.
    """

    manager_brief_time_et: str = "09:45"
    """Wall-clock time (America/New_York, `HH:MM`) the autopilot brief runs -- after the 09:35 workflow
    fill and the data sweep, so the brief reads the day's opened state. Overridable via
    `INVDASH_MANAGER_BRIEF_TIME_ET`.
    """

    # --- notifications (app.notify) -------------------------------------------
    notify_enabled: bool = False
    """Whether `app.notify.sender` actually delivers events over a channel.

    **Defaults to `False`, and the log fills up regardless.** Every `app.notify.emit()` call appends
    to `data/notify/events.jsonl` and `GET /api/notify/events` serves it whether this is on or off;
    this flag governs delivery alone. That split is what makes the feature safe to ship dark: a fresh
    deployment cannot page anyone by surprise, the whole cursor/poller path is still exercisable, and
    turning delivery on later is this one line rather than a leap of faith. Set
    `INVDASH_NOTIFY_ENABLED=1` to opt in.
    """

    notify_channel: str = "log"
    """Where a delivered event goes: `"log"` (default -- write it to the application log at INFO) or
    `"ntfy"` (POST it to `notify_ntfy_url`/`notify_ntfy_topic` for a phone push). `"log"` is a real
    destination, not a stub: it exercises the entire policy with no delivery hardware configured, and
    is genuinely useful where the server log is already watched. Overridable via
    `INVDASH_NOTIFY_CHANNEL`.
    """

    notify_ntfy_url: str = "https://ntfy.sh"
    """Base URL of the ntfy server. The public instance by default; point it at a self-hosted one to
    keep event text off a third party. Overridable via `INVDASH_NOTIFY_NTFY_URL`.
    """

    notify_ntfy_topic: str = ""
    """The ntfy topic events publish to. **On the public server a topic name is the only access
    control there is** -- anyone who knows it can read every notification -- so this has no default
    and `notify_channel="ntfy"` with it empty sends nothing and logs a warning rather than guessing
    at a shared name. Pick something long and unguessable; see `docs/NOTIFY-RUNBOOK.md`. Overridable
    via `INVDASH_NOTIFY_NTFY_TOPIC`.
    """

    notify_min_severity: str = "notable"
    """Lowest severity that is delivered: `"attention"`, `"notable"` (default) or `"fyi"`. The
    default sends attention and notable and drops fyi, which is what lets producers be generous in
    the *log* without that generosity reaching a phone. Overridable via
    `INVDASH_NOTIFY_MIN_SEVERITY`.
    """

    notify_kinds: str = ""
    """Comma-separated event kinds to deliver; empty (default) means all of them. Matched by prefix
    against the dotted `kind`, so `paper.` subscribes to every fill without enumerating them while
    `manager.brief` subscribes to exactly one thing. Overridable via `INVDASH_NOTIFY_KINDS`.
    """

    notify_quiet_hours: str = "22:00-07:00"
    """Wall-clock window (America/New_York, `HH:MM-HH:MM`, wrapping midnight) during which only
    `attention` events are delivered. Empty means no quiet window.

    **`attention` deliberately overrides this.** A quiet-hours rule with no override would either
    have to be switched off or would silently swallow the one severity that justifies the feature
    existing. Overridable via `INVDASH_NOTIFY_QUIET_HOURS`.
    """

    notify_rate_cap_per_hour: int = 20
    """Maximum events delivered in a rolling hour; beyond it they are logged and suppressed. This is
    the backstop against the failure mode that actually destroys a notification channel -- a producer
    bug emitting in a loop. It suppresses rather than queues on purpose: a hundred deferred
    notifications arriving at once is the same disaster an hour later. `0` disables the cap.
    Overridable via `INVDASH_NOTIFY_RATE_CAP_PER_HOUR`.
    """

    notify_service_token: str = ""
    """Shared secret that lets an external poller (a phone shortcut, a cron) `GET` the read-only
    notification and manager feeds with `Authorization: Bearer <token>` and no browser session.

    **Empty by default, which disables the bearer path entirely** -- there is no token to guess until
    the owner deliberately sets one. It is read-only and enumerated: `app.auth.gate`'s
    `_SERVICE_TOKEN_PATHS` limits it to four `GET`s, so a leaked token exposes the feeds it was
    created for and nothing else, and never a write. Overridable via `INVDASH_NOTIFY_SERVICE_TOKEN`.
    """

    persona_summary_lang: str = "en"
    """Language the persona summaries and profile are written in. The seed channels are mostly Korean;
    the model reads the source-language transcript and writes the note in this language, preserving
    quotes verbatim in their original language. Overridable via `INVDASH_PERSONA_SUMMARY_LANG`.
    """

    persona_refresh_enabled: bool = False
    """Whether `app.personas.refresh_loop.start` runs a daemon that periodically tops up every
    persona's notes from its YouTube sources (ingesting only videos not already on disk).

    **Defaults to `False`, the same opt-in shape `workflow_autopilot` / `social_snapshot_scheduler_enabled`
    use, and for the stronger version of the same reason: this daemon spends money unattended.** A
    top-up summarises new videos through the model with no person confirming any individual run, so it
    must be turned on deliberately, per deployment, never inherited from a library default -- and
    leaving it `False` keeps `tests/conftest.py`'s suite from ever spawning it. Set
    `INVDASH_PERSONA_REFRESH_ENABLED=1` in `.env` to opt in.
    """

    persona_refresh_interval_hours: float = 24.0
    """How often the persona top-up daemon sweeps, in hours. Daily by default: influencer channels
    post at most a few times a day, and each sweep costs real model spend per new video, so a tighter
    cadence buys little and costs more. Overridable via `INVDASH_PERSONA_REFRESH_INTERVAL_HOURS`.
    """

    # --- i18n: on-display narrative translation (Phase 4) ----------------------
    translate_narratives: bool = False
    """Whether `POST /api/i18n/translate` (`app.i18n.narrative.translate_texts`) actually calls the
    model to translate narrative prose to Korean, the same opt-in shape `workflow_autopilot` above
    uses and for the same reason: a page that triggers a paid model call on an ordinary load must be
    turned on deliberately, per deployment, never inherited silently from a library default. `False`
    also keeps `tests/conftest.py`'s `settings` fixture honest without its own override, the same way
    an unset `workflow_autopilot`/`social`-prefixed flag already is. Set
    `INVDASH_TRANSLATE_NARRATIVES=1` in `.env` to opt a deployment in.
    """

    translate_budget_usd: Decimal = Decimal("2.00")
    """Per-request spend ceiling on `POST /api/i18n/translate`'s model calls, threaded through one
    `app.agents.models.AgentBudget` shared across every uncached text in the request -- once spent
    reaches this cap, the remaining texts in that request return `None` rather than continuing to
    call the model. A `Decimal`, like `app.tournament`'s cost fields, rather than the decimal-string
    convention `persona_ingest_cap_usd` above uses, because `AgentBudget.cap_usd` itself is typed
    `Decimal` and this value is passed straight into it with no parsing step. Overridable via
    `INVDASH_TRANSLATE_BUDGET_USD`.
    """

    model_spend_daily_cap_usd: Decimal = Decimal("25")
    """Aggregate ceiling, in dollars, on model spend across the rolling 24-hour window tracked by
    `app.agents.spend.LEDGER` -- distinct from the per-call/per-job caps above (`translate_budget_usd`,
    `persona_ingest_cap_usd`), each of which bounds one request or one job. Those per-call caps do not
    stop an authenticated user from spending without bound by calling a capped route *repeatedly*; this
    cap does. It is checked, before the model call, by `POST /api/i18n/translate`
    (`app.i18n.narrative.translate_texts`) and by the persona routes that call the model
    (`app.personas.service`'s `ask`, `critique`, `consolidate`, `strategy_card`, `start_ingest`); once
    the rolling total is at or past this cap, those routes answer `429` instead of spending further,
    until enough of the window ages out.

    **Deliberately does not gate the evolution loop or agent-desk runs** (`app.agents.designer`/
    `reviewer`/`scout`, `app.tradingagents`, `app.vibedesk`): those are owner-launched, long-running
    jobs already bounded by their own single-slot registries and their own per-run `AgentBudget` caps,
    and stacking a second, shared ceiling on top of a job the owner explicitly started would starve it
    on behalf of an unrelated translate click rather than protect anything. See `app.agents.spend`'s
    module docstring for the caveat that their spend still adds to the tracked total (they share
    `app.agents.client`'s recording), even though nothing ever checks that total against them.

    `0` means unlimited -- only the per-call/per-job caps apply. Overridable via
    `INVDASH_MODEL_SPEND_DAILY_CAP_USD`.
    """

    # --- personal data source ---------------------------------------------
    data_source: Literal["local", "demo", "remote"] = "local"
    """Where the ledger and the personal documents (account manifest, sectors, Planner board) come from.

    - ``local``: files under ``data_dir``/``store_dir``, read and written in place (tests, offline dev).
    - ``demo``: like ``local``, but an empty data directory is seeded with an invented demo portfolio
      (:mod:`app.datasource.demo`) so a fresh clone shows every page populated with no real data.
    - ``remote``: the separate data service (``investing-dashboard-db``) is the system of record. The
      ledger is pulled on demand into a disposable local replica under ``cache_dir`` and refreshed
      whenever the service's revision moves; imports are pushed back as a changeset. See
      :mod:`app.datasource`.
    """

    db_service_url: str = "http://127.0.0.1:8020"
    """Base URL of the data service, used only when ``data_source = "remote"``."""

    db_service_token: SecretStr | None = None
    """Bearer token for the data service (its ``LEDGER_TOKEN``). Required in remote mode; startup
    fails rather than silently falling back to an empty ledger."""

    db_service_timeout_s: float = 30.0
    """Per-request timeout talking to the data service. A snapshot of a multi-year ledger is a few MB."""

    db_service_poll_s: float = 2.0
    """Minimum seconds between revision checks against the data service. Requests inside that window
    reuse the replica without a round trip."""

    # --- authentication -------------------------------------------------------
    auth_enabled: bool = True
    """Whether the login gate (`app.auth.gate.AuthGateMiddleware`) is active.

    **Defaults to `True`**: this is one shared instance for a handful of named users (owner,
    colleagues, UAT personas), reachable on a LAN, and serving the real ledger and tax forms -- so
    the deployed default has to be "locked", not "open". A fresh instance therefore serves `401` to
    everything but the health check and the login routes until the owner creates the first user with
    `python -m app.auth.cli add-user`; that locked-until-seeded state is intended, not a fault.

    `tests/conftest.py`'s `settings` fixture sets `INVDASH_AUTH_ENABLED=0`, so the several dozen
    files that build `TestClient(app)` keep exercising their endpoints without a session. The auth
    tests themselves flip it back on explicitly. Set `INVDASH_AUTH_ENABLED=0` in `.env` for local
    single-user development where a login screen is only friction.
    """

    auth_cookie_secure: bool = False
    """Whether the session cookie carries the `Secure` attribute (sent only over HTTPS).

    **Defaults to `False`** because the supported topology is loopback or LAN over plain HTTP (see
    `docs/DOCKER.md`), where a `Secure` cookie would simply never be sent and every login would
    appear to silently fail. Set `INVDASH_AUTH_COOKIE_SECURE=1` whenever a TLS terminator (Caddy,
    a reverse proxy, or Tailscale Serve) sits in front -- which `docs/AUTH.md` says is required
    before this instance is reachable from anywhere but the local network.
    """

    auth_session_idle_days: int = 14
    """How long a session survives without use. Every validated request pushes this out again, so an
    active user is never signed out mid-session; two idle weeks ends it. Overridable via
    `INVDASH_AUTH_SESSION_IDLE_DAYS`."""

    auth_session_max_days: int = 30
    """Absolute lifetime of a session regardless of activity -- a stolen token is useless after at
    most this long. The stored expiry is always the nearer of the idle and absolute deadlines.
    Overridable via `INVDASH_AUTH_SESSION_MAX_DAYS`."""

    auth_trust_forwarded_for: bool = False
    """Whether `app.api.auth._client_ip` trusts the *last* hop of an incoming `X-Forwarded-For`
    header for login-throttle keying, instead of the raw socket peer.

    **Defaults to `False`.** `X-Forwarded-For` is a client-supplied header unless something in front
    of this process appends to it -- trusting it by default would let anyone spoof the throttle
    bucket a login attempt is keyed against, either to dodge their own lockout or to lock out an
    innocent IP by forging its address. Set `INVDASH_AUTH_TRUST_FORWARDED_FOR=1` only when this
    process sits directly behind the app's own nginx (see `frontend/Dockerfile` and
    `docker-compose.yml`), the one hop in the supported topology this process trusts.

    The *last* hop, not the first: `frontend/Dockerfile`'s proxy config appends nginx's own view of
    the caller (`$proxy_add_x_forwarded_for`) rather than overwriting the header, so a client-supplied
    value survives as every entry except the one nginx itself added. See `_client_ip`'s own docstring
    for the full reasoning.
    """

    @property
    def auth_db_path(self) -> Path:
        """SQLite database holding auth users and sessions.

        Derived from `data_dir` (like `ledger_path` is from `store_dir`) rather than being its own
        env-overridable field, and that is deliberate on two counts. It keeps the auth database on
        the same `/data` volume the Docker image already mounts, so users persist across image
        rebuilds with no extra configuration. And it means `tests/conftest.py`'s redirection of
        `INVDASH_DATA_DIR` into a `tmp_path` carries the auth database along with everything else --
        a test can never write to or read the real one. It is a *sibling* of `store_dir`, not inside
        it, so it is never mistaken for a rebuildable derived store: users are not derived from
        anything and must not be swept with the bar cache.
        """
        return self.data_dir / "auth.sqlite"

    @property
    def ledger_path(self) -> Path:
        """SQLite database holding the transaction ledger.

        In ``remote`` mode this is the newest local replica pulled from the data service (possibly
        stale). Callers that need it fresh go through :func:`app.datasource.ledger_db_path`."""
        if self.data_source == "remote":
            from app.datasource.remote import current_replica_path

            return current_replica_path(self)
        return self.store_dir / "ledger.sqlite"

    @property
    def analytics_path(self) -> Path:
        """DuckDB database for bars and analytical queries."""
        return self.store_dir / "analytics.duckdb"

    @property
    def bars_dir(self) -> Path:
        """Parquet root for OHLCV bars, partitioned by interval and symbol."""
        return self.store_dir / "bars"

    def ensure_dirs(self) -> None:
        """Create the writable directories. Safe to call repeatedly."""
        for path in (self.store_dir, self.cache_dir, self.bars_dir, self.rounds_dir):
            path.mkdir(parents=True, exist_ok=True)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Cleared by tests via `get_settings.cache_clear()`."""
    return Settings()
