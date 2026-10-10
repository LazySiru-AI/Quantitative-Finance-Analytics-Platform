"""Regression tests for two defects in `app.evolution.promotion`/`app.evolution.ledger`/
`app.evolution.feedback`:

1. **Content-digest deduplication.** `genome_id_for` mints `g{generation}-{digest}`, and only a
   candidate carried forward as an elite keeps its original id across generations -- one the search
   *rediscovers from scratch* mints a brand new id over identical content. Before this change, the
   promotion guard (`evaluate_promotions`'s `already_promoted`), the consecutive-evidence walk
   (`_consecutive_evidence`), and the ledger's multiple-comparison denominator
   (`Ledger.distinct_candidates`/`Ledger.q_values`) all matched on the full `genome_id`, so a
   re-discovered identical card read as a second, unrelated hypothesis: it could accumulate its own
   two-consecutive-generations streak and get promoted a second time, and it inflated `m` in the
   Benjamini-Hochberg correction. This file proves the fix keys all three on
   `app.evolution.models.content_digest` instead, and that evidence recorded under one id is merged
   onto (never dropped in favour of) a differently-idd rediscovery of the same content.

2. **Unlocked read-modify-write races.** `request_seat` (the evolution loop's own supervisor thread)
   and `_transition` (FastAPI's threadpool, via `shelve_pending_seat`/`seat_pending_seat`/
   `reject_pending_seat`/`retire_pending_seat`) both used to do read -> modify -> `_write_pending_seats`
   with no coordination, so whichever wrote second could silently discard the other's change. This file
   drives both from real threads concurrently and asserts every write survives.

3. **Gate/panel disagreement.** `clears_gate` prefers `Standing.median_adjusted_excess`;
   `app.evolution.feedback._gate_finding` used to count clearers on raw `median_excess` alone. This
   file proves they now agree via the shared `app.evolution.promotion.gate_median_excess` helper, on a
   standing where the raw and adjusted figures disagree in sign.

Builders below are small and local, duplicated from `tests/test_evolution_promotion.py` and
`tests/test_evolution_seating.py` rather than imported -- this repo's own "duplicated fakes rather
than a cross-file import" style (see `tests/test_paperdesk.py`'s module docstring for the precedent).
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from decimal import Decimal

import pytest

from app.config import Settings
from app.evolution import feedback, promotion
from app.evolution.ledger import Ledger, LedgerEntry
from app.evolution.models import (
    GenerationOutcome,
    Genome,
    LoopConfig,
    PendingSeat,
    Standing,
    content_digest,
    generated_tier_dir,
)
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _settings(tmp_path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        library_dir=tmp_path / "library",
    )


def _card(agent_id: str, *, purpose: Purpose = Purpose.TRADING) -> StrategyCard:
    universe = ("AAA", "BBB")
    return StrategyCard(
        agent_id=agent_id,
        display_name=agent_id,
        discipline=Discipline.MOMENTUM,
        purpose=purpose,
        thesis="a test thesis, written before the trading window ran",
        universe=universe,
        entry="close > 0",
        exit="close < 0",
        stop_loss_pct=Decimal("0.10"),
        take_profit_pct=None,
        max_hold_days=180,
        max_positions=len(universe),
        position_pct=Decimal("1") / len(universe),
        designed_through=DESIGN_THROUGH,
    )


def _write_generated_card(settings: Settings, card: StrategyCard) -> None:
    tier_dir = generated_tier_dir(settings)
    tier_dir.mkdir(parents=True, exist_ok=True)
    (tier_dir / f"{card.agent_id}.json").write_text(card.model_dump_json(), encoding="utf-8")


def _genome(genome_id: str, *, generation: int, purpose: Purpose = Purpose.TRADING) -> Genome:
    return Genome(
        genome_id=genome_id,
        generation=generation,
        parents=(),
        origin="founder",
        shape="rules",
        purpose=purpose,
        universe=("AAA", "BBB"),
        traits={},
        seed=0,
        notes="a test genome",
    )


def _standing(
    genome_id: str,
    *,
    eligible: bool = True,
    median_excess: Decimal | None = Decimal("0.30"),
    median_adjusted_excess: Decimal | None = None,
    holdout_median_excess: Decimal | None = None,
    total_trades: int = 5,
    rank: int = 1,
) -> Standing:
    return Standing(
        genome_id=genome_id,
        agent_id=genome_id,
        display_name=genome_id,
        rank=rank,
        eligible=eligible,
        windows_run=8,
        median_excess=median_excess,
        median_adjusted_excess=median_adjusted_excess,
        worst_excess=Decimal("1"),
        hit_rate=0.6,
        total_trades=total_trades,
        holdout_median_excess=holdout_median_excess,
        q_value=None,
    )


def _outcome(
    generation: int,
    windows: tuple[str, ...],
    standings: tuple[Standing, ...],
    *,
    purpose: Purpose = Purpose.TRADING,
) -> GenerationOutcome:
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    return GenerationOutcome(
        generation=generation,
        round_id=f"r-auto-{generation}",
        purpose=purpose,
        status="succeeded",
        started_at=now,
        finished_at=now,
        windows=windows,
        genome_ids=tuple(s.genome_id for s in standings),
        standings=standings,
    )


def _pending_seat(genome_id: str, *, purpose: Purpose = Purpose.TRADING) -> PendingSeat:
    return PendingSeat(
        genome_id=genome_id,
        agent_id=genome_id,
        purpose=purpose,
        requested_at=dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC),
        generations=(1, 2),
        window_sets=(("w1", "w2"), ("w3", "w4")),
        median_excess=Decimal("0.30"),
        holdout_median_excess=None,
        q_value=None,
        library_path=f"backend/app/paper/library/candidates/{genome_id}.json",
        reason="test fixture",
    )


_CONFIG = LoopConfig(promotion_margin_pp=Decimal("5"))


# ---------------------------------------------------------------------------
# (a) content-digest dedup in the promotion guard and the consecutive-evidence walk
# ---------------------------------------------------------------------------


class TestContentDigestDedup:
    def test_a_rediscovered_identical_card_is_not_promoted_twice(self, tmp_path) -> None:
        """Two independently-discovered genomes sharing one `content_digest` -- the exact shape of
        the three duplicate pairs found in the live `promotions.jsonl` (0a9fcd74b740, c29fafa19c2b,
        145d2d5dbfeb, each minted under two ids). The first clears the gate twice under its own id and
        is promoted; the second, unrelated id sharing the same digest must be refused outright even
        though it has its own, entirely independent two-consecutive-generations streak."""
        digest = "shared0000001"
        id_a = f"g001-{digest}"
        id_b = f"g100-{digest}"
        assert content_digest(id_a) == content_digest(id_b) == digest
        assert id_a != id_b

        settings = _settings(tmp_path)
        genome_a = _genome(id_a, generation=1)
        genome_b = _genome(id_b, generation=99)
        _write_generated_card(settings, _card(id_a))
        _write_generated_card(settings, _card(id_b))

        # id_a: qualifies at generation 1 on (w3, w4), qualifies again (current) at generation 2 on
        # (w1, w2) -- two distinct window sets, promotes normally.
        history_a = (_outcome(1, ("w3", "w4"), (_standing(id_a),)),)
        first = promotion.evaluate_promotions(
            standings=(_standing(id_a),),
            genomes={id_a: genome_a},
            history=history_a,
            config=_CONFIG,
            generation=2,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        assert len(first) == 1
        assert first[0].genome_id == id_a

        # id_b: its OWN, entirely separate two-consecutive-generations streak, at much later
        # generations and on window sets that never appear anywhere in id_a's history.
        history_b = (_outcome(99, ("w7", "w8"), (_standing(id_b),)),)
        second = promotion.evaluate_promotions(
            standings=(_standing(id_b),),
            genomes={id_b: genome_b},
            history=history_b,
            config=_CONFIG,
            generation=100,
            selection_windows=("w9", "wa"),
            settings=settings,
        )
        assert second == (), (
            "a second id minted over content already promoted must be refused, not treated as a "
            "fresh hypothesis with its own independent evidence"
        )
        assert len(promotion.load_promotions(settings)) == 1

    def test_two_standings_sharing_content_in_one_call_promote_only_once(self, tmp_path) -> None:
        """The in-call guard: if two standings passed to a single `evaluate_promotions` call happen
        to share a `content_digest` (both already individually cleared their own
        `promotion_consecutive` streak by the time this call runs), the second must not slip past a
        set computed only once at the top of the function, before the first was recorded."""
        digest = "shared0000002"
        id_a = f"g001-{digest}"
        id_b = f"g002-{digest}"
        settings = _settings(tmp_path)
        genome_a = _genome(id_a, generation=1)
        genome_b = _genome(id_b, generation=2)
        _write_generated_card(settings, _card(id_a))
        _write_generated_card(settings, _card(id_b))

        # Both standings already have a qualifying prior generation of their own, on a window set
        # differing from the current one, so both would independently clear
        # `promotion_consecutive` in isolation.
        history = (
            _outcome(0, ("w3", "w4"), (_standing(id_a),)),
            _outcome(0, ("w3", "w4"), (_standing(id_b),)),
        )
        records = promotion.evaluate_promotions(
            standings=(_standing(id_a), _standing(id_b)),
            genomes={id_a: genome_a, id_b: genome_b},
            history=history,
            config=_CONFIG,
            generation=1,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        assert len(records) == 1, "one content digest must yield exactly one promotion per call"

    def test_consecutive_evidence_merges_across_ids_sharing_content(self, tmp_path) -> None:
        """A qualifying generation recorded under one id must count as evidence for a *different* id
        minted later over the same content -- merging the standings, not dropping the earlier one.

        `id_a` qualified once, alone, at generation 1 (never itself promoted -- one clearance is not
        enough). The search then rediscovers the same content from scratch at generation 5, minting
        `id_b`. `id_b`'s own current clearance, plus `id_a`'s generation-1 clearance on a differing
        window set, must together satisfy the two-consecutive-generations requirement -- proving the
        walk matches by content, not merely refusing a duplicate promotion after the fact.
        """
        digest = "shared0000003"
        id_a = f"g001-{digest}"
        id_b = f"g005-{digest}"
        settings = _settings(tmp_path)
        genome_b = _genome(id_b, generation=5)
        _write_generated_card(settings, _card(id_b))

        # Only id_a's standing exists in generation 1's history -- id_b never ran that generation
        # under its own id, because it did not exist yet.
        history = (_outcome(1, ("w3", "w4"), (_standing(id_a),)),)

        records = promotion.evaluate_promotions(
            standings=(_standing(id_b),),
            genomes={id_b: genome_b},
            history=history,
            config=_CONFIG,
            generation=5,
            selection_windows=("w1", "w2"),  # differs from generation 1's ("w3", "w4")
            settings=settings,
        )
        assert len(records) == 1
        record = records[0]
        assert record.genome_id == id_b
        assert set(record.generations) == {1, 5}
        assert set(record.window_sets) == {("w3", "w4"), ("w1", "w2")}


# ---------------------------------------------------------------------------
# (b) Ledger.distinct_candidates / Ledger.q_values counted once per content digest
# ---------------------------------------------------------------------------


class TestLedgerContentDigestDedup:
    def _entry(
        self,
        genome_id: str,
        *,
        generation: int,
        p_value: float | None,
        recorded_at: dt.datetime,
    ) -> LedgerEntry:
        return LedgerEntry(
            genome_id=genome_id,
            generation=generation,
            purpose=str(Purpose.TRADING),
            round_id=f"r-auto-{generation}",
            windows=("w1", "w2"),
            median_excess=Decimal("0.30"),
            holdout_median_excess=None,
            closed_trades=20,
            wins=15,
            p_value=p_value,
            recorded_at=recorded_at,
        )

    def test_distinct_candidates_counts_shared_content_once(self, tmp_path) -> None:
        digest = "sharedledger01"
        id_a = f"g001-{digest}"
        id_b = f"g050-{digest}"  # a later rediscovery of the identical content
        other = "g002-unrelated0"

        ledger = Ledger(tmp_path / "ledger.jsonl")
        ledger.record(
            [
                self._entry(id_a, generation=1, p_value=0.01, recorded_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
                self._entry(id_b, generation=50, p_value=0.02, recorded_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC)),
                self._entry(other, generation=2, p_value=0.10, recorded_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC)),
            ]
        )
        assert ledger.distinct_candidates() == 2, (
            "id_a and id_b are the same content re-minted under two ids and must occupy one seat "
            "in the multiple-comparison denominator, not two"
        )

    def test_q_values_merges_the_group_and_keys_the_result_by_every_id(self, tmp_path) -> None:
        digest = "sharedledger02"
        id_a = f"g001-{digest}"
        id_b = f"g050-{digest}"
        other = "g002-unrelated0"

        ledger = Ledger(tmp_path / "ledger.jsonl")
        # id_a recorded first (older); id_b is the more recent measurement of the same content and
        # must be the one whose p-value the merged group's q-value is actually computed from.
        ledger.record(
            [
                self._entry(id_a, generation=1, p_value=0.20, recorded_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
                self._entry(other, generation=2, p_value=0.10, recorded_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC)),
                self._entry(id_b, generation=50, p_value=0.02, recorded_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC)),
            ]
        )
        q = ledger.q_values()

        # Both ids that ever carried this content are present, and mapped to the identical q-value --
        # the merge, not a drop of the earlier id's row.
        assert id_a in q
        assert id_b in q
        assert q[id_a] == q[id_b]

        # And that shared value is computed over m=2 (this digest, plus `other`), from id_b's own
        # p-value (0.02, the most recently recorded for this digest) -- not m=3 as counting raw ids
        # would give, and not id_a's stale 0.20.
        from app.backtest.scan import benjamini_hochberg

        expected = benjamini_hochberg([0.02, 0.10])[0]
        assert expected is not None
        assert q[id_a] == pytest.approx(expected)
        assert q[other] != q[id_a]


# ---------------------------------------------------------------------------
# (c) concurrent request_seat / _transition do not lose writes
# ---------------------------------------------------------------------------


class TestConcurrentPendingSeatWrites:
    def test_concurrent_filing_and_deciding_survive_both(self, tmp_path, monkeypatch) -> None:
        """The exact race Task 2 describes: the loop's supervisor thread files new seat requests
        (`request_seat`) at the same moment a person decides unrelated rows through the FastAPI
        threadpool (`shelve_pending_seat` -> `_transition`). Before the lock, whichever call's
        `_write_pending_seats` landed second would silently discard the other's change -- a filed
        request could vanish, or a human decision could revert to `"pending"`.

        `_write_pending_seats` is monkeypatched to sleep briefly between being called and actually
        writing, widening the read-modify-write window so the two real threads below are far more
        likely to actually contend for `_PENDING_SEATS_LOCK` rather than happening to run back to
        back -- a stronger proof that the lock, not GIL luck, is what keeps every write intact.
        """
        settings = _settings(tmp_path)
        n = 25

        # Pre-file the rows the "decider" thread will act on, before either thread starts.
        pre_filed_ids = [f"g001-decide{i:03d}" for i in range(n)]
        for genome_id in pre_filed_ids:
            promotion.request_seat(_pending_seat(genome_id), settings=settings)

        original_write = promotion._write_pending_seats

        def _slow_write(seats, *, settings):
            time.sleep(0.003)
            return original_write(seats, settings=settings)

        monkeypatch.setattr(promotion, "_write_pending_seats", _slow_write)

        filed_new_ids = [f"g100-new{i:03d}" for i in range(n)]
        errors: list[BaseException] = []

        def _file_new_requests() -> None:
            try:
                for genome_id in filed_new_ids:
                    promotion.request_seat(_pending_seat(genome_id), settings=settings)
            except BaseException as exc:
                errors.append(exc)

        def _decide_existing() -> None:
            try:
                for genome_id in pre_filed_ids:
                    promotion.shelve_pending_seat(
                        genome_id, note="shelved concurrently", settings=settings
                    )
            except BaseException as exc:
                errors.append(exc)

        filer = threading.Thread(target=_file_new_requests, name="filer")
        decider = threading.Thread(target=_decide_existing, name="decider")
        filer.start()
        decider.start()
        filer.join(timeout=60)
        decider.join(timeout=60)

        assert not filer.is_alive() and not decider.is_alive(), "a worker thread deadlocked"
        assert not errors, f"unexpected exception(s) in worker threads: {errors}"

        final = {seat.genome_id: seat for seat in promotion.read_pending_seats(settings)}
        assert len(final) == 2 * n, (
            f"expected {2 * n} rows (no row dropped or duplicated by the race), got {len(final)}"
        )
        for genome_id in filed_new_ids:
            assert genome_id in final, f"{genome_id}: a concurrent decision must not drop a new request"
            assert final[genome_id].status == "pending"
        for genome_id in pre_filed_ids:
            assert genome_id in final
            assert final[genome_id].status == "shelved", (
                f"{genome_id}: a concurrent new seat request must never silently revert a human "
                f"decision back to pending (got {final[genome_id].status!r})"
            )

    def test_tmp_staging_names_do_not_collide_across_threads(self, tmp_path) -> None:
        """`_write_pending_seats`'s temp file must carry the thread id, not only the pid -- two
        threads in one process racing the identical `.tmp-{pid}` path could otherwise have one
        thread's write clobbered by the other's before either reaches `Path.replace`. Eight threads,
        each filing its own distinct request, exercise that path directly (`_PENDING_SEATS_LOCK`
        still serializes the actual writes, but each one must stage under its own temp name and every
        temp file must be gone by the time the thread returns)."""
        settings = _settings(tmp_path)

        def _worker(genome_id: str) -> None:
            promotion.request_seat(_pending_seat(genome_id), settings=settings)

        ids = [f"g001-thread{i:02d}" for i in range(8)]
        threads = [threading.Thread(target=_worker, args=(genome_id,)) for genome_id in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert all(not t.is_alive() for t in threads), "a worker thread deadlocked"

        # No stray temp file left behind by any thread -- every one reached `Path.replace`.
        leftovers = list((settings.data_dir / "loop").glob("*.tmp-*"))
        assert leftovers == [], f"stray temp file(s) left behind: {leftovers}"
        final_ids = {seat.genome_id for seat in promotion.read_pending_seats(settings)}
        assert final_ids == set(ids)


# ---------------------------------------------------------------------------
# (d) the gate and the panel agree on the metric, even when raw and adjusted excess disagree in sign
# ---------------------------------------------------------------------------


class TestGateAndPanelAgree:
    def test_agree_when_raw_and_adjusted_excess_differ_in_sign(self) -> None:
        config = LoopConfig(promotion_margin_pp=Decimal("5"))

        # Raw median says "cleared" (+30pp); the exposure-adjusted figure -- the one PROTOCOL.md
        # section 4 actually asks for -- says it did not (-5pp, at the margin's edge but not past
        # it). Before the shared helper, `_gate_finding` counted this on the raw figure alone while
        # `clears_gate` refused it on the adjusted one.
        deceptive = _standing(
            "g001-deceptive", median_excess=Decimal("0.30"), total_trades=10
        ).model_copy(update={"median_adjusted_excess": Decimal("-0.05")})

        # The mirror case: raw says "not cleared" (-5pp), adjusted says it did (+30pp).
        undersold = _standing(
            "g001-undersold", median_excess=Decimal("-0.05"), total_trades=10
        ).model_copy(update={"median_adjusted_excess": Decimal("0.30")})

        standings = (deceptive, undersold)
        gate_finding = next(
            f
            for f in feedback.derive_findings(
                standings,
                config=config,
                purpose=Purpose.TRADING,
                selection_windows=("w1", "w2"),
                holdout_windows=(),
                genomes={},
            )
            if f.kind == "gate"
        )
        cleared_by_panel = set(gate_finding.evidence["cleared_genome_ids"])
        cleared_by_gate = {s.genome_id for s in standings if promotion.clears_gate(s, config=config)}

        assert cleared_by_gate == {"g001-undersold"}, "sanity check on clears_gate itself"
        assert cleared_by_panel == cleared_by_gate, (
            "the panel's gate finding and promotion.clears_gate must agree on which candidates "
            "cleared the margin -- they disagreed here before the shared helper existed"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
