"""Unit tests for the agent-desk shared core: evidence rendering, the grounding gate, run
persistence, and the per-kind job registry.

No test here makes a real model call or a real network request. `run_grounded` is exercised against a
monkeypatched `app.agentdesk.grounding.call_structured`; the one evidence test that reaches into
`app.market.store` monkeypatches `ensure_series` to raise, so the fail-soft path is proven without a
live provider anywhere in the loop.
"""

from __future__ import annotations

import datetime as dt
import threading
from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.agentdesk import evidence, jobs
from app.agentdesk.grounding import (
    GroundedResult,
    check,
    correction_prompt,
    grounded_values,
    numeric_tokens,
    run_grounded,
)
from app.agentdesk.jobs import DeskRegistry, RunAlreadyActive
from app.agentdesk.models import (
    DeskRun,
    EvidenceItem,
    EvidencePack,
    EvidenceSection,
    StageRecord,
)
from app.agentdesk.store import RunStore, with_stage
from app.agents.models import (
    AgentBudget,
    AgentCall,
    AgentResponseInvalid,
    AgentTransientError,
    AgentUnavailable,
)
from app.config import Settings
from app.market.providers.base import ProviderUnavailable

# ---------------------------------------------------------------------------
# numeric_tokens / grounded_values / check
# ---------------------------------------------------------------------------


class TestNumericTokens:
    def test_thousands_separator_and_bare_decimal_collapse_to_the_same_token(self) -> None:
        assert numeric_tokens("Revenue was 1,234.50 million.") == numeric_tokens("Revenue was 1234.5 million.")
        assert numeric_tokens("Revenue was 1,234.50 million.") == ("1234.5",)

    def test_small_integers_zero_through_ten_are_exempt(self) -> None:
        assert numeric_tokens("3 of the 4 majors rose, with 10 laggards.") == ()

    def test_a_bare_four_digit_year_is_exempt(self) -> None:
        assert numeric_tokens("the 2024 10-K filing") == ()

    def test_an_ordinal_date_is_exempt(self) -> None:
        assert numeric_tokens("filed on the 21st of March") == ()

    def test_a_number_inside_a_markdown_link_target_is_ignored(self) -> None:
        assert numeric_tokens("see [the filing](https://sec.gov/Archives/1234567/report.htm)") == ()

    def test_a_genuine_measurement_is_kept(self) -> None:
        assert numeric_tokens("the close was $101.50, up 12.34%") == ("101.5", "12.34")

    # The four below are regressions on a defect found by probing the gate with realistic analyst
    # prose rather than by reading it: an ISO date leaked its day-of-month as a token, and a
    # parameterised indicator name leaked its parameter. Neither is a measurement, and both appear in
    # nearly every sentence the prompts actually ask for -- every system prompt in
    # `app.tradingagents.prompts` instructs its agent to cite as-of dates and to name indicators by
    # the labels the evidence uses, which are literally "RSI(14)" and "SMA(200)". The gate was
    # therefore rejecting agents for following their instructions, on almost every stage.

    def test_an_iso_date_does_not_leak_its_day_of_month(self) -> None:
        # The year is exempt as a bare year and the month as a small integer, but the day is neither:
        # "2026-08-28" used to yield ("28",) and reject the sentence carrying it.
        assert numeric_tokens("as of 2026-08-28") == ()
        assert numeric_tokens("between 2026-01-15 and 2026-08-28") == ()
        assert numeric_tokens("the close on 08/28/2026 was 187.45") == ("187.45",)

    def test_an_iso_date_at_the_end_of_a_clause_does_not_leak_its_day(self) -> None:
        # A sentence-final period (or comma) directly after the date must not stop the date scrub:
        # a blanket trailing `(?![\w.])` used to force a backtrack to the "2026-08" alternative and
        # leak the day as "-28", rejecting a sentence for the punctuation at its end. This is the
        # ordinary shape of the as-of citation every prompt asks for, so it was a false rejection on
        # nearly every real stage.
        assert numeric_tokens("The reading is as of 2026-08-28.") == ()
        assert numeric_tokens("as of 2026-08-28, up from the prior week") == ()
        assert numeric_tokens("dated 2026/08/28; the trend held") == ()
        assert numeric_tokens("(2026-08-28)") == ()
        # A date glued to a decimal continuation is still not scrubbed as a whole date -- the one `.`
        # case the trailing guard deliberately still blocks, so this pathological non-date form is not
        # silently swallowed.
        assert numeric_tokens("2026-08-28.5") != ()

    def test_a_parameterised_indicator_name_does_not_leak_its_parameter(self) -> None:
        assert numeric_tokens("RSI(14) read 61.30") == ("61.3",)
        assert numeric_tokens("bb(20,2) upper band at 191.02") == ("191.02",)

    def test_a_window_written_as_a_compound_adjective_is_exempt(self) -> None:
        assert numeric_tokens("price sits above the 200-day and the 50-week") == ()
        assert numeric_tokens("over the last 50 sessions") == ()

    def test_the_indicator_exemption_cannot_smuggle_a_bare_parenthesised_figure(self) -> None:
        # The exemption is scoped to digits in parens *attached to a preceding word*. A bare
        # parenthesised number is ordinary prose and must still be checked, or the exemption becomes
        # a hiding place for exactly the fabrication this gate exists to catch.
        assert numeric_tokens("a fabricated (192.80) in parens") == ("192.8",)

    def test_a_parameterised_indicator_name_with_a_space_before_its_params_is_exempt(self) -> None:
        # A model naming Bollinger Bands writes "Bollinger Bands (20,2)", with a space -- the attached
        # form (RSI(14)) misses it, and "20,2" then normalised to the token "202" and degraded the
        # stage for citing the indicator correctly. Real failing prose from run 65be4e23.
        assert numeric_tokens("Bollinger Bands (20,2) are upper-touched") == ()
        assert numeric_tokens("MACD (12, 26, 9) crossover in progress") == ()

    def test_the_spaced_indicator_exemption_still_cannot_smuggle_a_decimal(self) -> None:
        # The spaced form admits only integer/comma params; a decimal in parens after a word is a
        # quoted figure, not an indicator parameter, and must still be checked.
        assert numeric_tokens("the close (319.70) is real") == ("319.7",)

    def test_a_bare_month_day_date_does_not_leak_its_day(self) -> None:
        # Analysts label each price with a parenthetical month-day stamp -- "305.59 (08-17)" -- which
        # carries no year, so _DATE_RE's year-bearing forms missed it and the day past the 10th leaked
        # as a token. Real failing prose from runs 8708e0c2 / 65be4e23.
        assert numeric_tokens("305.59 (08-17) then 309.35 (08-21)") == ("305.59", "309.35")
        assert numeric_tokens("prior close (08-27) into (08-28)") == ()

    def test_the_month_day_exemption_is_scoped_to_real_calendar_shapes(self) -> None:
        # An invalid "month" (the 20 of a Bollinger 20,2) or an unpadded subtraction must not be
        # swallowed as a date -- only a 01-12 month with a 01-31 day is exempt.
        assert "20" in numeric_tokens("a ratio of 20/45 holds")  # month 20 is not a date
        assert numeric_tokens("11/25 close") == ()  # a real month-day still is


class TestGroundedValues:
    def _pack(self) -> EvidencePack:
        section = EvidenceSection(
            title="Price",
            items=(
                EvidenceItem(key="close", label="Close", value="100.00", unit="USD", as_of="2026-08-01"),
                EvidenceItem(key="close_prev", label="Close (T-1)", value="95.00", unit="USD", as_of="2026-07-31"),
            ),
        )
        return EvidencePack(symbol="AAPL", sections=(section,))

    def test_item_values_are_grounded(self) -> None:
        values = grounded_values(self._pack())
        assert "100" in values
        assert "95" in values

    def test_a_derived_difference_and_percentage_change_are_admitted(self) -> None:
        values = grounded_values(self._pack())
        assert "5" in values  # 100.00 - 95.00
        # (100 - 95) / 95 * 100 = 5.26...  -> rounded to 2dp
        assert "5.26" in values

    def test_a_ratio_of_two_grounded_figures_is_admitted(self) -> None:
        # A ratio is arithmetic on two handed figures, not an invented third -- the fundamentals
        # analyst's stock-in-trade (debt-to-equity, ROE, ROA, leverage, margin) is ratios, none of
        # which is a difference or a percentage *change*. Real AAPL fundamentals from run 3f05df5f:
        # liabilities / equity = debt-to-equity, net income / equity = ROE%.
        pack = EvidencePack(
            symbol="AAPL",
            sections=(
                EvidenceSection(
                    title="Fundamentals",
                    items=(
                        EvidenceItem(key="li", label="Total liabilities", value="285508000000.00"),
                        EvidenceItem(key="eq", label="Stockholders' equity", value="73733000000.00"),
                        EvidenceItem(key="ni", label="Net income", value="112010000000.00"),
                    ),
                ),
            ),
        )
        values = grounded_values(pack)
        assert "3.87" in values  # 285508 / 73733 = 3.872 -> debt-to-equity
        assert "151.9" in values  # 112010 / 73733 * 100 = 151.91 -> return on equity %

    def test_the_ratio_admission_does_not_ground_an_unrelated_fabrication(self) -> None:
        # Admitting quotients must not turn the grounded set into a hiding place: a figure that is
        # neither an item, a difference, a percentage change, nor a ratio of two items is still caught.
        values = grounded_values(self._pack())  # items 100.00 and 95.00 only
        assert "777.77" not in values

    def test_a_difference_across_two_sections_is_admitted(self) -> None:
        # The single most common technical-desk sentence -- "the close is N above its 50-day" -- pairs
        # a figure from the Price section with one from Indicators. Grounding that difference used to be
        # impossible (the pairwise derivation was same-section only), so every stage that wrote it was
        # degraded for stating arithmetic on the very numbers it was handed. Cross-section pairs are now
        # admitted: a difference of two real evidence figures is not a fabrication, wherever they sit.
        pack = EvidencePack(
            symbol="AAPL",
            sections=(
                EvidenceSection(
                    title="Price",
                    items=(EvidenceItem(key="close", label="Close", value="127.31", unit="USD"),),
                ),
                EvidenceSection(
                    title="Indicators",
                    items=(EvidenceItem(key="sma50", label="SMA_50", value="100.23"),),
                ),
            ),
        )
        values = grounded_values(pack)
        assert "27.08" in values  # 127.31 - 100.23, Price minus Indicators
        # ... and the check accepts a sentence stating exactly that comparison.
        verdict = check("Close 127.31 sits 27.08 above the 50-day of 100.23.", pack)
        assert verdict.ok is True, verdict.issues

    def test_a_figure_stated_to_fewer_decimals_is_a_rounding_not_a_fabrication(self) -> None:
        # A derived 9.73% written back as "9.7%", or a close of 127.31 written as "127.3", is an
        # ordinary one-decimal rounding of a real number -- the gate used to degrade the stage for it
        # because "9.7" != "9.73". Each grounded figure is now admitted at its coarser decimal
        # roundings too.
        pack = EvidencePack(
            symbol="AAPL",
            sections=(
                EvidenceSection(
                    title="Indicators",
                    items=(
                        EvidenceItem(key="roc", label="ROC", value="9.73"),
                        EvidenceItem(key="close", label="Close", value="127.31", unit="USD"),
                    ),
                ),
            ),
        )
        assert check("Momentum reads 9.7 and the close is near 127.3.", pack).ok is True
        # The relaxation is a rounding, not a free pass: the *wrong* rounding is still rejected
        # (9.73 rounds to 9.7, never 9.8), and exact precision still passes.
        assert check("Momentum reads 9.8.", pack).ok is False
        assert check("Momentum reads 9.73.", pack).ok is True

    def test_a_signed_figures_magnitude_is_admitted(self) -> None:
        # A stage carries the direction of a signed figure in words -- "a 15.23 loss" for a diluted EPS
        # the pack holds as -15.23, "lost 3,848,152,000" for a negative net income, "9.73% below" for a
        # percentage change stored as -9.73. This gate checks whether the number traces to the evidence,
        # not which way it points, so a signed figure's magnitude grounds.
        pack = EvidencePack(
            symbol="AAPL",
            sections=(
                EvidenceSection(
                    title="Fundamentals",
                    items=(
                        EvidenceItem(key="eps", label="Diluted EPS", value="-15.23", unit="USD"),
                        EvidenceItem(key="ni", label="Net income", value="-3848152000", unit="USD"),
                    ),
                ),
            ),
        )
        assert check("The desk notes a 15.23 loss per share and a 3,848,152,000 loss.", pack).ok is True
        # The magnitude carries its rounding relaxation too.
        assert check("Roughly a 15.2 loss per share.", pack).ok is True

    def test_rounding_never_collapses_a_figure_to_a_bare_integer(self) -> None:
        # The relaxation stops at one decimal place: a figure near a whole number does not admit the
        # integer, or the gate's integer strictness would be handed away -- a fabricated round "70"
        # would match any evidence figure that merely sits near it.
        pack = EvidencePack(
            symbol="AAPL",
            sections=(EvidenceSection(title="I", items=(EvidenceItem(key="x", label="X", value="70.40"),)),),
        )
        assert check("It sits at 70 flat.", pack).ok is False
        assert check("It sits at 70.4.", pack).ok is True

    def test_check_accepts_a_grounded_number(self) -> None:
        verdict = check("The close was 100.00, up from 95.00.", self._pack())
        assert verdict.ok is True
        assert verdict.issues == ()

    def test_check_rejects_an_ungrounded_number(self) -> None:
        verdict = check("The close was 250.00.", self._pack())
        assert verdict.ok is False
        assert verdict.issues[0].kind == "ungrounded_number"
        assert "250" in verdict.issues[0].detail

    def test_check_flags_empty_output(self) -> None:
        verdict = check("   ", self._pack())
        assert verdict.ok is False
        assert verdict.issues[0].kind == "empty_output"

    def test_check_flags_no_evidence_against_an_empty_pack(self) -> None:
        empty_pack = EvidencePack(symbol="AAPL", sections=(EvidenceSection(title="Price"),))
        verdict = check("The close was 100.00.", empty_pack)
        assert verdict.ok is False
        assert verdict.issues[0].kind == "no_evidence"

    def test_correction_prompt_quotes_the_issue_detail(self) -> None:
        verdict = check("The close was 250.00.", self._pack())
        prompt = correction_prompt(verdict)
        assert "250" in prompt
        assert "ungrounded_number" in prompt


# ---------------------------------------------------------------------------
# run_grounded
# ---------------------------------------------------------------------------


class _Answer(BaseModel):
    text: str


def _prose_of(answer: _Answer) -> str:
    return answer.text


def _fake_call(text: str) -> object:
    """A `call_structured`-shaped callable bound to always answer with `text`."""

    def fake(
        *,
        role: object,
        system: str,
        user: str,
        output_format: type[_Answer],
        model: str,
        settings: object,
        budget: AgentBudget,
        effort: str = "high",
    ) -> tuple[_Answer, AgentCall, AgentBudget]:
        call = AgentCall(
            call_id=f"call-{budget.calls}",
            role="market_analyst",
            model=model,
            created_at=dt.datetime.now(dt.UTC),
            system=system,
            user=user,
            raw_response=text,
        )
        new_budget = AgentBudget(cap_usd=budget.cap_usd, spent_usd=budget.spent_usd, calls=budget.calls + 1)
        return output_format(text=text), call, new_budget

    return fake


class TestRunGrounded:
    def _pack(self) -> EvidencePack:
        section = EvidenceSection(
            title="Price", items=(EvidenceItem(key="close", label="Close", value="100.00", unit="USD"),)
        )
        return EvidencePack(symbol="AAPL", sections=(section,))

    def test_a_grounded_first_attempt_returns_immediately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.agentdesk.grounding as grounding

        monkeypatch.setattr(grounding, "call_structured", _fake_call("The close was 100.00."))
        result = run_grounded(
            role="market_analyst",
            system="sys",
            user="user",
            output_format=_Answer,
            prose_of=_prose_of,
            pack=self._pack(),
            settings=Settings(),
            budget=AgentBudget(cap_usd=Decimal("5.00")),
        )
        assert isinstance(result, GroundedResult)
        assert result.verdict.ok is True
        assert result.verdict.attempts == 1
        assert len(result.calls) == 1

    def test_retries_then_degrades_after_max_attempts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.agentdesk.grounding as grounding

        monkeypatch.setattr(grounding, "call_structured", _fake_call("The close was 999.00."))
        result = run_grounded(
            role="market_analyst",
            system="sys",
            user="user",
            output_format=_Answer,
            prose_of=_prose_of,
            pack=self._pack(),
            settings=Settings(),
            budget=AgentBudget(cap_usd=Decimal("5.00")),
            max_attempts=3,
        )
        assert result.verdict.ok is False
        assert result.verdict.degraded is True
        assert result.verdict.attempts == 3
        assert len(result.calls) == 3
        assert result.value.text == "The close was 999.00."

    def test_retry_prompt_is_built_from_the_original_user_turn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.agentdesk.grounding as grounding

        seen_users: list[str] = []

        def fake(*, role, system, user, output_format, model, settings, budget, effort="high"):  # type: ignore[no-untyped-def]
            seen_users.append(user)
            call = AgentCall(
                call_id=f"call-{len(seen_users)}", role="market_analyst", model=model,
                created_at=dt.datetime.now(dt.UTC), system=system, user=user, raw_response="999.00",
            )
            new_budget = AgentBudget(cap_usd=budget.cap_usd, spent_usd=budget.spent_usd, calls=budget.calls + 1)
            return output_format(text="The close was 999.00."), call, new_budget

        monkeypatch.setattr(grounding, "call_structured", fake)
        run_grounded(
            role="market_analyst", system="sys", user="ORIGINAL_USER_TURN", output_format=_Answer,
            prose_of=_prose_of, pack=self._pack(), settings=Settings(),
            budget=AgentBudget(cap_usd=Decimal("5.00")), max_attempts=3,
        )
        assert seen_users[0] == "ORIGINAL_USER_TURN"
        for later in seen_users[1:]:
            assert later.startswith("ORIGINAL_USER_TURN\n\n")
            assert later.count("ORIGINAL_USER_TURN") == 1  # never compounds across retries

    def test_a_malformed_response_is_retried_and_can_then_succeed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A response the transport could not parse (a dropped required field, trailing prose) raises
        `AgentResponseInvalid`; `run_grounded` re-asks with a schema correction rather than failing.
        This is the exact failure that took a live Trading Agents run down -- an analyst that omitted
        its `takeaway` field -- now recovered within the attempt budget."""
        import app.agentdesk.grounding as grounding

        seen_users: list[str] = []
        n = {"c": 0}

        def fake(*, role, system, user, output_format, model, settings, budget, effort="high"):  # type: ignore[no-untyped-def]
            n["c"] += 1
            seen_users.append(user)
            if n["c"] == 1:
                raise AgentResponseInvalid("did not parse as AnalystReport: takeaway Field required")
            call = AgentCall(
                call_id=f"call-{n['c']}", role="market_analyst", model=model,
                created_at=dt.datetime.now(dt.UTC), system=system, user=user, raw_response="100.00",
            )
            nb = AgentBudget(cap_usd=budget.cap_usd, spent_usd=budget.spent_usd, calls=budget.calls + 1)
            return output_format(text="The close was 100.00."), call, nb

        monkeypatch.setattr(grounding, "call_structured", fake)
        result = run_grounded(
            role="market_analyst", system="sys", user="ORIG", output_format=_Answer,
            prose_of=_prose_of, pack=self._pack(), settings=Settings(),
            budget=AgentBudget(cap_usd=Decimal("5.00")), max_attempts=3,
        )
        assert result.verdict.ok is True
        assert n["c"] == 2  # one malformed attempt, then one that parsed and grounded
        assert len(result.calls) == 1  # only the successful call carries an AgentCall record
        # the retry after a malformed response carried the schema correction, not the grounding one
        assert "single JSON object" in seen_users[1]

    def test_every_attempt_malformed_reraises_rather_than_fabricating(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If a stage never once returns a parseable response, there is no report to degrade to -- so
        the last `AgentResponseInvalid` is surfaced (failing this stage, blocking those downstream)
        rather than inventing a value the model never produced."""
        import app.agentdesk.grounding as grounding

        n = {"c": 0}

        def fake(*, role, system, user, output_format, model, settings, budget, effort="high"):  # type: ignore[no-untyped-def]
            n["c"] += 1
            raise AgentResponseInvalid("did not parse")

        monkeypatch.setattr(grounding, "call_structured", fake)
        with pytest.raises(AgentResponseInvalid):
            run_grounded(
                role="market_analyst", system="sys", user="u", output_format=_Answer,
                prose_of=_prose_of, pack=self._pack(), settings=Settings(),
                budget=AgentBudget(cap_usd=Decimal("5.00")), max_attempts=3,
            )
        assert n["c"] == 3  # exhausted the attempt budget before giving up

    def test_a_transport_failure_propagates_immediately_without_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bare `AgentUnavailable` (no credential, dead transport) is NOT a malformed response and
        must not be retried -- re-asking a broken transport only wastes time. It propagates on the
        first attempt, exactly as before this retry path existed."""
        import app.agentdesk.grounding as grounding

        n = {"c": 0}

        def fake(*, role, system, user, output_format, model, settings, budget, effort="high"):  # type: ignore[no-untyped-def]
            n["c"] += 1
            raise AgentUnavailable("no usable credential")

        monkeypatch.setattr(grounding, "call_structured", fake)
        with pytest.raises(AgentUnavailable):
            run_grounded(
                role="market_analyst", system="sys", user="u", output_format=_Answer,
                prose_of=_prose_of, pack=self._pack(), settings=Settings(),
                budget=AgentBudget(cap_usd=Decimal("5.00")), max_attempts=3,
            )
        assert n["c"] == 1  # not retried

    def test_a_transient_api_error_is_retried_and_can_then_succeed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transient model/API error -- the CLI exited non-zero or reported `is_error` on one call
        -- is re-attempted with the same turn (nothing to correct), rather than failing the pipeline.
        This is the exact failure that took the risk-analyst stage of a live run down after eight
        earlier stages had already succeeded, proving the transport itself was healthy."""
        import app.agentdesk.grounding as grounding

        seen_users: list[str] = []
        n = {"c": 0}

        def fake(*, role, system, user, output_format, model, settings, budget, effort="high"):  # type: ignore[no-untyped-def]
            n["c"] += 1
            seen_users.append(user)
            if n["c"] == 1:
                raise AgentTransientError("Claude Code CLI exited 1 for risk_aggressive: is_error=true")
            call = AgentCall(
                call_id=f"call-{n['c']}", role="risk_aggressive", model=model,
                created_at=dt.datetime.now(dt.UTC), system=system, user=user, raw_response="100.00",
            )
            nb = AgentBudget(cap_usd=budget.cap_usd, spent_usd=budget.spent_usd, calls=budget.calls + 1)
            return output_format(text="The close was 100.00."), call, nb

        slept: list[float] = []
        monkeypatch.setattr(grounding, "call_structured", fake)
        result = run_grounded(
            role="risk_aggressive", system="sys", user="ORIG", output_format=_Answer,
            prose_of=_prose_of, pack=self._pack(), settings=Settings(),
            budget=AgentBudget(cap_usd=Decimal("5.00")), max_attempts=3,
            sleep=slept.append,
        )
        assert result.verdict.ok is True
        assert n["c"] == 2  # one transient failure, then success
        # a transient error is retried with the SAME turn -- no schema/grounding correction appended
        assert seen_users[1] == "ORIG"
        # and it backed off once (before the second attempt) rather than re-firing instantly
        assert slept == [8.0]

    def test_every_attempt_transient_reraises_the_transient_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If every attempt hits a transient error, the last one is surfaced (failing the stage) --
        the caller never receives a value that was never produced, and the error type is preserved."""
        import app.agentdesk.grounding as grounding

        n = {"c": 0}

        def fake(*, role, system, user, output_format, model, settings, budget, effort="high"):  # type: ignore[no-untyped-def]
            n["c"] += 1
            raise AgentTransientError("is_error=true")

        monkeypatch.setattr(grounding, "call_structured", fake)
        with pytest.raises(AgentTransientError):
            run_grounded(
                role="risk_aggressive", system="sys", user="u", output_format=_Answer,
                prose_of=_prose_of, pack=self._pack(), settings=Settings(),
                budget=AgentBudget(cap_usd=Decimal("5.00")), max_attempts=3,
                sleep=lambda _: None,
            )
        assert n["c"] == 3


# ---------------------------------------------------------------------------
# render_pack
# ---------------------------------------------------------------------------


class TestRenderPack:
    def test_empty_pack_carries_the_anti_fabrication_sentence(self) -> None:
        pack = EvidencePack(symbol="AAPL", sections=(EvidenceSection(title="Price"),))
        rendered = evidence.render_pack(pack)
        assert "Do not estimate or fabricate values" in rendered

    def test_a_populated_pack_renders_items_and_warnings(self) -> None:
        section = EvidenceSection(
            title="Price",
            items=(EvidenceItem(key="close", label="Close", value="100.00", unit="USD", as_of="2026-08-01", source="yahoo"),),
            text="Verified snapshot.",
        )
        pack = EvidencePack(symbol="AAPL", sections=(section,), warnings=("news unavailable for AAPL: timeout",))
        rendered = evidence.render_pack(pack)
        assert "## Price" in rendered
        assert "Close: 100.00 USD (as of 2026-08-01, source yahoo)" in rendered
        assert "Verified snapshot." in rendered
        assert "## Warnings" in rendered
        assert "news unavailable for AAPL: timeout" in rendered


class TestEvidenceFailSoft:
    def test_build_pack_never_raises_when_the_data_layer_is_down(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        def _boom(*args: object, **kwargs: object) -> object:
            raise ProviderUnavailable("yahoo is down", provider="yahoo")

        monkeypatch.setattr(evidence.store, "ensure_series", _boom)
        settings = Settings(data_dir=tmp_path / "data")
        pack = evidence.build_pack("AAPL", None, settings=settings, sections=("price",))
        assert pack.is_empty
        assert any("AAPL" in w for w in pack.warnings)

    def test_build_pack_rejects_an_unknown_section(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        with pytest.raises(ValueError):
            evidence.build_pack("AAPL", None, settings=settings, sections=("not-a-real-section",))

    def test_default_indicators_parse_against_the_real_registry(self) -> None:
        from app.indicators import registry as indicator_registry

        for spec_text in evidence.DEFAULT_INDICATORS:
            indicator_registry.request(spec_text)  # must not raise

    def test_section_keys_matches_the_documented_set(self) -> None:
        # The first seven are pinned *in order*: every desk preset names its sections explicitly, so
        # a reordering here would silently change what each stage reads. `live_quote` and `intraday`
        # (the two look-ahead-gated live sections) are appended after them for that reason -- see
        # `SECTION_KEYS`' own comment and `tests/test_agentdesk_live_evidence.py`.
        assert evidence.SECTION_KEYS == (
            "price", "indicators", "news", "social", "fundamentals", "macro", "events",
            "live_quote", "intraday",
        )


# ---------------------------------------------------------------------------
# RunStore
# ---------------------------------------------------------------------------


def _sample_run(run_id: str = "run-1") -> DeskRun:
    return DeskRun(
        run_id=run_id,
        kind="tradingagents",
        created_at=dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
        budget=AgentBudget(cap_usd=Decimal("5.00")),
        stages=(StageRecord(stage_id="market_analyst", role="market_analyst", label="Market Analyst"),),
    )


class TestRunStore:
    def test_round_trip(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        run_store = RunStore(settings, "tradingagents")
        run = _sample_run()

        run_store.save(run)
        loaded = run_store.load(run.run_id)

        assert loaded == run

    def test_load_missing_run_returns_none(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        run_store = RunStore(settings, "tradingagents")
        assert run_store.load("no-such-run") is None

    def test_list_runs_skips_a_corrupt_file_and_returns_the_rest(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        run_store = RunStore(settings, "tradingagents")

        good_older = _sample_run("run-older")
        good_older = good_older.model_copy(update={"created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC)})
        good_newer = _sample_run("run-newer")
        good_newer = good_newer.model_copy(update={"created_at": dt.datetime(2026, 6, 1, tzinfo=dt.UTC)})
        run_store.save(good_older)
        run_store.save(good_newer)

        from app.agentdesk.models import run_dir

        corrupt_dir = run_dir(settings, "tradingagents", "run-corrupt")
        corrupt_dir.mkdir(parents=True, exist_ok=True)
        (corrupt_dir / "run.json").write_text("{not valid json", encoding="utf-8")

        listed = run_store.list_runs()
        ids = [run.run_id for run in listed]
        assert "run-corrupt" not in ids
        assert ids == ["run-newer", "run-older"]  # newest first

    def test_delete_returns_false_for_an_unknown_run(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        run_store = RunStore(settings, "tradingagents")
        assert run_store.delete("nope") is False

    def test_delete_removes_a_saved_run(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        run_store = RunStore(settings, "tradingagents")
        run = _sample_run()
        run_store.save(run)

        assert run_store.delete(run.run_id) is True
        assert run_store.load(run.run_id) is None


class TestWithStage:
    def test_replaces_the_named_stage_immutably(self) -> None:
        run = _sample_run()
        updated = with_stage(run, "market_analyst", state="succeeded", output_md="report text")

        assert updated is not run
        assert updated.stages[0].state == "succeeded"
        assert updated.stages[0].output_md == "report text"
        # the original run is untouched -- frozen models, replace rather than mutate
        assert run.stages[0].state == "pending"
        assert run.stages[0].output_md == ""

    def test_unknown_stage_id_raises_key_error(self) -> None:
        run = _sample_run()
        with pytest.raises(KeyError):
            with_stage(run, "no-such-stage", state="failed")


# ---------------------------------------------------------------------------
# DeskRegistry
# ---------------------------------------------------------------------------


class TestDeskRegistry:
    def test_second_start_for_the_same_kind_raises_run_already_active(self) -> None:
        registry = DeskRegistry()
        started = threading.Event()
        release = threading.Event()

        def worker(cancel_event: threading.Event) -> None:
            started.set()
            release.wait(timeout=5)

        registry.start("tradingagents", "run-a", worker)
        assert started.wait(timeout=5)

        with pytest.raises(RunAlreadyActive):
            registry.start("tradingagents", "run-b", worker)

        assert registry.active("tradingagents") == "run-a"

        release.set()
        registry.join("run-a", timeout=5)
        assert registry.active("tradingagents") is None

    def test_the_other_kind_is_not_blocked(self) -> None:
        registry = DeskRegistry()
        release_a = threading.Event()
        started_b = threading.Event()

        def worker_a(cancel_event: threading.Event) -> None:
            release_a.wait(timeout=5)

        def worker_b(cancel_event: threading.Event) -> None:
            started_b.set()

        registry.start("tradingagents", "run-a", worker_a)
        registry.start("vibedesk", "run-b", worker_b)

        assert started_b.wait(timeout=5)
        registry.join("run-b", timeout=5)
        assert registry.active("vibedesk") is None
        assert registry.active("tradingagents") == "run-a"

        release_a.set()
        registry.join("run-a", timeout=5)

    def test_cancel_sets_the_event_the_worker_observes(self) -> None:
        registry = DeskRegistry()
        observed_cancel = threading.Event()

        def worker(cancel_event: threading.Event) -> None:
            if cancel_event.wait(timeout=5):
                observed_cancel.set()

        registry.start("tradingagents", "run-c", worker)
        assert registry.cancel("run-c") is True
        registry.join("run-c", timeout=5)

        assert observed_cancel.is_set()
        assert registry.cancelled("run-c") is True

    def test_cancel_and_cancelled_are_false_for_an_unknown_run(self) -> None:
        registry = DeskRegistry()
        assert registry.cancel("never-started") is False
        assert registry.cancelled("never-started") is False

    def test_a_worker_exception_does_not_escape_and_frees_the_slot(self) -> None:
        registry = DeskRegistry()

        def worker(cancel_event: threading.Event) -> None:
            raise RuntimeError("boom")

        registry.start("tradingagents", "run-d", worker)
        registry.join("run-d", timeout=5)
        assert registry.active("tradingagents") is None


def test_registry_singleton_is_process_wide() -> None:
    assert jobs.registry() is jobs.registry()
