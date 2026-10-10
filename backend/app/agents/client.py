"""Credential resolution, the call itself, cost accounting and the spend cap.

This module is the one place in `app.agents` that touches the `anthropic` package or the process
environment. Every other module in this package (`prompts`, `designer`, and `scout` when it lands)
goes through :func:`call_structured` rather than building a client of its own, so the credential
trap this module exists to catch -- an empty `ANTHROPIC_API_KEY` silently winning its precedence slot
and then authenticating with nothing -- only has to be handled in one place.

**`import anthropic` never happens at module scope.** Every function that needs the package imports
it locally, so a machine with no `anthropic` installed -- or a test that never exercises this module --
still gets a working application. `app.agents.models.AgentUnavailable` is what a caller sees instead
of an `ImportError` traveling up through the loop's supervisor thread.

**Two transports, because one machine had a credential that the SDK could never see.** The `anthropic`
SDK only ever authenticates from three places: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or an
`ant auth login` profile. A machine with none of those three set, but with Claude Code installed and
logged in, made `is_available()` return `(False, "no usable Anthropic credential: ...")` even though a
usable login sat one file over, at Claude Code's own `~/.claude/.credentials.json` -- a store the SDK
has never read and never will, because it belongs to a different product surface. `app.agents.
cli_transport` is the second transport this module now knows about: it shells out to the locally
installed `claude` binary, which already carries that login, and does the same structured-output job
`call_structured` does for the SDK, prompt-engineered instead of native (see that module's own
docstring for why). The SDK path is tried first whenever it is usable -- it is the lower-latency path,
no subprocess spawn -- and the CLI is the fallback, never the reverse; :func:`is_available` and
:func:`credential_source` both say which one actually won.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from app.agents import cli_transport
from app.agents.models import (
    DEFAULT_MODEL,
    AgentBudget,
    AgentCall,
    AgentResponseInvalid,
    AgentRole,
    AgentUnavailable,
    BudgetExhausted,
    CredentialSource,
    agent_calls_dir,
)
from app.agents.spend import LEDGER
from app.config import Settings

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import anthropic

__all__ = [
    "build_client",
    "call_structured",
    "credential_source",
    "estimate_cost_usd",
    "is_available",
]

# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

#: Environment variable naming the active `ant auth login` profile, mirroring the SDK's and the
#: `ant` CLI's own resolution: `ANTHROPIC_PROFILE`, defaulting to `"default"` when unset.
_PROFILE_ENV = "ANTHROPIC_PROFILE"
_DEFAULT_PROFILE = "default"


def _config_dir() -> Path:
    """Where an `ant auth login` profile is stored: `$ANTHROPIC_CONFIG_DIR` if set, otherwise
    `%APPDATA%\\Anthropic` on Windows and `~/.config/anthropic/` everywhere else -- the same
    resolution the SDK and the `ant` CLI use, restated here because this module is the one place
    that has to answer "is there a credential at all" without constructing a client first."""
    override = os.environ.get("ANTHROPIC_CONFIG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "Anthropic"
    return Path.home() / ".config" / "anthropic"


def _profile_credentials_path() -> Path:
    """`<config_dir>/credentials/<profile>.json` -- where a token minted by `ant auth login` lives
    for the active (or `ANTHROPIC_PROFILE`-selected) profile. Existence, not validity, is what
    :func:`credential_source` checks: a present-but-expired token is `build_client`'s problem to
    discover when the API call itself fails, not this function's to pre-diagnose."""
    profile = os.environ.get(_PROFILE_ENV) or _DEFAULT_PROFILE
    return _config_dir() / "credentials" / f"{profile}.json"


def credential_source() -> CredentialSource:
    """Which credential -- or transport -- wins: `ANTHROPIC_API_KEY`, then `ANTHROPIC_AUTH_TOKEN`,
    then an on-disk `ant auth login` profile, then a locally-installed Claude Code CLI binary, matching
    `app.agents.models.CredentialSource`'s own documented order. Never constructs a client and never
    spawns the CLI to check -- the CLI check is `app.agents.cli_transport.resolve_cli_binary`, itself
    only a filesystem/`PATH` lookup, so this function stays as cheap as its three SDK-slot checks.

    **Presence, not validity.** An `ANTHROPIC_API_KEY` set to the empty string still wins this slot
    -- `"ANTHROPIC_API_KEY" in os.environ` is true for `""` -- and this function returns `"api_key"`
    for it, exactly as the real SDK would go on to authenticate with an empty key rather than fall
    through to a profile (or the CLI) underneath it. Whether that makes the credential *usable* is
    :func:`is_available`'s question, deliberately kept separate so a caller can always ask "which slot
    won" and "is it any good" independently -- and, now, so a broken SDK slot reported here does not
    stop :func:`is_available` from still finding a working CLI underneath it.
    """
    if "ANTHROPIC_API_KEY" in os.environ:
        return "api_key"
    if "ANTHROPIC_AUTH_TOKEN" in os.environ:
        return "auth_token"
    if _profile_credentials_path().is_file():
        return "profile"
    if cli_transport.resolve_cli_binary() is not None:
        return "cli"
    return "none"


def _sdk_is_available() -> tuple[bool, str]:
    """The original three-slot check, unchanged: whether one of `ANTHROPIC_API_KEY`,
    `ANTHROPIC_AUTH_TOKEN` or an `ant auth login` profile is both present and usable. Split out of
    :func:`is_available` so that function can independently ask "is the CLI usable" without this
    function's `"none"` case needing to know the CLI exists at all.
    """
    if "ANTHROPIC_API_KEY" in os.environ:
        if not os.environ.get("ANTHROPIC_API_KEY", ""):
            return False, (
                "ANTHROPIC_API_KEY is set but empty -- it still wins its precedence slot ahead of "
                "ANTHROPIC_AUTH_TOKEN and any logged-in profile, and then authenticates with an "
                "empty key rather than falling through to either; unset it entirely (do not set it "
                "to '') or give it a real key"
            )
        return True, "credential resolved via ANTHROPIC_API_KEY"
    if "ANTHROPIC_AUTH_TOKEN" in os.environ:
        if not os.environ.get("ANTHROPIC_AUTH_TOKEN", ""):
            return False, "ANTHROPIC_AUTH_TOKEN is set but empty"
        return True, "credential resolved via ANTHROPIC_AUTH_TOKEN"
    if _profile_credentials_path().is_file():
        return True, f"credential resolved via an `ant auth login` profile at {_profile_credentials_path()}"
    return False, (
        "no usable Anthropic credential: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN and an "
        "`ant auth login` profile are all unset"
    )


def is_available() -> tuple[bool, str]:
    """Whether an agent call can actually be attempted right now -- via either transport -- and why or
    why not in a sentence a log line or `GET /api/agents/health` can show verbatim.

    This is the function every other check in this module goes through, precisely because
    :func:`credential_source` alone cannot tell "no credential" apart from "a credential that will
    fail the instant it is used" -- the empty-`ANTHROPIC_API_KEY` trap `app.agents.models`' own
    module docstring calls out as the documented #1 auth failure. Catching it here, before a network
    call (or a subprocess spawn) is ever made, turns a confusing `AuthenticationError` deep in the SDK
    into a one-line reason the loop can log and move on from.

    **The SDK is checked first and returned immediately if usable.** It is the lower-latency path --
    no subprocess spawn -- so a machine with a real `ANTHROPIC_API_KEY` never pays for a CLI lookup it
    was never going to need. Only when the SDK's own three slots are all absent or broken does this
    function ask `app.agents.cli_transport.is_available` at all; if that also comes back unusable, the
    combined reason names both, since a caller (or a person reading a log line) needs to know both
    doors were tried, not just the last one.
    """
    sdk_available, sdk_reason = _sdk_is_available()
    if sdk_available:
        return True, sdk_reason
    cli_available, cli_reason = cli_transport.is_available()
    if cli_available:
        return True, cli_reason
    return False, f"{sdk_reason}; Claude Code CLI: {cli_reason}"


def build_client(*, timeout: float = 120.0) -> anthropic.Anthropic:
    """A zero-arg `anthropic.Anthropic()` client, after confirming a credential is actually usable.

    Deliberately thin -- the SDK's own resolution order is trusted once :func:`_sdk_is_available` has
    already ruled out the one case (an empty `ANTHROPIC_API_KEY`) where that order silently produces
    a client that will fail on first use rather than one that simply is not there.

    **Checks `_sdk_is_available`, not the combined `is_available`.** `is_available()` returns `True`
    when *either* transport is usable, so on a machine with only the CLI it would say "available" while
    this function -- which only ever knows how to build the SDK client -- has nothing to build. Calling
    it here would raise a confusing SDK error (or, worse, silently authenticate with nothing) instead of
    the same one-line `AgentUnavailable` every other missing-credential path in this module produces.
    `call_structured` is the function that decides which transport to use; this one only ever builds
    the SDK half of that decision.
    """
    import anthropic

    available, reason = _sdk_is_available()
    if not available:
        raise AgentUnavailable(reason)
    return anthropic.Anthropic(timeout=timeout)


# ---------------------------------------------------------------------------
# Cost accounting -- an aid for the budget cap, never a billing figure
# ---------------------------------------------------------------------------

#: `{model: (input $/1M tokens, output $/1M tokens)}`. Anthropic's published first-party API rates
#: as of this package's writing. This table exists only to keep `AgentBudget.spent_usd` from running
#: past `AgentBudget.cap_usd` -- the authoritative number for what a run actually cost is always the
#: Anthropic console, never this dict, which is why `AgentCall.cost_usd` documents itself the same way.
_PRICE_TABLE_PER_MILLION: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5-20251001": (Decimal("1.00"), Decimal("5.00")),
}

#: A cache read bills at roughly a tenth of the input rate; a cache write (creation) at roughly
#: 1.25x it. Both are Anthropic's published multipliers, applied against the same model's input
#: price -- there is no separate "cache price" column in the table above.
_CACHE_READ_MULTIPLIER = Decimal("0.1")
_CACHE_CREATION_MULTIPLIER = Decimal("1.25")
_PER_MILLION = Decimal(1_000_000)
_MICRO_DOLLAR = Decimal("0.000001")


def estimate_cost_usd(model: str, usage: Any) -> Decimal:
    """`usage`'s tokens priced against :data:`_PRICE_TABLE_PER_MILLION`, in dollars.

    `usage` is duck-typed (an SDK `Usage` object, or anything else exposing the same four attributes,
    e.g. a `SimpleNamespace` in a test) rather than typed against `anthropic.types.Usage` -- this
    function has no reason to force an `anthropic` import on a caller that only wants to price a
    hypothetical usage figure. Missing attributes default to zero rather than raising, since a
    response that never touched the cache legitimately has no `cache_read_input_tokens`.

    An unknown `model` falls back to :data:`app.agents.models.DEFAULT_MODEL`'s pricing rather than
    raising -- this is an accounting aid for a budget cap, not a billing system, and a caller that
    passed a model this table has not been updated for still deserves a number in the right
    neighbourhood rather than a crash in the middle of an agent call.

    **This is not a billing figure.** It is priced from a table this package maintains by hand, and
    Anthropic's own console is the authoritative record of what a run actually cost -- see
    `app.agents.models.AgentCall.cost_usd`'s own docstring, which says the same thing for the same
    reason.
    """
    input_price, output_price = _PRICE_TABLE_PER_MILLION.get(
        model, _PRICE_TABLE_PER_MILLION[DEFAULT_MODEL]
    )
    input_tokens = Decimal(int(getattr(usage, "input_tokens", 0) or 0))
    output_tokens = Decimal(int(getattr(usage, "output_tokens", 0) or 0))
    cache_read_tokens = Decimal(int(getattr(usage, "cache_read_input_tokens", 0) or 0))
    cache_creation_tokens = Decimal(int(getattr(usage, "cache_creation_input_tokens", 0) or 0))

    cost = (
        input_tokens * input_price
        + output_tokens * output_price
        + cache_read_tokens * input_price * _CACHE_READ_MULTIPLIER
        + cache_creation_tokens * input_price * _CACHE_CREATION_MULTIPLIER
    ) / _PER_MILLION
    return cost.quantize(_MICRO_DOLLAR, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# The call itself
# ---------------------------------------------------------------------------


def _raw_response_text(response: Any) -> str:
    """The text this call's `AgentCall.raw_response` archives.

    Prefers the structured JSON the model actually returned (`response.parsed_output`, re-serialised)
    over the raw content blocks, because that JSON is what a caller downstream of `call_structured`
    acted on -- archiving anything else would let the audit record disagree with the decision it is
    supposed to explain. Falls back to any `text`-type content blocks when there is no parsed output
    (a refusal has none), so a refused call's archive still carries whatever the model said before
    declining, rather than an empty string with no explanation.
    """
    parsed = getattr(response, "parsed_output", None)
    if parsed is not None:
        return str(parsed.model_dump_json())
    blocks = getattr(response, "content", None) or []
    texts = [block.text for block in blocks if getattr(block, "type", None) == "text"]
    return "\n".join(texts)


def _archive_call(call: AgentCall, *, settings: Settings) -> None:
    """Write `call` to `agent_calls_dir(settings)/{call_id}.json`, one file per call.

    `app.agents.models`'s own module docstring is explicit that this archive is what replaces
    replayability for an agent-designed generation: a seeded generation can be re-run to the same
    bytes, this one cannot, so every input and output is kept instead. Overwrites nothing that
    already exists -- `call_id` is a fresh `uuid4` per call, never reused.
    """
    directory = agent_calls_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{call.call_id}.json"
    path.write_text(call.model_dump_json(indent=2) + "\n", encoding="utf-8")


def call_structured[T: BaseModel](
    *,
    role: AgentRole,
    system: str,
    user: str,
    output_format: type[T],
    model: str = DEFAULT_MODEL,
    settings: Settings,
    budget: AgentBudget,
    effort: str = "high",
) -> tuple[T, AgentCall, AgentBudget]:
    """One structured model call, fully accounted for: refused up front if the budget is already
    exhausted, archived in full regardless of outcome, and returned alongside the spend it cost.

    **Routes to whichever transport is usable, SDK first.** This function itself decides nothing about
    *how* the call happens -- it checks `_sdk_is_available()` and, if that is usable, delegates to
    `_call_via_sdk`; otherwise it checks `app.agents.cli_transport.is_available()` and delegates to
    `_call_via_cli`; otherwise it raises `AgentUnavailable` naming both reasons. The SDK is preferred
    whenever both exist because it is the lower-latency path (no subprocess spawn) -- see this module's
    own docstring and `is_available`'s for the same preference stated for the health check. Every
    caller (`designer.py`, `scout.py`, `reviewer.py`) keeps calling this one function; which transport
    actually ran is visible only in the archived `AgentCall.model` / the loop's log, never in this
    function's signature, so no caller needed to change to gain the fallback.

    **Caching placement is load-bearing, not stylistic, on the SDK path.** `system` is sent as a single
    cached text block (`cache_control: {"type": "ephemeral"}`) so the frozen designer/scout prompt is
    the stable prefix every call shares; everything that changes generation to generation -- findings,
    standings, the goal, the pool -- lives in `user`, entirely after the cache breakpoint. A caching
    prefix is invalidated by any byte change earlier in the request, so putting volatile content in
    `system` would silently defeat the cache on every single call. The CLI path has no `cache_control`
    flag to protect, but keeps `system` byte-identical for the same reason: `app.agents.cli_transport`'s
    own docstring explains why it appends its JSON-schema instructions to `user` rather than `system`.

    **Refusal is a normal outcome, not an exception, on both paths.** `stop_reason == "refusal"` arrives
    as HTTP 200 from the SDK; the CLI's envelope carries the same string. On the SDK path it is checked
    explicitly, after the call is archived (the archive is supposed to record what actually happened,
    refusal included) and before this function returns. On the CLI path `cli_transport.call_structured`
    itself raises before ever returning, so there is nothing to archive -- consistent with "every
    transport/auth failure becomes `AgentUnavailable`" below, since a CLI refusal is filtered out before
    this function gets far enough to build an `AgentCall` at all. Either way, a refusal is raised as
    `AgentUnavailable`, so a caller's `except AgentUnavailable` already covers it alongside every other
    degrade-to-deterministic-proposer path.

    **Every transport/auth failure becomes `AgentUnavailable`.** There is nothing to archive for a
    call that never produced a response (a bad API key, a network failure, a 400, a missing CLI binary,
    a non-zero CLI exit, a timeout): those raise without writing a call record -- the archive exists to
    explain a *decision*, and a call that never reached the model made none.
    """
    if budget.exhausted:
        raise BudgetExhausted(budget.spent_usd, budget.cap_usd)

    sdk_available, sdk_reason = _sdk_is_available()
    if sdk_available:
        return _call_via_sdk(
            role=role, system=system, user=user, output_format=output_format,
            model=model, settings=settings, budget=budget, effort=effort,
        )

    cli_available, cli_reason = cli_transport.is_available()
    if not cli_available:
        raise AgentUnavailable(f"{sdk_reason}; Claude Code CLI: {cli_reason}")

    return _call_via_cli(
        role=role, system=system, user=user, output_format=output_format,
        model=model, settings=settings, budget=budget, effort=effort,
    )


def _call_via_sdk[T: BaseModel](
    *,
    role: AgentRole,
    system: str,
    user: str,
    output_format: type[T],
    model: str,
    settings: Settings,
    budget: AgentBudget,
    effort: str,
) -> tuple[T, AgentCall, AgentBudget]:
    """The original `call_structured` body: one `messages.parse` call through the `anthropic` SDK.
    Split out of `call_structured` so that function could become a router between this and
    `_call_via_cli` without changing what either path itself does.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise AgentUnavailable("the `anthropic` package is not installed") from exc

    client = build_client()

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            # `cast` rather than a literal dict: the SDK types `output_config` as a TypedDict, and a
            # `dict[str, str]` built from the `effort` parameter does not narrow to it -- `effort` is
            # a plain `str` here on purpose, so a caller can pass a value this SDK version has not
            # heard of yet and get the API's own error rather than a local type error.
            output_config=cast("Any", {"effort": effort}),
            output_format=output_format,
        )
    except anthropic.AuthenticationError as exc:
        raise AgentUnavailable(f"authentication failed ({role}): {exc}") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AgentUnavailable(f"permission denied ({role}): {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise AgentUnavailable(f"rate limited ({role}): {exc}") from exc
    except anthropic.BadRequestError as exc:
        raise AgentUnavailable(f"bad request ({role}): {exc}") from exc
    except anthropic.APITimeoutError as exc:
        raise AgentUnavailable(f"request timed out ({role}): {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise AgentUnavailable(f"connection error ({role}): {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise AgentUnavailable(f"API error {exc.status_code} ({role}): {exc}") from exc

    usage = response.usage
    cost = estimate_cost_usd(model, usage)

    call = AgentCall(
        call_id=str(uuid.uuid4()),
        role=role,
        model=model,
        created_at=dt.datetime.now(dt.UTC),
        system=system,
        user=user,
        raw_response=_raw_response_text(response),
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_read_input_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        cache_creation_input_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        cost_usd=cost,
        request_id=getattr(response, "_request_id", None),
        stop_reason=response.stop_reason,
    )
    _archive_call(call, settings=settings)
    LEDGER.record(cost)

    new_budget = AgentBudget(
        cap_usd=budget.cap_usd,
        spent_usd=budget.spent_usd + cost,
        calls=budget.calls + 1,
    )

    if response.stop_reason == "refusal":
        stop_details = getattr(response, "stop_details", None)
        category = getattr(stop_details, "category", None) if stop_details is not None else None
        raise AgentUnavailable(f"model refused the {role} request (category={category!r})")

    parsed_output = response.parsed_output
    if parsed_output is None:
        # Not reachable through a successful `messages.parse` -- the SDK populates `parsed_output`
        # whenever `output_format` is set and the turn was not a refusal, which the check above has
        # already excluded. Raised rather than asserted so that a future SDK change turning this into
        # a real case degrades the loop to its deterministic proposer instead of raising an
        # `AssertionError` no caller is prepared to catch. `AgentResponseInvalid` (an
        # `AgentUnavailable` subclass) rather than the base so a grounded caller retries a response
        # that arrived but carried no parsed value, matching the CLI transport's own parse-failure path.
        raise AgentResponseInvalid(f"{role} response carried no parsed output")
    return parsed_output, call, new_budget


def _call_via_cli[T: BaseModel](
    *,
    role: AgentRole,
    system: str,
    user: str,
    output_format: type[T],
    model: str,
    settings: Settings,
    budget: AgentBudget,
    effort: str,
) -> tuple[T, AgentCall, AgentBudget]:
    """The CLI half of `call_structured`: hands the call to
    `app.agents.cli_transport.call_structured`, then builds and archives the `AgentCall` record the
    same way `_call_via_sdk` does, so a CLI call is auditable exactly like an SDK call and
    indistinguishable to `_archive_call` and everything downstream of it.

    `cli_transport.call_structured` raises `AgentUnavailable` for every failure mode itself (missing
    binary, spawn failure, non-zero exit, `is_error`, a refusal, an unparseable or schema-invalid
    response) before ever returning, so by the time this function has a `CliCallResult` in hand the
    call already succeeded -- there is no failure branch left to handle here, only the record to build.

    `budget.remaining_usd` is passed as `cli_transport.call_structured`'s `max_budget_usd`, a second,
    process-level ceiling underneath the one `AgentBudget` this function's caller already enforces via
    the `budget.exhausted` check at the top of `call_structured` -- see `cli_transport`'s own docstring
    on why `--max-budget-usd` is worth passing at all when `AgentBudget` already gates the call.
    """
    result = cli_transport.call_structured(
        role=role,
        system=system,
        user=user,
        output_format=output_format,
        model=model,
        max_budget_usd=budget.remaining_usd,
        effort=effort,
    )

    # A shim carrying only the two attributes `_raw_response_text` actually reads, so the CLI path
    # archives its response the identical way the SDK path does -- preferring the parsed JSON,
    # reserialised, over any raw text -- rather than duplicating that preference here.
    shim_response = SimpleNamespace(parsed_output=result.parsed_output, content=())

    call = AgentCall(
        call_id=str(uuid.uuid4()),
        role=role,
        model=model,
        created_at=dt.datetime.now(dt.UTC),
        system=system,
        user=user,
        raw_response=_raw_response_text(shim_response),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read_input_tokens=result.cache_read_input_tokens,
        cache_creation_input_tokens=result.cache_creation_input_tokens,
        cost_usd=result.cost_usd,
        request_id=result.request_id,
        stop_reason=result.stop_reason,
    )
    _archive_call(call, settings=settings)
    LEDGER.record(result.cost_usd)

    new_budget = AgentBudget(
        cap_usd=budget.cap_usd,
        spent_usd=budget.spent_usd + result.cost_usd,
        calls=budget.calls + 1,
    )
    return result.parsed_output, call, new_budget
