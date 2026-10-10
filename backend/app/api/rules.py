"""Rule catalog, decision table and expression validation endpoints.

Thin on purpose, matching `app.api.macro` more than `app.api.market`: almost every failure this
router could translate into an HTTP status has already been absorbed one layer down, in
`app.rules.service.build_decision_table` (a bad rule becomes a degraded row, not an exception; a
symbol with nothing synced yet becomes an empty table with a warning, not a 500). The one genuine
error condition left at this boundary is the same one `app.api.market` and `app.api.macro` already
handle: a confirmed-missing symbol or every provider down with nothing already stored, which
`app.market.store.ensure_series` raises as a `~app.market.providers.base.ProviderError` and this
router maps to a status the caller can act on.

`/validate` is the one endpoint that is not a thin wrapper over a service function -- see its own
docstring for why its logic sits here rather than in `app.rules.service`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db.duck import Interval
from app.indicators import registry
from app.indicators.base import IndicatorError
from app.market.providers.base import ProviderError, ProviderUnavailable, SymbolNotFound
from app.market.registry import ProviderRegistry, default_registry
from app.rules import catalog as catalog_module
from app.rules import service
from app.rules.models import DecisionTable, Rule

router = APIRouter(prefix="/api/rules", tags=["rules"])

#: Same closed alphabet as `app.api.market.SymbolParam`, duplicated rather than imported -- matching
#: `app.api.macro.SeriesIdPath`'s own choice to duplicate instead of couple this router's
#: importability to `market.py`'s. A symbol reaches the filesystem as a Parquet partition directory
#: name one layer down in `app.market.store`, so the accepted alphabet is fixed here rather than
#: sanitised downstream.
SymbolParam = Annotated[str, Query(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-^=]+$")]

#: Generous headroom over the longest catalog expression (`bb_squeeze`, well under 80 characters)
#: while still refusing anything shaped like an attempt to make the parser do real work -- `/validate`
#: is called from an editor on every keystroke and must stay cheap regardless of what is typed.
_MAX_EXPRESSION_LENGTH = 500


# ---------------------------------------------------------------------------
# Wire shapes that exist only at this boundary
# ---------------------------------------------------------------------------


class ValidateRequest(BaseModel):
    """The `/validate` request body.

    No `min_length`: an empty string is a normal thing to type into an empty editor and must reach
    `grammar.parse` to come back as `valid: false`, not be rejected as a malformed *request* -- see
    the module and endpoint docstrings for the 200-vs-4xx distinction this turns on.
    """

    expression: str = Field(max_length=_MAX_EXPRESSION_LENGTH)


class RuleValidation(BaseModel):
    """Result of checking a rule expression without running it against data.

    Mirrors `frontend/src/api/rules.ts`'s `RuleValidation` field for field.
    """

    valid: bool
    error: str | None = None
    normalized: str | None = None
    indicators: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry() -> ProviderRegistry:
    """One registry per request -- see `app.api.market._registry` for why not a module singleton."""
    return default_registry()


def _handle(exc: ProviderError) -> HTTPException:
    """The same status mapping as `app.api.market._handle` and `app.api.macro._handle`.

    Duplicated rather than imported for the reason `app.api.macro` gives for its own copy: this is a
    two-line contract, cheaper to repeat than to make this router's importability depend on
    `market.py`'s.
    """
    if isinstance(exc, SymbolNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ProviderUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _grammar() -> service.Grammar:
    """The real `app.rules.grammar` module, imported lazily -- see `app.rules.service._default_grammar`
    for why this stays a function rather than a module-level import: it lets this router import
    cleanly even before `grammar.py` exists elsewhere in this phase. A separate indirection from
    `service`'s own default so `/validate` -- which never touches `service.build_decision_table` --
    does not have to construct a full decision-table call just to parse one expression."""
    from app.rules import grammar

    return grammar


def _evaluator() -> service.Evaluator:
    """The real `app.rules.evaluate` module for `/validate`'s `required_specs` call. See `_grammar`."""
    from app.rules import evaluate

    return evaluate


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@router.get("/catalog", response_model=list[Rule])
def catalog() -> list[Rule]:
    """The curated rule catalog, independent of any symbol -- see `app.rules.catalog.catalog`."""
    return catalog_module.catalog()


# ---------------------------------------------------------------------------
# Decision table
# ---------------------------------------------------------------------------


@router.get("/decisions", response_model=DecisionTable)
def decisions(symbol: SymbolParam, interval: Interval = Interval.DAY) -> DecisionTable:
    """The whole catalog, evaluated for one symbol and interval.

    See `app.rules.service.build_decision_table`'s docstring for why a bad rule or a symbol with no
    stored bars never reach this function as an exception -- both are absorbed into the table. The
    one thing that does reach here is a `ProviderError` from the store: a confirmed-missing symbol
    (404) or every provider unavailable with nothing already stored (503), mapped the same way
    `app.api.market` and `app.api.macro` map it. A malformed `interval` value never reaches this
    function's body at all -- FastAPI rejects it against the `Interval` enum before the handler runs,
    which is what makes it a 4xx rather than a 500 here.
    """
    try:
        return service.build_decision_table(
            get_settings(), symbol.upper(), interval, registry=_registry()
        )
    except ProviderError as exc:
        raise _handle(exc) from exc


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@router.post("/validate", response_model=RuleValidation)
def validate(request: ValidateRequest) -> RuleValidation:
    """Check one expression without evaluating it against any bars.

    Called from the rule editor on every keystroke, so it must be cheap and must never touch the bar
    store or the network -- it parses, renders the tree back to its canonical text, and collects the
    indicator specs the tree would need, nothing else. Kept as router-local logic rather than a
    `service.py` function for exactly that reason: `build_decision_table` always reads bars, and
    routing this through it (even with an empty rule list) would tie a cheap, keystroke-frequency
    call to the market-data path this endpoint's whole job is to avoid.

    A malformed *expression* is not a client error -- the editor is asking "is this valid yet?", and
    "no, here is why" is a successful answer to that question, so this always returns ``200`` with
    ``valid: false`` and the parser's message in ``error``. The one thing that *is* a 4xx here is a
    malformed *request* -- a missing `expression` field, or one over `_MAX_EXPRESSION_LENGTH` -- and
    that is enforced by `ValidateRequest`'s own `Field` constraint before this function body runs.
    """
    grammar = _grammar()
    try:
        node = grammar.parse(request.expression)
    except ValueError as exc:
        return RuleValidation(valid=False, error=str(exc), normalized=None, indicators=[])

    normalized = grammar.render(node)
    try:
        indicators = _evaluator().required_specs(node)
    except ValueError as exc:
        # `required_specs` does not validate against the indicator registry (see its own docstring),
        # so this is not expected to fail on a tree that just parsed -- handled the same as a parse
        # failure regardless, rather than letting an unexpected exception become a 500 on a keystroke.
        return RuleValidation(valid=False, error=str(exc), normalized=normalized, indicators=[])

    # Parsing is not validity. `required_specs` deliberately does not check the registry (its own
    # docstring says so), so `rsi(14, 5)` and `sma(9999)` both parse cleanly and were both reported
    # VALID -- while `parse_spec` rejects the first for arity and the second for range the moment the
    # rule actually runs. A validator that says VALID for an expression the engine will refuse is
    # worse than no validator: a UAT persona built on those green checkmarks and only found out at
    # evaluation.
    #
    # Checking here is still cheap. This endpoint's "must not be expensive" rule is about the *bar
    # store* and the network -- see this function's docstring -- and `registry.request` is an
    # in-memory lookup against the spec table with no bars, no interval and no I/O.
    for spec in indicators:
        try:
            registry.request(spec)
        except (IndicatorError, ValueError) as exc:
            return RuleValidation(
                valid=False, error=str(exc), normalized=normalized, indicators=indicators
            )

    return RuleValidation(valid=True, error=None, normalized=normalized, indicators=indicators)
