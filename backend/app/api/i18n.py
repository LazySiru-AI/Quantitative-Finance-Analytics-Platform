"""HTTP surface for on-display narrative translation: `POST /api/i18n/translate`.

Thin over `app.i18n.narrative.translate_texts`, matching `app.api.tradingagents`'s own convention for
a router that is wiring only -- every real decision (the flag gate, the cache, the model call, the
number-preservation check) lives in that module. This router's job is the request/response shape and
nothing else.

**Never a 500 for a translation failure.** `translate_texts` already degrades every model/transport
failure to `None` per-text (see its own docstring); this router adds no additional try/except around
that call for those -- a `None` in the response is the documented outcome, not an error. The one
exception is `app.agents.spend.SpendCapExceeded`: that is not a per-text failure but a deliberate
refusal to spend further, so it is caught here and turned into `429`, the same shape
`app.agents.spend_http`'s handler gives the persona routes for the identical condition.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.agents.spend import SpendCapExceeded
from app.config import Settings, get_settings
from app.i18n.narrative import translate_texts

router = APIRouter(prefix="/api/i18n", tags=["i18n"])

SettingsDep = Annotated[Settings, Depends(get_settings)]

#: Per-request cap on how many texts one call will translate. Bounds a single request's worst-case
#: model spend and latency; a page rendering more narrative sentences than this in one go should
#: batch across multiple requests rather than raise the ceiling.
_MAX_TEXTS = 64

#: Per-text cap on how long one string in the batch may be. Bounds one request's worst-case model
#: spend and latency the other way from `_MAX_TEXTS`: a small number of very long strings can cost as
#: much as many short ones. No narrative sentence this app renders is anywhere near this long -- it
#: exists to bound a malformed or adversarial request, not to constrain a real caller.
_MAX_TEXT_LENGTH = 4000

_TranslatableText = Annotated[str, StringConstraints(max_length=_MAX_TEXT_LENGTH)]


class TranslateRequest(BaseModel):
    """`locale` is a closed `Literal` rather than a free string so an unsupported locale is a 422 from
    pydantic's own validation -- FastAPI's standard behaviour for a `Literal` field mismatch -- rather
    than something this router has to check by hand. Widen the `Literal` here, in one place, the day a
    second locale ships."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    locale: Literal["ko"]
    texts: list[_TranslatableText] = Field(max_length=_MAX_TEXTS)


class TranslateResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    results: list[str | None]


@router.post("/translate", response_model=TranslateResponse)
def translate(body: TranslateRequest, settings: SettingsDep) -> TranslateResponse | JSONResponse:
    """Translate `body.texts` to `body.locale`, returning one result per input text in the same
    order -- the Korean translation, or `null` wherever it was not translated (flag off, an empty or
    whitespace-only text, an LLM/transport failure, or a failed number-preservation check). Any
    `locale` other than `"ko"`, or more than `_MAX_TEXTS` texts, is already rejected as a 422 by
    `TranslateRequest`'s own field types before this function ever runs.

    Returns `429` (a plain `JSONResponse`, bypassing `response_model` -- `{"detail": "spend_cap",
    "spent_usd": ..., "cap_usd": ..., "retry_after_seconds": ...}`, matching
    `app.agents.spend_http.spend_cap_exceeded_handler`'s body for the persona routes) if the aggregate
    `Settings.model_spend_daily_cap_usd` ceiling is already reached -- see `translate_texts`'s own
    docstring for exactly when that check runs.
    """
    try:
        results = translate_texts(body.texts, locale=body.locale, settings=settings)
    except SpendCapExceeded as exc:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "spend_cap",
                "spent_usd": str(exc.spent_usd),
                "cap_usd": str(exc.cap_usd),
                "retry_after_seconds": exc.retry_after_seconds,
            },
        )
    return TranslateResponse(results=results)
