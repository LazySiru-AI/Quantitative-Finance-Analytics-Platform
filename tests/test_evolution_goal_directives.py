"""`app.evolution.goal_directives`, and the `PLAN.md` section it writes into.

The case these exist for is on disk: `data/loop/gen1873/PLAN.md` records
`purposes=['trading', 'roth', 'saving']` under "What this generation is for" and then records a
generation that ran the default lanes, with nothing marking the gap and nothing noting that `saving`
is not a purpose at all. What is pinned here:

  - the directive is found, and the note names both faults (it did not take effect; the value is not
    legal) alongside what the run *actually* used;
  - an ordinary goal -- the question this field is for -- produces no notes at all, and no heading;
  - a directive the config genuinely reflects produces no note either, because there is nothing wrong
    with it;
  - none of this changes the config, refuses a write, or gives `goal` any influence over the search.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.config import Settings
from app.evolution.goal_directives import find_unapplied_goal_directives, goal_directive_notes
from app.evolution.loop import _write_plan_file
from app.evolution.models import Genome, LoopConfig, loop_root
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _config(**overrides: object) -> LoopConfig:
    """A `LoopConfig` with the fields this module reads, defaulted to the real ones -- `purposes`
    especially: `(TRADING, ROTH)` is exactly what gen1873 ran with."""
    base: dict[str, object] = {
        "purposes": (Purpose.TRADING, Purpose.ROTH),
        "rank_by": "median",
        "focus_symbols": (),
        "avoid_symbols": (),
        "goal": "",
    }
    base.update(overrides)
    return LoopConfig(**base)  # type: ignore[arg-type]


def _genome() -> Genome:
    return Genome(
        genome_id="g1873-fdc4f3a52dd6",
        generation=1873,
        parents=(),
        origin="founder",
        shape="rules",
        purpose=Purpose.TRADING,
        universe=("NVDA", "AMD"),
        traits={"fast": 15},
        seed=1,
        notes="synthetic candidate",
    )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_empty_goal_produces_nothing() -> None:
    assert find_unapplied_goal_directives(_config(goal="")) == ()
    assert find_unapplied_goal_directives(_config(goal="   \n  ")) == ()


def test_an_ordinary_question_produces_nothing() -> None:
    """The sentence the field is *for* must never trip this. A colon is ordinary punctuation in a
    goal, and a passing mention of a metric is not a directive."""
    goal = (
        "does a small semiconductor tilt survive a drawdown better than a pure trend book? "
        "what I want to know: whether the median excess holds up once the holdout rotates."
    )
    assert find_unapplied_goal_directives(_config(goal=goal)) == ()


def test_gen1873_goal_is_reported_with_both_faults() -> None:
    config = _config(
        goal="add saving as one of purpose as well\npurposes=['trading', 'roth', 'saving']",
    )
    (directive,) = find_unapplied_goal_directives(config)

    assert directive.field == "purposes"
    assert directive.values == ("trading", "roth", "saving")
    # What the generation actually ran with -- the thing only the server-side check can say.
    assert directive.effective == ("trading", "roth")
    assert directive.illegal == ("saving",)
    assert directive.legal_values == ("savings", "trading", "roth")

    (note,) = goal_directive_notes(config)
    assert "had no effect" in note
    assert "`purposes` = trading, roth" in note
    assert "`saving`" in note
    assert "savings, trading, roth" in note


def test_a_legal_but_unapplied_purposes_directive_is_still_reported() -> None:
    """`savings` is a real purpose; asking for it in prose still did not add a savings lane."""
    (directive,) = find_unapplied_goal_directives(
        _config(goal="purposes=['trading', 'roth', 'savings']")
    )
    assert directive.illegal == ()
    assert directive.values == ("trading", "roth", "savings")
    assert directive.effective == ("trading", "roth")


def test_a_purposes_directive_the_run_actually_carries_is_not_reported() -> None:
    config = _config(
        purposes=(Purpose.TRADING, Purpose.ROTH, Purpose.SAVINGS),
        goal="purposes=['trading', 'roth', 'savings']",
    )
    assert find_unapplied_goal_directives(config) == ()


def test_asking_for_fewer_purposes_than_the_run_breeds_is_reported() -> None:
    """Set equality, not containment: `purposes` replaces the lane rotation, so a goal asking for
    trading alone against a trading+roth run did not take effect -- see `_is_applied`."""
    (directive,) = find_unapplied_goal_directives(_config(goal="purposes=trading"))
    assert directive.values == ("trading",)
    assert directive.effective == ("trading", "roth")


def test_symbol_directives_compare_by_containment() -> None:
    """A focus list is a per-candidate constraint, so a run enforcing more tickers than the goal named
    still satisfies it -- the opposite convention to `purposes`, deliberately."""
    assert (
        find_unapplied_goal_directives(
            _config(goal="focus=NVDA,AMD", focus_symbols=("NVDA", "AMD", "MU"))
        )
        == ()
    )
    (directive,) = find_unapplied_goal_directives(
        _config(goal="focus=NVDA,AMD", focus_symbols=("NVDA",))
    )
    assert directive.field == "focus_symbols"
    assert directive.values == ("NVDA", "AMD")
    assert directive.effective == ("NVDA",)
    # A ticker's legality is the start-time validator's business, not this module's.
    assert directive.illegal == ()
    assert directive.legal_values is None


def test_a_bare_ticker_list_is_reported_but_prose_acronyms_are_not() -> None:
    (directive,) = find_unapplied_goal_directives(_config(goal="try a book of NVDA, AMD, MU"))
    assert directive.values == ("NVDA", "AMD", "MU")
    assert find_unapplied_goal_directives(_config(goal="compare IRR, CAGR, and TWR")) == ()


def test_a_ranking_metric_phrase_resolves_to_its_longest_legal_name() -> None:
    (hit,) = find_unapplied_goal_directives(_config(goal="rank by hit rate this time"))
    assert hit.field == "rank_by"
    assert hit.values == ("hit-rate",)
    assert hit.illegal == ()
    assert hit.effective == ("median",)

    (exposure,) = find_unapplied_goal_directives(
        _config(goal="ranked by excess per exposure over the matrix")
    )
    assert exposure.values == ("excess-per-exposure",)

    (sharpe,) = find_unapplied_goal_directives(_config(goal="optimise for sharpe"))
    assert sharpe.illegal == ("sharpe",)
    assert sharpe.legal_values == ("median", "worst", "hit-rate", "excess-per-exposure")


def test_a_metric_the_run_already_ranks_by_is_not_reported() -> None:
    assert find_unapplied_goal_directives(_config(goal="rank by median")) == ()


def test_each_directive_is_reported_once_and_a_swallowed_key_is_not_missed() -> None:
    """The word before a directive must not be eaten by its key -- an earlier version matched
    `"plus avoid"` as one key, resolved it to no field, and silently dropped the `avoid=` inside it."""
    directives = find_unapplied_goal_directives(
        _config(goal="purposes=['saving'] and purposes=['saving'] again, plus avoid=TSLA")
    )
    assert [d.field for d in directives] == ["purposes", "avoid_symbols"]


def test_tickers_inside_a_directive_are_not_reported_again_as_a_bare_list() -> None:
    directives = find_unapplied_goal_directives(_config(goal="focus=NVDA,AMD,MU"))
    assert len(directives) == 1
    assert directives[0].field == "focus_symbols"


# ---------------------------------------------------------------------------
# PLAN.md
# ---------------------------------------------------------------------------


def _write_plan(settings: Settings, config: LoopConfig) -> Path:
    return _write_plan_file(
        settings,
        generation=1873,
        round_id="r17-auto-20260826-155413-g1873",
        purpose=Purpose.TRADING,
        genomes=[_genome()],
        selection_windows=["bear-2022", "chop-2015"],
        holdout_windows=["covid", "q4-2018"],
        config=config,
    )


def test_plan_records_a_goal_directive_that_did_not_take_effect(settings: Settings) -> None:
    config = _config(
        goal="add saving as one of purpose as well\npurposes=['trading', 'roth', 'saving']",
    )
    text = _write_plan(settings, config).read_text(encoding="utf-8")

    # The goal is still recorded verbatim -- the note is added beside it, never in place of it.
    assert "**Goal:** add saving as one of purpose as well" in text
    assert "purposes=['trading', 'roth', 'saving']" in text
    assert "**The goal names settings the goal field cannot change:**" in text
    assert "had no effect" in text
    assert "`purposes` = trading, roth" in text
    assert "the legal values are savings, trading, roth" in text
    # And the note sits inside the section it is about, before the candidate list.
    assert text.index("had no effect") < text.index("## Candidates")


def test_plan_adds_no_heading_when_the_goal_is_an_ordinary_question(settings: Settings) -> None:
    config = _config(goal="does a semiconductor tilt survive a drawdown better than a trend book?")
    text = _write_plan(settings, config).read_text(encoding="utf-8")

    assert "**The goal names settings" not in text
    assert "**Goal:** does a semiconductor tilt" in text
    # The existing pre-registration block is untouched by any of this.
    assert "`goal` is recorded verbatim and does not steer the search" in text
    assert "**Rank by:** median" in text


def test_plan_is_written_for_an_empty_goal_exactly_as_before(settings: Settings) -> None:
    text = _write_plan(settings, _config(goal="")).read_text(encoding="utf-8")

    assert "**Goal:** (no goal was stated)" in text
    assert "**The goal names settings" not in text


def test_writing_the_plan_does_not_touch_the_config(settings: Settings) -> None:
    """The whole module is a reader's note. It may not become a second, sneaky way for `goal` to
    configure a run -- see `app.evolution.goal_directives`' own docstring."""
    config = _config(goal="purposes=['trading', 'roth', 'saving']", focus_symbols=("NVDA",))
    before = config.model_dump_json()

    _write_plan(settings, config)

    assert config.model_dump_json() == before
    assert config.purposes == (Purpose.TRADING, Purpose.ROTH)
    assert loop_root(settings).exists()


def test_promotion_margin_default_is_untouched_by_this_module(settings: Settings) -> None:
    """A guard on the block this edit rewrote: the gate paragraph still renders its real number."""
    config = _config(goal="purposes=['saving']")
    text = _write_plan(settings, config).read_text(encoding="utf-8")

    assert isinstance(config.promotion_margin_pp, Decimal)
    assert f"= {config.promotion_margin_pp} on selection-window median excess" in text
