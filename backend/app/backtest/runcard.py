"""Immutable per-run artifacts: what was asked, what data answered it, what came back.

:class:`~app.backtest.models.RunCard` is the shared shape; this module is the only place that
builds, stores, and retrieves one. The point is answering "why does this number differ from the one
I saw last month?" without guessing -- see the model's docstring for the full argument.

**``run_id`` is a content hash**, computed over ``kind``, the canonicalised ``params``, the
:func:`fingerprint` of the bars the study actually saw, and :func:`code_version <_code_version>`.
Two calls to :func:`make` with the same question against the same data produce the same id, which is
what makes it double as a cache key: the same study run twice is the same file, not two.

**Immutability is enforced at the write, not by convention.** :func:`write` refuses to replace an
existing ``run_id`` whose stored payload differs from the one being written, raising
:class:`RunCardConflict`. A hash collision between genuinely different content is exactly what that
check exists to catch -- silently overwriting would destroy the audit trail. Re-running the identical
study is a no-op success: the *content* is compared (kind, symbol, interval, params, both hashes,
code version, results), not the wall-clock ``created_at``, because comparing timestamps would turn
every legitimate re-run into a false conflict.

**Params must canonicalise.** ``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` are the same question and
hash identically: :func:`_canonical_json` sorts keys at every nesting level and uses a stable
separator. Types JSON has no literal for -- ``dt.date``, ``dt.datetime``, ``NaN``, ``inf`` -- are
given an explicit, reversible tag (``_encode``/``_decode``) rather than being flattened through
``default=str``, which would silently make a ``dt.date`` and the string that happens to look like it
hash the same.

**``data_fingerprint`` moves the moment the data does.** It covers symbol, interval, the first and
last session, the row count, and a hash of the whole ``close`` column, so a single corrected close
value anywhere in the history -- a corporate action, a backfill, a provider revision -- changes it
even though the question (``params_hash``) did not. That combination is otherwise indistinguishable
from a code bug; a run card makes it visible instead.

**Writes are atomic.** Same recipe as ``app.market.store._write_meta``: stage through a uniquely
uuid-suffixed temp file in the destination directory, then ``replace`` it into place, guarded by a
lock keyed on the destination path. The uuid alone is not sufficient on Windows -- concurrent
``Path.replace`` calls onto the *same destination* race with ``PermissionError`` regardless of how
unique the staging name is -- so both fixes from that module apply here for the same reason.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import pandas as pd
from pydantic import ValidationError

from app.backtest.models import RunCard
from app.config import REPO_ROOT, Settings, get_settings
from app.db.duck import Interval

__all__ = [
    "RunCardConflict",
    "RunCardCorrupt",
    "RunCardError",
    "RunCardNotFound",
    "fingerprint",
    "make",
    "read",
    "recent",
    "write",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RunCardError(Exception):
    """Base for every error this module raises. Never `KeyError`/`FileNotFoundError` leaking out of
    `read` or `write` -- a caller catching run-card failures should not also have to catch generic
    filesystem and parsing errors that mean something different everywhere else in the app."""


class RunCardConflict(RunCardError):
    """`write` was asked to store a `run_id` that already exists on disk under different content.

    Since `run_id` is a content hash, this is a hash collision between two different studies (or, far
    more commonly, a hand-edited/corrupted file sharing an id it should not). Either way, overwriting
    it would destroy the audit trail the module exists to keep, so `write` refuses instead.
    """


class RunCardNotFound(RunCardError):
    """`read` was asked for a `run_id` with no stored card."""


class RunCardCorrupt(RunCardError):
    """A stored run card could not be parsed or validated. Names the offending file -- a half-written
    JSON file that chokes a bare `json.loads` is a worse failure than a clear error pointing at it."""


# ---------------------------------------------------------------------------
# Canonical, reversible encoding for `params` and `results`
# ---------------------------------------------------------------------------

#: Tag keys used to round-trip values plain JSON has no literal for. Each is a single-key dict that
#: cannot be produced by encoding an ordinary mapping the caller supplied, because every ordinary key
#: from `params`/`results` is coerced to `str` and none of these collide with the JSON reserved
#: tokens; `_decode` only recognises them when they are the dict's *only* key.
_DATE_TAG: Final = "__date__"
_DATETIME_TAG: Final = "__datetime__"
_FLOAT_TAG: Final = "__float__"


def _encode(value: object) -> object:
    """Recursively convert a `params`/`results` value into a structure `json.dumps` accepts, tagging
    the types plain JSON cannot represent so `_decode` can invert exactly.

    `bool`/`int`/`str`/`None` pass through untouched -- `str` also covers a `StrEnum` member, which
    `json.dumps` already serialises correctly as its plain value with no help needed. Finite `float`
    passes through too; `NaN`/`inf`/`-inf` do not survive a standard JSON round trip so they get the
    same explicit tag treatment as dates rather than becoming non-standard bare tokens.
    """
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {_FLOAT_TAG: "nan"}
        if math.isinf(value):
            return {_FLOAT_TAG: "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, dt.datetime):
        return {_DATETIME_TAG: value.isoformat()}
    if isinstance(value, dt.date):
        return {_DATE_TAG: value.isoformat()}
    if isinstance(value, Mapping):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_encode(v) for v in value]
    raise TypeError(
        f"cannot store a run card value of type {type(value).__name__}: {value!r} -- params and "
        "results must be built from dicts, lists/tuples, str, bool, int, float, None, dt.date and "
        "dt.datetime"
    )


def _decode(value: object) -> object:
    """Invert `_encode`, reconstructing `dt.date`/`dt.datetime`/non-finite `float` from their tags."""
    if isinstance(value, dict):
        if value.keys() == {_DATE_TAG}:
            raw = value[_DATE_TAG]
            assert isinstance(raw, str)
            return dt.date.fromisoformat(raw)
        if value.keys() == {_DATETIME_TAG}:
            raw = value[_DATETIME_TAG]
            assert isinstance(raw, str)
            return dt.datetime.fromisoformat(raw)
        if value.keys() == {_FLOAT_TAG}:
            token = value[_FLOAT_TAG]
            if token == "nan":
                return math.nan
            if token == "inf":
                return math.inf
            if token == "-inf":
                return -math.inf
            raise ValueError(f"unrecognised float tag payload: {token!r}")
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _canonical_json(value: object) -> str:
    """Deterministic JSON text for `value`: sorted keys at every level, stable separators, and the
    tagged encoding from `_encode` so two structurally-equal-but-differently-typed inputs (a `dt.date`
    versus the string that looks like it) can never collide."""
    return json.dumps(_encode(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------


def _sha256_hex(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(bars: pd.DataFrame, *, symbol: str, interval: Interval) -> str:
    """Identify the exact bars a study saw: symbol, interval, first/last session, row count, and a
    hash of the whole `close` column.

    Two cards with the same `params_hash` and a different fingerprint saw different data under an
    unchanged question -- a corporate action, a backfill, a provider revision -- which this exists to
    make visible rather than leave indistinguishable from a code bug. A single changed close value
    anywhere in the middle of the history changes the close-column hash and therefore this value,
    regardless of row count or date range staying the same.
    """
    if bars.empty or "close" not in bars.columns:
        first_session = ""
        last_session = ""
        row_count = 0
        close_hash = _sha256_hex("")
    else:
        ts = bars["ts"]
        if ts.dt.tz is not None:
            ts = ts.dt.tz_convert("UTC")
        dates = ts.dt.date
        first_session = dates.iloc[0].isoformat()
        last_session = dates.iloc[-1].isoformat()
        row_count = len(bars)
        closes = bars["close"].astype("float64").to_numpy()
        close_hash = _sha256_hex(closes.tobytes().hex())

    payload: dict[str, object] = {
        "symbol": symbol.upper(),
        "interval": interval.value,
        "first_session": first_session,
        "last_session": last_session,
        "row_count": row_count,
        "close_hash": close_hash,
    }
    return _sha256_hex(_canonical_json(payload))


def _params_hash(params: Mapping[str, object]) -> str:
    return _sha256_hex(_canonical_json(dict(params)))


def _code_version() -> str:
    """The checked-out git revision, or `"unknown"` if it cannot be resolved.

    Never fabricates a placeholder that would make two different builds look identical -- an
    unresolvable version is reported as such, not silently coerced into something that hashes the
    same as a real one. Resolved against the actual repository root (`app.config.REPO_ROOT`, the
    module-level constant), not a `Settings.repo_root` a test may have redirected into a temp
    directory: code version describes the code, which does not move when the data directory does.
    Bounded by an explicit timeout and every failure mode -- git absent, not a checkout, timing out --
    is swallowed rather than propagated, because a study should not fail to run for want of `git`.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    revision = result.stdout.strip()
    return revision if revision else "unknown"


def _run_id(kind: str, params_hash: str, data_fingerprint: str, code_version: str) -> str:
    payload: dict[str, object] = {
        "kind": kind,
        "params_hash": params_hash,
        "data_fingerprint": data_fingerprint,
        "code_version": code_version,
    }
    return _sha256_hex(_canonical_json(payload))


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def make(
    kind: str,
    *,
    symbol: str,
    interval: Interval,
    params: Mapping[str, object],
    bars: pd.DataFrame,
    results: Mapping[str, object],
) -> RunCard:
    """Build a `RunCard` for one study. Does not write it -- see `write`.

    `params` is stored with sorted top-level keys, matching the model's documented "canonicalised, no
    defaults elided" contract; `params_hash` is taken over the fully canonical (all-levels-sorted,
    type-tagged) encoding regardless of the caller's own key order, so two calls that differ only in
    dict-literal order hash identically.
    """
    resolved_params_hash = _params_hash(params)
    resolved_fingerprint = fingerprint(bars, symbol=symbol, interval=interval)
    resolved_code_version = _code_version()
    run_id = _run_id(kind, resolved_params_hash, resolved_fingerprint, resolved_code_version)

    return RunCard(
        run_id=run_id,
        kind=kind,
        created_at=dt.datetime.now(dt.UTC),
        symbol=symbol,
        interval=interval,
        params=dict(sorted(params.items())),
        params_hash=resolved_params_hash,
        data_fingerprint=resolved_fingerprint,
        code_version=resolved_code_version,
        results=dict(results),
    )


# ---------------------------------------------------------------------------
# Storage layout
# ---------------------------------------------------------------------------


def _runs_dir(settings: Settings) -> Path:
    """Where run cards live: `<store_dir>/runs/`, alongside the other derived, rebuildable stores
    (`bars/`, the DuckDB analytics file) rather than under `data_dir` -- a run card is computed from
    the bar store and the ledger, never a raw broker export, so it belongs with the other derived
    artifacts `Settings` already documents as disposable-but-useful, not with the real financial
    records `data_dir` holds.
    """
    return settings.store_dir / "runs"


def _run_path(settings: Settings, run_id: str) -> Path:
    return _runs_dir(settings) / f"{run_id}.json"


def _serialize(card: RunCard) -> str:
    payload: dict[str, object] = {
        "run_id": card.run_id,
        "kind": card.kind,
        "created_at": card.created_at.isoformat(),
        "symbol": card.symbol,
        "interval": card.interval.value,
        "params": _encode(card.params),
        "params_hash": card.params_hash,
        "data_fingerprint": card.data_fingerprint,
        "code_version": card.code_version,
        "results": _encode(card.results),
    }
    # Sorted, indented: the stored file is meant to be diffable by a human comparing two runs, not
    # just machine-readable -- see the module docstring.
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def _require[T](raw: dict[Any, Any], key: str, kind: type[T], *, path: Path) -> T:
    """Fetch ``key`` and check its JSON type, raising :class:`RunCardCorrupt` naming the file.

    Deliberately not ``assert isinstance(...)``: ``python -O`` strips assert statements, so a run of
    the app under optimisation would let a malformed or hand-edited card through the validation and
    into a ``RunCard`` -- which is exactly the audit trail this module exists to keep trustworthy.
    """
    if key not in raw:
        raise RunCardCorrupt(f"run card at {path} is missing {key!r}")
    value = raw[key]
    if not isinstance(value, kind):
        raise RunCardCorrupt(
            f"run card at {path}: {key!r} is {type(value).__name__}, expected {kind.__name__}"
        )
    return value


def _deserialize(text: str, *, path: Path) -> RunCard:
    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RunCardCorrupt(f"run card at {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise RunCardCorrupt(f"run card at {path} does not contain a JSON object at its root")

    try:
        interval_raw = _require(raw, "interval", str, path=path)
        params_raw = _require(raw, "params", dict, path=path)
        results_raw = _require(raw, "results", dict, path=path)
        decoded_params = _decode(params_raw)
        decoded_results = _decode(results_raw)
        if not isinstance(decoded_params, dict) or not isinstance(decoded_results, dict):
            raise RunCardCorrupt(f"run card at {path}: params/results did not decode to objects")
        return RunCard(
            run_id=_require(raw, "run_id", str, path=path),
            kind=_require(raw, "kind", str, path=path),
            created_at=dt.datetime.fromisoformat(_require(raw, "created_at", str, path=path)),
            symbol=_require(raw, "symbol", str, path=path),
            interval=Interval(interval_raw),
            params=decoded_params,
            params_hash=_require(raw, "params_hash", str, path=path),
            data_fingerprint=_require(raw, "data_fingerprint", str, path=path),
            code_version=_require(raw, "code_version", str, path=path),
            results=decoded_results,
        )
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        raise RunCardCorrupt(f"run card at {path} is malformed: {exc}") from exc


def _identity_payload(card: RunCard) -> dict[str, object]:
    """The fields that decide whether two cards sharing a `run_id` are "the same content" for
    `write`'s immutability check.

    `created_at` is deliberately excluded: `run_id` does not cover it (see the module docstring), so
    two honest calls to `make` for the identical study one minute apart produce cards that differ only
    in `created_at` and must both be treated as the same run, not a conflict. `run_id` itself is
    excluded too -- it is already equal by construction whenever this comparison runs.
    """
    return {
        "kind": card.kind,
        "symbol": card.symbol,
        "interval": card.interval.value,
        "params": _encode(card.params),
        "params_hash": card.params_hash,
        "data_fingerprint": card.data_fingerprint,
        "code_version": card.code_version,
        "results": _encode(card.results),
    }


# ---------------------------------------------------------------------------
# Write (atomic, immutable)
# ---------------------------------------------------------------------------

#: One lock per run-card path, exactly `app.market.store._META_WRITE_LOCKS` and
#: `app.db.duck._WRITE_LOCKS` one layer down -- see the module docstring for why a uuid-suffixed
#: staging name alone does not stop two concurrent writers from racing `PermissionError` on Windows
#: when `Path.replace` targets the same destination.
_WRITE_LOCKS: dict[Path, threading.Lock] = {}
_LOCK_REGISTRY = threading.Lock()


def _write_lock(path: Path) -> threading.Lock:
    with _LOCK_REGISTRY:
        return _WRITE_LOCKS.setdefault(path, threading.Lock())


def write(card: RunCard, *, settings: Settings | None = None) -> Path:
    """Store `card` under `<store_dir>/runs/<run_id>.json`, atomically.

    Re-writing the same `run_id` with byte-for-byte-equivalent content (see `_identity_payload`) is a
    silent no-op success, so re-running the same study never errors. Writing a different payload under
    an existing `run_id` raises `RunCardConflict` instead of overwriting it -- see the module
    docstring for why that is the check that matters most here.
    """
    cfg = settings or get_settings()
    runs_dir = _runs_dir(cfg)
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = _run_path(cfg, card.run_id)

    with _write_lock(path):
        if path.exists():
            try:
                existing = _deserialize(path.read_text(encoding="utf-8"), path=path)
            except (RunCardCorrupt, OSError) as exc:
                raise RunCardConflict(
                    f"run_id {card.run_id!r} already has a stored card at {path} that could not be "
                    f"read for comparison ({exc}); refusing to overwrite a run card that might differ"
                ) from exc
            if _identity_payload(existing) == _identity_payload(card):
                return path  # same question, same answer -- re-running is a no-op, not a conflict
            raise RunCardConflict(
                f"run_id {card.run_id!r} already exists at {path} with different content -- this is "
                "a hash collision between two different studies, and overwriting it would destroy "
                "the audit trail this module exists to keep"
            )

        payload = _serialize(card)
        staging = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            staging.write_text(payload, encoding="utf-8")
            staging.replace(path)
        finally:
            staging.unlink(missing_ok=True)
    return path


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def read(run_id: str, *, settings: Settings | None = None) -> RunCard:
    """Load the run card stored under `run_id`.

    Raises `RunCardNotFound` for an unknown id and `RunCardCorrupt` -- naming the file -- for one that
    exists but cannot be parsed, rather than letting `FileNotFoundError`/`JSONDecodeError` leak out.
    """
    cfg = settings or get_settings()
    path = _run_path(cfg, run_id)
    if not path.exists():
        raise RunCardNotFound(f"no run card found for run_id {run_id!r} (looked in {path})")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunCardCorrupt(f"could not read run card at {path}: {exc}") from exc
    return _deserialize(text, path=path)


def recent(*, limit: int = 50, settings: Settings | None = None) -> list[RunCard]:
    """The most recently created run cards, newest first.

    A run card that cannot be read or parsed is skipped rather than failing the whole listing -- one
    corrupted file should not make every other stored run invisible; `read` is the place a caller
    finds out precisely what is wrong with a specific one.
    """
    cfg = settings or get_settings()
    runs_dir = _runs_dir(cfg)
    if not runs_dir.exists():
        return []

    cards: list[RunCard] = []
    for path in runs_dir.glob("*.json"):
        try:
            cards.append(_deserialize(path.read_text(encoding="utf-8"), path=path))
        except (RunCardCorrupt, OSError):
            continue

    cards.sort(key=lambda c: (c.created_at, c.run_id), reverse=True)
    return cards[:limit]
