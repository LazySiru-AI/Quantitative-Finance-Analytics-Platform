"""Tests for `app.manager.snapshots` -- atomic per-day-per-scope persistence of `ManagerSnapshot`.

No model calls, no filesystem beyond `tmp_path` (via `Settings(data_dir=...)`), matching the rest of
this repo's store tests (see `TestRunStore` in `tests/test_agentdesk_core.py`, which this module's
`save`/`load`/atomicity contract deliberately mirrors).
"""

from __future__ import annotations

import datetime as dt

from app.config import Settings
from app.manager import snapshots
from app.manager.models import ManagerSnapshot, Scope, SnapshotSection, snapshots_dir


def _snapshot(
    as_of: str, scope: Scope = "owner", *, sections: tuple[SnapshotSection, ...] = ()
) -> ManagerSnapshot:
    return ManagerSnapshot(
        scope=scope,
        as_of=as_of,
        generated_at=f"{as_of}T09:45:00+00:00",
        sections=sections,
        warnings=(),
    )


class TestSaveLoadRoundTrip:
    def test_round_trip_is_exact(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        snap = _snapshot(
            "2026-09-08",
            sections=(
                SnapshotSection(
                    key="account", ok=True, as_of="2026-09-08", text="3 positions",
                    figures={"total_market_value": "125000.00", "cash_balance": "500.00"},
                ),
            ),
        )

        path = snapshots.save(settings, snap)
        loaded = snapshots.load(settings, dt.date(2026, 9, 8), "owner")

        assert path.is_file()
        assert loaded == snap

    def test_save_writes_to_the_pinned_path(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        snap = _snapshot("2026-09-08")

        path = snapshots.save(settings, snap)

        assert path == snapshots_dir(settings) / "2026-09-08.owner.json"

    def test_save_is_atomic_no_partial_file_left_behind(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        snap = _snapshot("2026-09-08")

        snapshots.save(settings, snap)

        entries = sorted(p.name for p in snapshots_dir(settings).iterdir())
        assert entries == ["2026-09-08.owner.json"]


class TestLoad:
    def test_load_of_missing_date_returns_none(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        assert snapshots.load(settings, dt.date(2026, 1, 1), "owner") is None

    def test_load_of_corrupt_file_returns_none_not_raise(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        directory = snapshots_dir(settings)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "2026-01-01.owner.json").write_text("{not valid json", encoding="utf-8")

        assert snapshots.load(settings, dt.date(2026, 1, 1), "owner") is None

    def test_load_scopes_the_lookup_by_scope(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        snapshots.save(settings, _snapshot("2026-09-08", scope="owner"))

        assert snapshots.load(settings, dt.date(2026, 9, 8), "member") is None


class TestListDates:
    def test_list_dates_is_newest_first(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        for as_of in ("2026-09-01", "2026-09-08", "2026-09-03"):
            snapshots.save(settings, _snapshot(as_of))

        assert snapshots.list_dates(settings, "owner") == (
            dt.date(2026, 9, 8), dt.date(2026, 9, 3), dt.date(2026, 9, 1),
        )

    def test_list_dates_ignores_junk_filenames(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        snapshots.save(settings, _snapshot("2026-09-08"))
        directory = snapshots_dir(settings)
        (directory / "not-a-date.owner.json").write_text("{}", encoding="utf-8")
        (directory / "README.md").write_text("junk", encoding="utf-8")

        assert snapshots.list_dates(settings, "owner") == (dt.date(2026, 9, 8),)

    def test_list_dates_scopes_by_scope(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        snapshots.save(settings, _snapshot("2026-09-08", scope="owner"))
        snapshots.save(settings, _snapshot("2026-09-07", scope="member"))

        assert snapshots.list_dates(settings, "owner") == (dt.date(2026, 9, 8),)
        assert snapshots.list_dates(settings, "member") == (dt.date(2026, 9, 7),)

    def test_list_dates_of_empty_directory_is_empty(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        assert snapshots.list_dates(settings, "owner") == ()


class TestLatest:
    def test_latest_with_no_before_is_the_newest(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        for as_of in ("2026-09-01", "2026-09-08", "2026-09-05"):
            snapshots.save(settings, _snapshot(as_of))

        found = snapshots.latest(settings, "owner")

        assert found is not None
        assert found.as_of == "2026-09-08"

    def test_latest_before_picks_the_nearest_strictly_prior_date(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        # Not every calendar day has a snapshot -- "yesterday" must land on the nearest one, not
        # literally T-1.
        for as_of in ("2026-09-01", "2026-09-05", "2026-09-08"):
            snapshots.save(settings, _snapshot(as_of))

        found = snapshots.latest(settings, "owner", before=dt.date(2026, 9, 8))

        assert found is not None
        assert found.as_of == "2026-09-05"

    def test_latest_before_the_earliest_date_is_none(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        snapshots.save(settings, _snapshot("2026-09-08"))

        assert snapshots.latest(settings, "owner", before=dt.date(2026, 9, 1)) is None

    def test_latest_of_empty_scope_is_none(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        assert snapshots.latest(settings, "owner") is None

    def test_latest_skips_a_corrupt_newest_file_for_the_next_readable_one(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        snapshots.save(settings, _snapshot("2026-09-05"))
        directory = snapshots_dir(settings)
        (directory / "2026-09-08.owner.json").write_text("{not valid json", encoding="utf-8")

        found = snapshots.latest(settings, "owner")

        assert found is not None
        assert found.as_of == "2026-09-05"
