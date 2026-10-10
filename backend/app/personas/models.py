"""Frozen wire models for the persona feature, mirroring `docs/INFLUENCER-CONTRACT.md` field for field.

Every model here is `_Frozen` (`frozen=True, extra="forbid"`), the same base `app.agentdesk.models`
uses, so a payload with a field this contract does not name is a loud error rather than a silent
extra. The grounding types are imported from `app.agentdesk.models` rather than redefined -- the
contract pins them as shared, and a second definition is exactly the drift the contract exists to
prevent.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.agentdesk.models import GroundingVerdict  # re-exported; shared shape, never redefined
from app.config import Settings
from app.core.models import (  # foundational money/quantity types (string on the wire)
    Money,
    Quantity,
)

__all__ = [
    "BenchmarkedHorizon",
    "CallOutcome",
    "CallScore",
    "CardCritique",
    "ChatContext",
    "ChatLang",
    "ChatThread",
    "ChatTurn",
    "ClaimChange",
    "DigestCard",
    "EpisodicNote",
    "FollowedSource",
    "GroundingVerdict",
    "Horizon",
    "HorizonReturn",
    "HorizonStat",
    "InfluencerWatchlist",
    "IngestJob",
    "IngestState",
    "InstrumentKind",
    "NoteKind",
    "Persona",
    "PersonaAnswer",
    "PersonaBacktest",
    "PersonaBook",
    "PersonaHolding",
    "PersonaProfile",
    "PersonaRegime",
    "PersonaScorecard",
    "PersonaSkippedCall",
    "PersonaTimeline",
    "PersonaTrade",
    "Platform",
    "ProfileClaim",
    "ProfileDiff",
    "RegimeConsensus",
    "RegimeView",
    "RiskPosture",
    "SavedStrategyDraft",
    "Stance",
    "StancePoint",
    "StanceTimeline",
    "StatEstimate",
    "StrategyCardDraft",
    "SummarySource",
    "TickerMention",
    "TickerThesis",
    "TimelineEntry",
    "TranscriptSource",
    "WatchlistEntry",
    "persona_dir",
    "personas_root",
    "slugify",
]

Platform = Literal["youtube", "manual"]
IngestState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
Stance = Literal["bullish", "bearish", "neutral", "unclear"]
NoteKind = Literal["video_transcript", "post", "manual"]
TranscriptSource = Literal["manual", "auto"]

#: What kind of instrument a symbol is. Set at mention time so a card universe can be restricted to
#: things the backtest engine actually prices as equities, and so the watchlist can flag the rest.
#: Legacy notes (written before this field existed) load as "equity" -- the historical default, and
#: what the overwhelming majority of mentions are; a one-time reclassification can correct them since
#: instrument kind is a deterministic property of the symbol, not of the transcript.
InstrumentKind = Literal["equity", "etf", "index", "future", "crypto", "fx", "unknown"]

#: The holding horizon the speaker implied for a call. A day-trader's "bullish" is an intraday view,
#: not a position to hold to today -- conflating the two is what made return-to-today scoring
#: window-dependent and gave a scalper zero "current holdings". "unclear" is the honest default when
#: the transcript does not say, and what every legacy note loads as.
Horizon = Literal["intraday", "swing", "position", "long_term", "unclear"]

#: Where a note's summary/themes/quotes/mentions actually came from. `"model"` = produced by this
#: project's grounded in-house summariser (`app.personas.summarize`) -- the default, and what every
#: legacy note loads as. `"external"` = pasted back from an outside agent (Gemini, ChatGPT, another
#: Claude) via `app.personas.backfill_ingest`, validated on the way in (ticker validation + a numeric
#: grounding check against the transcript) but not model-grounded here: no `run_grounded` verdict
#: exists for it, so `degraded` is not the same kind of signal it is on a model note. Kept as its own
#: field rather than inferred from anything else, because a reader has no other way to tell the two
#: apart once the note is on disk.
SummarySource = Literal["model", "external"]

#: Risk posture a macro/regime commentator implied. The counterpart to a technical trader's
#: methodology: what a persona with no mechanical toolkit is actually good for.
RiskPosture = Literal["on", "off", "mixed", "unclear"]

#: Every `url` field on a persona wire model, whether it names a followed channel, a video, or a
#: note relaying one, must pass through this. A `javascript:`/`data:` scheme rendered as a link by
#: the frontend would execute in the reader's browser rather than open the source -- see
#: `app.market.news_models`'s identical guard on `NewsItem.url` for the same reasoning, restated
#: here rather than imported because this module has no dependency on `app.market` otherwise and
#: importing one module solely for this helper would be a stranger coupling than duplicating four
#: lines. Case-insensitive and checked after stripping, matching that module's own rule.
_ALLOWED_URL_SCHEMES = ("http://", "https://")


def _require_http_url(value: str) -> str:
    """`value` unchanged (stripped) when it is empty or starts with `http(s)://`; raises otherwise.

    The empty string is a deliberate, pre-existing "no url" sentinel on these fields -- a manual drop
    with text but no source link (`app.personas.service._plan_items`) and a manually-followed source
    with no channel URL to give (`app.personas.service._resolve_source`) both construct their model
    with `url=""` rather than omitting the field (which is itself required, unlike `channel_id`,
    which is `None` in the same cases). Rejecting a non-empty scheme this module does not recognise
    closes the actual gap -- a `javascript:`/`data:` value reaching the frontend as a clickable link
    -- without also rejecting the absence of a url, which is not the same thing as an unsafe one.
    """
    stripped = value.strip()
    if stripped and not stripped.lower().startswith(_ALLOWED_URL_SCHEMES):
        raise ValueError(f"url must be empty or start with http:// or https://, got {value!r}")
    return stripped


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class StatEstimate(_Frozen):
    """A statistic reported WITH its denominator and uncertainty, never bare.

    Every rate or mean this feature shows a reader is over a small, single-window sample, so a point
    value alone invites over-reading. `n` is the sample size the estimate is over; `low`/`high` bound a
    confidence interval at `confidence` (default 0.90); `method` names how the interval was made
    (bootstrap for means, Wilson for proportions). `point`/`low`/`high` are all `None` when `n == 0` --
    an estimate over nothing is undefined, not zero (the discipline the scorecard already applies to
    `hit_rate`)."""

    n: int = 0
    point: float | None = None
    low: float | None = None
    high: float | None = None
    confidence: float = 0.90
    method: Literal["bootstrap", "wilson", "none"] = "none"


class RegimeView(_Frozen):
    """A macro/regime commentator's structured market posture -- the counterpart to a technical
    trader's methodology, for personas that describe no mechanical toolkit. Every non-empty field is
    grounded: `citations` names the notes the view was drawn from. `has_signal` is False for a persona
    that offers no macro view (a pure technical trader), the same honest-empty discipline methodology
    uses. Descriptive, never a trading signal."""

    risk: RiskPosture = "unclear"
    rates: str = ""
    summary: str = ""
    sectors_favoured: tuple[str, ...] = ()
    sectors_avoided: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    has_signal: bool = False


class FollowedSource(_Frozen):
    """One place a persona's content comes from. For youtube, `channel_id` is the resolved `UC…` id
    and `source_id` is `"yt:<channel_id>"`; a manual drop source is `"manual:<uuid>"` with a null
    `channel_id`."""

    source_id: str
    platform: Platform
    handle: str
    channel_id: str | None
    url: str
    """Must be `http://` or `https://` -- enforced below. For `youtube` this is the resolved channel
    URL; for a manual drop source it is whatever the owner supplied when following it."""
    enabled: bool = True
    added_at: dt.datetime

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, value: str) -> str:
        return _require_http_url(value)


class TickerMention(_Frozen):
    """A symbol the influencer named and the stance THEY took on it -- never our own view. `symbol`
    is validated against the instrument table before a mention is ever constructed (see the contract's
    guardrails); this model does not itself hit the DB, it only enforces the surface shape."""

    symbol: str
    stance: Stance
    reasoning: str
    instrument: InstrumentKind = "equity"
    """What kind of instrument this symbol is. Defaults to "equity" so every note written before this
    field existed loads unchanged; a deterministic reclassification pass (`app.personas.instruments`)
    can correct futures/crypto/index mentions after the fact without re-reading the transcript."""
    horizon: Horizon = "unclear"
    """The holding horizon the speaker implied for THIS call. "unclear" when the transcript does not
    say, and what legacy notes load as -- only a fresh summarisation can populate it from the words."""

    @field_validator("symbol")
    @classmethod
    def _upper_nonempty(cls, value: str) -> str:
        v = value.strip().upper()
        if not v:
            raise ValueError("TickerMention.symbol must be non-empty")
        return v


class EpisodicNote(_Frozen):
    """One immutable dated note per ingested item. Persisted as a markdown file in the vault (see the
    contract's frontmatter schema); this is the JSON the API serves for it. Never rewritten once
    written -- only the persona profile and per-ticker theses (Phase 2) are regenerated."""

    note_id: str
    persona: str
    source_id: str
    published: dt.datetime | None
    """When the influencer published it, or `None` when the upstream could not tell us.

    Nullable on purpose, verified 2026-09-01: yt-dlp's *flat* channel listing carries no upload date
    at all (`timestamp`, `upload_date` and `release_timestamp` are all absent), so a note built from
    the listing alone genuinely does not know when the video went up. A per-video metadata fetch
    recovers it, and `None` here means even that did not answer -- never a stand-in date. Fabricating
    one (from `ingested_at`, say) would put a wrong date on the note, order the timeline wrong, and be
    indistinguishable from a real one.
    """

    ingested_at: dt.datetime
    url: str
    """Must be `http://` or `https://` -- enforced below. The source video/post URL, whether it came
    from a YouTube fetch or a manually-pasted drop; see `_require_http_url`'s docstring."""
    title: str | None
    kind: NoteKind
    transcript_source: TranscriptSource | None
    lang: str
    summary: str

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, value: str) -> str:
        return _require_http_url(value)

    themes: tuple[str, ...] = ()
    """What this item was about, 2-5 short bullets -- what they are trading, watching, or arguing.

    Stored on the note rather than recomputed, because the summariser already produces it for every
    item and it is the only per-item structure a `DigestCard` can build its own `themes` from without
    a second model call. Phase 2's consolidation reads these too. Throwing them away at write time
    would mean paying for them again, per card render, forever.
    """

    quotes: tuple[str, ...] = ()
    mentions: tuple[TickerMention, ...] = ()
    path: str

    degraded: bool = False
    """True when this note's summary was released despite failing the grounding gate.

    Persisted on the note (frontmatter `degraded: true`) rather than recomputed, because it is the
    only record that survives: `run_grounded` returns a full `GroundingVerdict` at ingest time, the
    note is written once and never rewritten, and nothing re-runs the gate afterwards. Without this
    field a reader has no way to tell a fact-checked summary from one the gate rejected, and
    `DigestCard.grounding` -- which the page renders -- would have nothing truthful to aggregate.

    Only the boolean is kept, not the whole verdict: the issues name tokens in a transcript the note
    itself no longer quotes in full, so storing them would preserve a complaint the reader cannot
    check. The transcript file is still there for anyone who wants to look.
    """

    summary_source: SummarySource = "model"
    """Who actually wrote this note's summary.

    `"model"` = produced by this project's grounded in-house summariser -- the default, and what every
    legacy note (written before this field existed) loads as, exactly like `TickerMention.instrument`.
    `"external"` = pasted back from an outside agent via `app.personas.backfill_ingest`, validated
    (tickers + numeric grounding against the transcript) but not model-grounded here.

    Defaulted so nothing on disk has to be rewritten, and persisted to frontmatter so the distinction
    survives: `degraded` records whether *our* grounding gate passed, which an external note never ran
    at all, and without this field an externally-authored note would be indistinguishable from one
    this project produced and fact-checked itself.
    """


class Persona(_Frozen):
    """One influencer's identity and the roster of sources feeding its memory. `persona.json` in the
    vault is the source of truth; this is its wire mirror."""

    slug: str
    display_name: str
    sources: tuple[FollowedSource, ...] = ()
    note_count: int = 0
    tickers: tuple[str, ...] = ()
    profile_version: int = 0
    consolidated_at: dt.datetime | None = None
    created_at: dt.datetime


class DigestCard(_Frozen):
    """The card the `/personas` page renders for one persona: the recent picture assembled from its
    notes. `headline` is `""` and `latest_note` is `None` when the persona has no notes yet -- an
    empty card is a valid state, not an error. `warnings` names any upstream that could not be reached
    on the last refresh; the card still renders from stored notes."""

    persona: Persona
    as_of: dt.datetime | None
    window_start: dt.datetime | None
    note_count: int
    headline: str
    themes: tuple[str, ...] = ()
    mentions: tuple[TickerMention, ...] = ()
    latest_note: EpisodicNote | None

    grounding: GroundingVerdict
    """An **aggregate** over the notes in this card's window, not the record of a single model call.

    Only `ok` and `degraded` are meaningful here: `degraded` is true when any note in the window was
    released despite failing the gate, and `ok` is its inverse. `issues`, `attempts` and
    `checked_tokens` stay at their defaults on purpose -- a card is assembled from stored notes
    without making a call, so there is no attempt count to report and inventing one would make a
    summary statistic look like a measurement. The per-note truth is `EpisodicNote.degraded`.
    """

    warnings: tuple[DigestWarning, ...] = ()


class DigestWarning(_Frozen):
    source: str
    reason: str


class IngestJob(_Frozen):
    """Progress of one ingest run. `spent_usd` is a decimal string, the house money rule. `error` is
    populated only when `state == "failed"`."""

    job_id: str
    persona: str
    state: IngestState
    items_total: int = 0
    items_done: int = 0
    items_failed: int = 0
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    spent_usd: str = "0"
    error: str | None = None


class ProfileClaim(_Frozen):
    """One statement in a persona profile, with the notes it was drawn from.

    **`citations` may not be empty, and that is enforced here rather than left to the caller.** A
    profile is the one document in this feature that gets *rewritten*: an episodic note is immutable
    and self-evidently comes from one transcript, but a profile claim is synthesised across many, so
    without the note ids behind it there is no way to tell a thing the influencer actually said from
    a thing the model inferred. Rejecting the empty case at construction means an uncited claim
    cannot reach the vault even by accident.
    """

    text: str
    citations: tuple[str, ...]

    @field_validator("citations")
    @classmethod
    def _at_least_one_citation(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError(
                "a ProfileClaim must cite at least one note_id -- an uncited claim is "
                "indistinguishable from one the model invented"
            )
        return value


class PersonaProfile(_Frozen):
    """The consolidated persona: who they are, what they believe, how they trade.

    Rewritten on every consolidation, with the previous version kept under `profile.history/` so the
    drift between versions stays inspectable. `version` starts at 1; `Persona.profile_version` mirrors
    the newest one.
    """

    persona: str
    version: int
    consolidated_at: dt.datetime
    note_count: int
    summary: str
    beliefs: tuple[ProfileClaim, ...] = ()
    playbook: tuple[ProfileClaim, ...] = ()

    methodology: tuple[ProfileClaim, ...] = ()
    """HOW they trade, not what -- the mechanical toolkit: named indicators (RSI, MACD, moving
    averages, Bollinger, VWAP...), chart timeframes, entry/exit triggers, stop/position-sizing and
    risk rules, and the tools/platforms they name. Distinct from `playbook` (strategic what-they-do):
    this is the technique. Each claim cites the notes it came from, like every other profile claim.
    Captured because a persona that only knows their stock picks cannot inform a *strategy*; their
    method is what Phase 7's card mapping reads. Empty for a persona whose videos never discuss
    technique (a pure macro commentator), which is itself an honest signal."""

    regime: RegimeView | None = None
    """The persona's structured macro/regime posture -- the counterpart to `methodology` for a
    commentator with no mechanical toolkit. None on a profile consolidated before this field existed,
    and `has_signal=False` for a persona who is purely technical. Persisted as its own `## Regime`
    section in `profile.md` and omitted when absent."""

    vocabulary: tuple[str, ...] = ()
    degraded: bool = False
    path: str


class TickerThesis(_Frozen):
    """A persona's running view on one symbol, folded from the notes that named it."""

    persona: str
    symbol: str
    stance: Stance
    updated_at: dt.datetime
    claims: tuple[ProfileClaim, ...] = ()
    path: str

    @field_validator("symbol")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()


CallOutcome = Literal[
    "played_out", "went_against", "flat", "not_directional", "pending", "no_data"
]


class HorizonReturn(_Frozen):
    """A call's return a fixed number of TRADING days after entry.

    `complete` is False (and `return_pct` None) when fewer than `days` bars exist after the entry bar
    yet -- the horizon has not elapsed, so there is no return to report and none is extrapolated. This
    is what makes calls comparable across time: a July call and an August call are both judged over
    the same 5/20/60-bar window, rather than July over months and August over days."""

    days: int
    return_pct: float | None
    complete: bool


class CallScore(_Frozen):
    """One dated ticker statement scored against what the market actually did since.

    Descriptive, never predictive: it says how a stance the influencer took on `said_on` would have
    looked if acted on at the next available close. `entry_*`/`latest_*`/`return_pct`/`basis` are all
    `None` for `pending` (statement newer than the last bar) and `no_data` (no bars) -- those states
    carry no number rather than a fabricated zero.
    """

    symbol: str
    stance: Stance
    note_id: str
    said_on: dt.datetime
    entry_date: dt.datetime | None
    entry_price: float | None
    latest_date: dt.datetime | None
    latest_price: float | None
    return_pct: float | None
    basis: Literal["adjusted", "close"] | None
    outcome: CallOutcome

    horizons: tuple[HorizonReturn, ...] = ()
    """Fixed-horizon returns (5/20/60 trading days after entry). Empty for `pending`/`no_data` calls.
    The return-to-today fields above are "so far"; these are the window-independent measure."""


class HorizonStat(_Frozen):
    """Aggregate at one fixed horizon over the directional calls whose horizon has fully elapsed.
    `hit_rate`/`median_return_pct` are `None` when `directional_count == 0` -- undefined, not zero."""

    days: int
    directional_count: int = 0
    played_out: int = 0
    hit_rate: float | None = None
    median_return_pct: float | None = None
    mean_return_pct: float | None = None
    hit_rate_ci: StatEstimate | None = None
    """Wilson interval for `hit_rate` over the directional calls at this horizon. None when
    `directional_count == 0`. The point matches `hit_rate`; the interval is what keeps a reader from
    over-reading a rate that is really 3-of-4."""
    return_ci: StatEstimate | None = None
    """Bootstrap interval for the MEAN horizon return. None when no call has an elapsed return here."""


class PersonaScorecard(_Frozen):
    """Every scored call for a persona plus the aggregate. `hit_rate` and `median_return_pct` are
    `None` when no directional call had price data -- a rate over zero calls is not zero, it is
    undefined, and the UI must render the difference. `warnings` names the symbols/dates that could
    not be scored (no bars, or a null `published`), never silently dropped.

    The top-level `hit_rate`/`median_return_pct` are return-to-today ("so far"); `horizon_stats`
    carries the window-independent aggregates at each fixed horizon."""

    persona: str
    as_of: dt.datetime
    scored_calls: tuple[CallScore, ...] = ()
    directional_count: int = 0
    played_out: int = 0
    hit_rate: float | None = None
    median_return_pct: float | None = None
    hit_rate_ci: StatEstimate | None = None
    """Wilson interval for the return-to-today `hit_rate`. None when no directional call had price
    data. The single most important honesty signal on the card: a hit rate of 0.16 over n=192 and one
    over n=6 must not read the same."""
    horizon_stats: tuple[HorizonStat, ...] = ()
    warnings: tuple[DigestWarning, ...] = ()


class PersonaAnswer(_Frozen):
    """A model's impression of what the influencer would say, grounded in their own profile and notes.

    Explicitly not the person and not advice (the prompt enforces both). `citations` are the note_ids
    the answer drew on; it is empty only when the persona has no notes yet, in which case `answer`
    says so rather than inventing a view. `stance` is filled only when a `symbol` was asked about and
    the record supports one. `cost_usd` is a decimal string, the house money rule."""

    persona: str
    question: str
    symbol: str | None
    answer: str
    citations: tuple[str, ...] = ()
    stance: Stance | None = None
    grounding: GroundingVerdict
    degraded: bool = False
    cost_usd: str = "0"


# --- Phase 9: persona chat -------------------------------------------------

#: The language a chat turn is written in. See `docs/INFLUENCER-CONTRACT.md`, "Phase 9 -- persona
#: chat (pinned)" -- the same two languages `persona_summary_lang` already supports.
ChatLang = Literal["en", "ko"]


class ChatTurn(_Frozen):
    """One question/answer exchange inside a `ChatThread`, produced by `app.personas.chat.chat_turn`.

    Mirrors `PersonaAnswer` field-for-field where the shape overlaps (`citations`, `stance`,
    `grounding`, `degraded`, `cost_usd`), plus the two fields a persisted, multi-turn record needs
    that a one-shot answer does not: `turn_id`/`asked_at` (so a thread can be replayed in order) and
    `retrieved` (the full note_id set handed to the model this turn, for audit -- `citations` is the
    subset the model actually drew on, always a subset of `retrieved`)."""

    turn_id: str
    asked_at: dt.datetime
    question: str
    symbol: str | None
    lang: ChatLang
    answer: str
    citations: tuple[str, ...] = ()
    retrieved: tuple[str, ...] = ()
    stance: Stance | None = None
    grounding: GroundingVerdict
    degraded: bool
    cost_usd: str


class ChatThread(_Frozen):
    """A persisted multi-turn conversation with one persona, the source of truth being
    `<vault>/influencers/<slug>/chats/<thread_id>.json` (`app.personas.chat.ChatStore`).

    `title` is empty until the first turn is answered, then set from that turn's question (see
    `app.personas.service.chat_turn`). `turns` is oldest-first (the order a reader replays a
    conversation in); the list endpoint (`GET .../chats`) answers each thread with `turns=()` --
    a thread's full content is a `GET .../chats/{thread_id}` away, so the list stays cheap regardless
    of how long any one conversation has grown."""

    thread_id: str
    persona: str
    title: str
    created_at: dt.datetime
    updated_at: dt.datetime
    turn_count: int = 0
    spent_usd: str = "0"
    turns: tuple[ChatTurn, ...] = ()


class ChatContext(_Frozen):
    """What a chat composer needs to know before the first turn: whether the persona's consolidated
    profile is stale relative to the notes actually on disk. `profile_version=0` means never
    consolidated at all -- a legitimate state (see `PersonaProfile.version`'s own docstring), not an
    error."""

    profile_version: int
    profile_note_count: int
    note_count: int
    stale: bool


class PersonaHolding(_Frozen):
    """One OPEN position in a persona's cash-constrained paper book: a `notional_per_position` paper
    buy of a symbol the persona turned bullish on, still held at the end of the replay, entered at the
    first close on/after the call date and marked to the latest available close. Mirrors the paper
    desk's own `Holding` fields structurally so the same UI row renders it; money/quantity are
    string-on-the-wire `Money`/`Quantity`. `return_pct` is a 0-1 FRACTION (e.g. `Decimal("0.1523")` for
    a 15.23% gain), never a pre-multiplied percent. Not advice, not a real position -- a paper
    projection of what following their live calls would hold."""

    symbol: str
    stance: Stance
    note_id: str
    entry_date: dt.date
    entry_price: Money
    quantity: Quantity
    cost_basis: Money
    last_price: Money
    last_price_date: dt.date
    market_value: Money
    unrealised_pnl: Money
    return_pct: Decimal
    bars_held: int
    weight: float
    last_bullish_on: dt.date
    """The date of the most recent bullish call that kept this position open -- either the original buy
    or a later re-affirming bullish mention. `replace_stalest` closes whichever open position has the
    OLDEST `last_bullish_on` first when cash is needed for a fresh buy, so this is the field that
    ordering reads."""


class PersonaTrade(_Frozen):
    """One CLOSED position in a persona's cash-constrained paper book: a `notional_per_position` buy
    later sold -- on a bearish/neutral flip, or closed early to fund a fresh buy when cash ran short.
    `return_pct` is a 0-1 FRACTION, like everywhere else in this book."""

    symbol: str
    note_id: str
    entry_date: dt.date
    entry_price: Money
    exit_date: dt.date
    exit_price: Money
    quantity: Quantity
    realised_pnl: Money
    return_pct: Decimal
    reason: Literal["flip_bearish", "flip_neutral", "replaced"]
    """Why the position was closed: the persona turned bearish or neutral on it, or the book needed the
    cash for a fresh buy and this was the longest-held ("stalest") open position at the time."""


class PersonaSkippedCall(_Frozen):
    """One dated call the replay could not or would not act on -- named so a reader can see what the
    book passed on, not just what it holds."""

    symbol: str
    said_on: dt.date
    reason: Literal["no_cash", "no_market_data", "no_bar_since"]
    """`no_cash`: a fresh buy was wanted but there was nowhere left to raise the cash from (every open
    position was already closed trying). `no_market_data`: the symbol cannot be priced at all.
    `no_bar_since`: the symbol prices fine, but no session has settled since the call was made yet."""


class PersonaBook(_Frozen):
    """A persona's paper book: the result of replaying its dated calls against a $100,000 starting cash
    balance, buying `notional_per_position` on each fresh bullish call and selling on a bearish/neutral
    flip (see `app.personas.paperbook`'s module docstring for the full replay rules). Descriptive, not
    advice. `as_of` is the latest mark/exit date, `None` when the book has neither an open holding nor a
    closed trade. `warnings` names symbols that could not be priced at all -- excluded from the book,
    never counted as zero. `return_pct` (here, and on every holding/trade) is a 0-1 FRACTION."""

    persona: str
    display_name: str
    inception: dt.date
    as_of: dt.date | None
    notional_per_position: Money
    starting_cash: Money = Decimal(0)
    cash: Money = Decimal(0)
    equity: Money = Decimal(0)
    holdings: tuple[PersonaHolding, ...] = ()
    cost_basis_total: Money = Decimal(0)
    market_value_total: Money = Decimal(0)
    unrealised_pnl_total: Money = Decimal(0)
    realised_pnl_total: Money = Decimal(0)
    return_pct: Decimal = Decimal(0)
    trade_count: int = 0
    open_count: int = 0
    trades: tuple[PersonaTrade, ...] = ()
    skipped: tuple[PersonaSkippedCall, ...] = ()
    warnings: tuple[DigestWarning, ...] = ()


class StrategyCardDraft(_Frozen):
    """A rule-card the persona's METHODOLOGY was mapped onto -- direction (b) of Phase 7.

    An exploration lens, never advice or a promise of edge: it translates the persona's described
    technique onto the repo's fixed rule-shape vocabulary and realises it as a real, validated,
    backtestable `StrategyCard` (embedded as JSON in `card`). `mapped` is False -- with `reason` -- for
    a persona that describes no mechanical methodology (a pure macro commentator) or whose mapping the
    card validators rejected; in that case `card`/`rule_shape` are None and nothing is invented.
    `caveat` (always shown) states the inspired-by, no-edge-expected framing."""

    persona: str
    mapped: bool
    reason: str = ""
    rule_shape: str | None = None
    card: dict[str, object] | None = None
    rationale: str = ""
    citations: tuple[str, ...] = ()
    caveat: str = ""
    degraded: bool = False
    cost_usd: str = "0"
    version: int = 0
    """Monotonic version of this persisted draft (0 = unsaved). Drafts are archived like profiles so a
    card the owner looked at can be re-opened exactly, even though re-drafting is non-deterministic."""
    fidelity: float | None = None
    """techniques_represented / techniques_total -- how much of the persona's methodology the fixed
    8-shape DSL could actually express. None when unmapped. Low fidelity is the honest signal that the
    card is a loose caricature of a rich method, not a faithful port."""
    techniques_total: int = 0
    techniques_represented: int = 0
    unrepresentable: tuple[str, ...] = ()
    """Methodology techniques the DSL cannot express (e.g. "opening-range box", "multi-timeframe
    confirmation"), named so the gap is visible rather than silently dropped."""


class SavedStrategyDraft(_Frozen):
    """A `StrategyCardDraft` plus its save metadata, as persisted under `strategy/<version>.json` and
    listed by the drafts endpoint. Separate from the draft itself so the wire draft stays the pure
    mapping result."""

    draft: StrategyCardDraft
    saved_at: dt.datetime
    filename: str


class PersonaRegime(_Frozen):
    """One persona's regime view for the `/regime` endpoint. `has_view` mirrors `view.has_signal` at
    the top level so a caller can filter without unpacking."""

    persona: str
    display_name: str
    view: RegimeView
    has_view: bool = False
    as_of: dt.datetime | None = None


class RegimeConsensus(_Frozen):
    """The cross-persona macro picture: each persona's regime view, plus a tally of how many lean
    risk-on vs risk-off. A reference input the Agent Workflow desk's regime step MAY cite, never a
    signal -- `caveat` (always rendered) says so."""

    as_of: dt.datetime
    personas: tuple[PersonaRegime, ...] = ()
    risk_on: int = 0
    risk_off: int = 0
    mixed: int = 0
    caveat: str = ""


class ClaimChange(_Frozen):
    """One difference between two profile versions: a claim added, removed, or kept but re-cited to
    different notes. `section` says which part of the profile it belongs to."""

    kind: Literal["added", "removed", "recited"]
    section: Literal["belief", "playbook", "methodology"]
    text: str
    citations: tuple[str, ...] = ()


class ProfileDiff(_Frozen):
    """What changed in a persona's memory between two consolidations. Answers the one question the
    growing-memory design raises and nothing else does: is this persona's profile improving or just
    churning? Counts are convenience aggregates over `changes`."""

    persona: str
    from_version: int
    to_version: int
    changes: tuple[ClaimChange, ...] = ()
    added: int = 0
    removed: int = 0
    recited: int = 0


class CardCritique(_Frozen):
    """A persona's in-voice assessment of a strategy card, grounded in their own methodology and
    beliefs -- the reverse of the persona->card mapping. A reading lens, not advice: `verdict` says how
    well the card fits how THEY trade, `cannot_say` when the record does not support a judgement.
    `caveat` (always rendered) states it is an impression of their view, not the person and not
    advice."""

    persona: str
    verdict: Literal["aligned", "mixed", "misaligned", "cannot_say"]
    assessment: str
    citations: tuple[str, ...] = ()
    caveat: str = ""
    degraded: bool = False
    cost_usd: str = "0"


class WatchlistEntry(_Frozen):
    """One symbol on the cross-persona influencer watchlist: how many followed personas are CURRENTLY
    bullish (vs bearish) on it, who, and one backing reason from the most recent bullish note. A
    reference for the strategy layer or the owner -- descriptive, never a buy list."""

    symbol: str
    bullish_count: int
    bearish_count: int
    personas: tuple[str, ...] = ()
    latest_reasoning: str = ""
    as_of: dt.datetime | None = None
    instrument: InstrumentKind = "equity"
    """What kind of instrument the symbol is, so the UI can flag that a "bullish" future or index is
    not something the strategy layer can trade as-is. Drawn from the most recent mention's own field."""


class InfluencerWatchlist(_Frozen):
    """The current-bullish tickers aggregated across every persona, ranked by how many influencers
    back each. `caveat` (always rendered) states this is a reference, not a recommendation."""

    as_of: dt.datetime
    entries: tuple[WatchlistEntry, ...] = ()
    caveat: str = ""


class BenchmarkedHorizon(_Frozen):
    """One fixed horizon's aggregate for the persona-backtest lens: the persona's mean signed call
    return vs the benchmark over the SAME entry->exit windows. All fields `None` when no directional
    call had both a complete horizon and a benchmark window at this horizon -- undefined, not zero."""

    days: int
    n: int = 0
    mean_return_pct: float | None = None
    mean_benchmark_pct: float | None = None
    excess_pct: float | None = None
    win_rate_vs_benchmark: float | None = None
    excess_ci: StatEstimate | None = None
    """Bootstrap interval for `excess_pct` (per-call excess over the benchmark). None when `n == 0`.
    Over these sample sizes the interval almost always straddles zero -- which is the honest finding."""


class PersonaBacktest(_Frozen):
    """A DESCRIPTIVE lens, not a strategy or an alpha claim: how following the persona's dated calls
    would have compared to holding the benchmark, over the same windows. `caveat` is a fixed string
    the UI must render -- small samples over a single window are not evidence of skill."""

    persona: str
    as_of: dt.datetime
    benchmark: str
    call_count: int = 0
    horizons: tuple[BenchmarkedHorizon, ...] = ()
    caveat: str = ""
    warnings: tuple[DigestWarning, ...] = ()


class StancePoint(_Frozen):
    """One dated stance the influencer took on a symbol -- a single point on its evolution."""

    note_id: str
    said_on: dt.datetime
    stance: Stance
    reasoning: str


class StanceTimeline(_Frozen):
    """How one symbol's stance evolved, `points` OLDEST first so it reads as a story forward in time
    (bullish in July, cautious in August, ...)."""

    symbol: str
    points: tuple[StancePoint, ...] = ()


class TimelineEntry(_Frozen):
    """One note placed on the persona's chronological timeline."""

    note_id: str
    published: dt.datetime | None
    title: str | None
    summary: str
    themes: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    url: str
    """Relayed from the source `EpisodicNote.url`, which already enforces `http(s)` -- validated
    again here anyway, since this model has no other guarantee the value it is constructed from went
    through that check."""

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, value: str) -> str:
        return _require_http_url(value)


class PersonaTimeline(_Frozen):
    """The persona's notes as a dated timeline plus per-symbol stance evolution. A pure read over
    stored notes -- no model call, no market fetch. `entries` newest first; `stance_timelines` lists
    symbols whose stance actually changed first (the interesting ones), then by mention count."""

    persona: str
    entries: tuple[TimelineEntry, ...] = ()
    stance_timelines: tuple[StanceTimeline, ...] = ()


# --- vault paths -----------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(handle: str) -> str:
    """A filesystem- and URL-safe slug from a handle. Non-ASCII (e.g. a Korean display name) collapses
    to empty, so callers that may pass a non-latin handle must fall back to the channel id -- the
    resolver does exactly that. `"@creator-a"` -> `"creator-a"`."""
    s = _SLUG_RE.sub("-", handle.strip().lower().lstrip("@")).strip("-")
    return s


def personas_root(settings: Settings) -> Path:
    """`<vault>/influencers/`. The vault dir is `Settings.vault_dir`, default `data/vault/`."""
    return settings.vault_dir / "influencers"


def persona_dir(settings: Settings, slug: str) -> Path:
    return personas_root(settings) / slug
