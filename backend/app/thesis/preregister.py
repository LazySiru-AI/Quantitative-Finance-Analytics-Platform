"""Guard 1: a thesis is content-hashed and frozen before any backtest runs.

The failure this prevents is not dishonesty, it is drift. Someone writes a thesis, runs it, sees an
edge at 20 bars rather than the 5 they predicted, changes the horizon, and reports the result. Every
step feels reasonable. What has happened is two tests reported as one, with the winner selected after
the fact -- and nothing in the output records that the first test existed.

So the hash covers **everything that makes the claim what it is**: the hypothesis wording, the entry
and exit rules, the holding cap, the stop, the horizon, the predicted direction, and the falsification
criterion. Change any of them and :func:`content_hash` returns something different, which is a
different :class:`~app.thesis.models.ThesisRecord`, which is another trial in the ledger. There is no
edit path. That is the mechanism, and it is the whole of it.

**The rationale is deliberately excluded from the hash.** It records *why* a thesis was proposed and
carries no claim, so rewording it does not make a new hypothesis -- and hashing it would let a
cosmetic edit silently consume a trial, which trains people to leave it blank. Everything that is a
claim is hashed; the one field that is commentary is not.

**Hashing is canonical, not ``repr``-based.** Field order, float formatting and ``None`` all have to
serialise identically across processes and Python versions, or the same thesis registered twice would
occupy two ledger slots and inflate its own denominator. :func:`_canonical` pins that.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

from app.thesis.models import Thesis, ThesisRecord, ThesisStatus

__all__ = ["HASHED_FIELDS", "PreregistrationError", "content_hash", "register", "verify_unmodified"]

#: Exactly the fields that constitute the claim. Anything here changes the hash; anything not here
#: does not.
#:
#: Spelled out rather than derived from ``model_fields`` on purpose: a future field added to
#: :class:`~app.thesis.models.Thesis` must be a deliberate decision about whether it is part of the
#: claim, and deriving the list would silently answer "yes" for a field that is commentary or "no"
#: for one that is a claim, depending on which way the derivation was written.
HASHED_FIELDS: tuple[str, ...] = (
    "symbol",
    "interval",
    "hypothesis",
    "entry",
    "exit",
    "max_holding_bars",
    "stop_loss_pct",
    "horizon",
    "direction",
    "falsifies_if",
)


class PreregistrationError(RuntimeError):
    """A registered thesis was modified, or a result was joined to a hash that does not match it."""


def _canonical(thesis: Thesis) -> str:
    """The exact bytes hashed. Sorted keys, no whitespace, explicit ``None``.

    Floats go through ``repr`` rather than ``str`` so ``0.1`` round-trips to the same text on every
    platform -- a stop of ``0.1`` hashing differently from ``0.1`` read back out of JSON would make a
    thesis un-re-registerable and quietly double its trial count.
    """
    payload: dict[str, object] = {}
    for field in HASHED_FIELDS:
        value = getattr(thesis, field)
        if value is None:
            payload[field] = None
        elif isinstance(value, float):
            payload[field] = repr(value)
        elif isinstance(value, str):
            # Whitespace is normalised: a trailing newline in a hypothesis is a typo, not a new
            # claim, and treating it as one would charge a trial for pressing return.
            payload[field] = " ".join(value.split())
        else:
            payload[field] = str(value)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_hash(thesis: Thesis) -> str:
    """Stable identity for a claim. Same claim, same hash, on any machine at any time."""
    return hashlib.sha256(_canonical(thesis).encode("utf-8")).hexdigest()


def register(thesis: Thesis, *, at: dt.datetime | None = None) -> ThesisRecord:
    """Freeze a thesis into a record. **Call this before running anything.**

    Returns a record in :attr:`~app.thesis.models.ThesisStatus.REGISTERED` with no evidence attached.
    Registering is what makes the thesis count as a trial, and it happens first precisely so that a
    run which dies -- or a thesis whose author loses interest halfway -- still leaves its slot in the
    ledger. A loop that registered on *completion* would leave no trace of the attempts it abandoned,
    which is the invisible-denominator failure this package is built around.
    """
    return ThesisRecord(
        thesis_hash=content_hash(thesis),
        thesis=thesis,
        registered_at=at or dt.datetime.now(dt.UTC),
        status=ThesisStatus.REGISTERED,
    )


def verify_unmodified(record: ThesisRecord) -> None:
    """Raise if a record's thesis no longer hashes to the hash it is filed under.

    The tamper check. Nothing in normal operation should ever trip it -- :class:`Thesis` is frozen and
    the hash is computed once -- which is exactly why it is worth asserting at the boundary where
    results are attached: the failure it catches is one where a record has been rebuilt, deserialised
    from a modified store, or assembled by code that meant well.
    """
    actual = content_hash(record.thesis)
    if actual != record.thesis_hash:
        raise PreregistrationError(
            f"thesis content does not match its registration: filed under {record.thesis_hash[:12]} "
            f"but now hashes to {actual[:12]}. A thesis edited after registration is a new thesis "
            "and must be registered again as its own trial, not attached to this one's results."
        )
