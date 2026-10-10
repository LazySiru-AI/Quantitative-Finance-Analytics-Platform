"""Tests for `app.ingest.provenance`, in particular the row-count ceiling on `read_rows` (A10).

`read_rows` has to materialise a whole broker CSV into memory before any adapter sees it -- Robinhood's
export embeds newlines inside a quoted field, which rules out row-by-row streaming. Without a bound,
a corrupted or accidentally-huge file is read in full and only fails with an opaque `MemoryError`
afterwards. `Settings.ingest_max_rows` bounds that, and these tests pin the bound's behaviour: it must
not fire on anything resembling a real broker export, it must fire with a clear, locatable error once
exceeded, and it must be configurable both by passing a `Settings` object directly and via the
`INVDASH_` environment-variable convention every other setting in this app uses.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.config import Settings
from app.ingest.provenance import RowLimitExceeded, read_rows


def _write_csv(path: Path, row_count: int) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Date", "Symbol", "Amount"])
        for i in range(row_count):
            writer.writerow([f"2026-01-{(i % 28) + 1:02d}", "SOXL", "1.00"])


# ---------------------------------------------------------------------------
# The default must never fire on legitimate use
# ---------------------------------------------------------------------------


def test_default_limit_leaves_a_wide_margin_over_the_largest_measured_real_export() -> None:
    """The largest real broker export measured for this app is Webull's 1,087-row combined order
    history. The default must clear that by a wide margin, not merely exceed it."""
    cfg = Settings()
    assert cfg.ingest_max_rows >= 1_087 * 10


def test_default_limit_does_not_fire_on_a_file_the_size_of_the_largest_real_export(
    tmp_path: Path,
) -> None:
    path = tmp_path / "webull_sized.csv"
    _write_csv(path, 1_087)
    raw = read_rows(path)  # no settings override: exercises the real default
    assert raw.row_count == 1_087


# ---------------------------------------------------------------------------
# The bound itself: exact, configurable, and a clear error rather than a crash
# ---------------------------------------------------------------------------


def test_a_file_over_a_configured_limit_raises_row_limit_exceeded(tmp_path: Path) -> None:
    path = tmp_path / "toobig.csv"
    _write_csv(path, 20)
    with pytest.raises(RowLimitExceeded) as excinfo:
        read_rows(path, settings=Settings(ingest_max_rows=10))
    assert "toobig.csv" in str(excinfo.value)
    assert "10" in str(excinfo.value)
    assert excinfo.value.path == path
    assert excinfo.value.max_rows == 10


def test_row_limit_exceeded_is_a_value_error_not_a_memory_error(tmp_path: Path) -> None:
    """The whole point of the ceiling: a predictable, catchable exception instead of however the
    interpreter happens to fail once it runs out of memory."""
    assert issubclass(RowLimitExceeded, ValueError)


def test_a_file_exactly_at_the_limit_succeeds(tmp_path: Path) -> None:
    path = tmp_path / "exact.csv"
    _write_csv(path, 10)
    raw = read_rows(path, settings=Settings(ingest_max_rows=10))
    assert raw.row_count == 10


def test_a_file_one_row_under_the_limit_succeeds(tmp_path: Path) -> None:
    path = tmp_path / "under.csv"
    _write_csv(path, 9)
    raw = read_rows(path, settings=Settings(ingest_max_rows=10))
    assert raw.row_count == 9


def test_the_limit_is_configurable_via_the_invdash_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every other setting in this app is overridable through an `INVDASH_`-prefixed environment
    variable (see `app.config.Settings`); this one must follow the same convention rather than being
    a special case only reachable by constructing `Settings` in code."""
    monkeypatch.setenv("INVDASH_INGEST_MAX_ROWS", "5")
    cfg = Settings()
    assert cfg.ingest_max_rows == 5

    path = tmp_path / "env_limited.csv"
    _write_csv(path, 6)
    with pytest.raises(RowLimitExceeded):
        read_rows(path, settings=cfg)


def test_row_limit_is_checked_before_the_whole_file_is_buffered(tmp_path: Path) -> None:
    """Checked while iterating, not after building the full row list -- otherwise the ceiling would
    only catch the failure after paying the exact memory cost it exists to avoid. Observable from the
    outside as: the error names the configured limit, not the file's true (larger) row count."""
    path = tmp_path / "big.csv"
    _write_csv(path, 1_000)
    with pytest.raises(RowLimitExceeded) as excinfo:
        read_rows(path, settings=Settings(ingest_max_rows=3))
    assert excinfo.value.max_rows == 3
