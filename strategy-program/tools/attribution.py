"""Which trades actually produced a card's result, and how it compared to SPY.

A results table says a card returned +17.37% against a benchmark of -56.23%. It does not say whether
that came from ninety small wins or from one position that happened to be held through the right
fortnight. Those are different strategies wearing the same number, and only the second is fragile.

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe \\
        strategy-program/tools/attribution.py \\
        --results data/rounds/r2-2026-08/results --agent c11-breakout

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name.

**Contribution is exact, not apportioned.** Every trade's ``pnl`` is in currency against a known
``starting_equity``, and the trade log is complete: summing every ``pnl`` reproduces
``ending_equity - starting_equity`` to the cent. So ``pnl / starting_equity`` is that trade's share of
the card's return, and the shares sum to the return itself. Nothing here is modelled or allocated.

**Unrealised marks are separated from realised ones.** A position still open when the window closed
carries ``exit_reason == "open_at_end"``, and its ``pnl`` is a mark against the last session's close
rather than money taken. A card whose result rests on an open mark has not demonstrated the same thing
as one that closed its winners, and the concentration figures below split the two.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.tournament.models import AgentResult, RealisedTrade

__all__ = [
    "TradeContribution",
    "WindowAttribution",
    "attribute_window",
    "load_window",
    "render_agent_markdown",
]

#: A trade contributing at least this share of starting equity is called out individually. 1% of the
#: book is the level at which a single position visibly moves a card's headline number; below it the
#: list becomes a transaction log rather than an explanation.
MATERIAL_CONTRIBUTION = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class TradeContribution:
    """One trade's exact share of its card's return in one window."""

    trade: RealisedTrade
    contribution: Decimal
    """``pnl / starting_equity`` -- signed, and summing to the card's total return across trades."""

    unrealised: bool
    """True when the position was still open at the window's end, so `contribution` is a mark."""

    @property
    def symbol(self) -> str:
        return self.trade.symbol

    @property
    def held_bars(self) -> int:
        return self.trade.bars_held


@dataclass(frozen=True, slots=True)
class WindowAttribution:
    """What produced one card's result in one window, and how it compared to the benchmark."""

    agent_id: str
    window: str
    sessions: int
    starting_equity: Decimal
    ending_equity: Decimal
    total_return: Decimal
    benchmark_return: Decimal | None
    capital_exposure: Decimal | None
    max_drawdown: Decimal
    contributions: tuple[TradeContribution, ...]
    """Every trade, sorted by absolute contribution descending."""

    @property
    def excess(self) -> Decimal | None:
        """Return minus the benchmark -- what a reader means by "did it beat SPY"."""
        if self.benchmark_return is None:
            return None
        return self.total_return - self.benchmark_return

    @property
    def adjusted_excess(self) -> Decimal | None:
        """Return minus a passive benchmark position of this card's own size. See `score.py`."""
        if self.benchmark_return is None or self.capital_exposure is None:
            return None
        return self.total_return - self.capital_exposure * self.benchmark_return

    @property
    def winners(self) -> tuple[TradeContribution, ...]:
        return tuple(c for c in self.contributions if c.contribution > 0)

    @property
    def losers(self) -> tuple[TradeContribution, ...]:
        return tuple(c for c in self.contributions if c.contribution < 0)

    @property
    def material(self) -> tuple[TradeContribution, ...]:
        """Trades moving at least `MATERIAL_CONTRIBUTION` of the book, either direction."""
        return tuple(
            c for c in self.contributions if abs(c.contribution) >= MATERIAL_CONTRIBUTION
        )

    def top_share(self, n: int) -> Decimal | None:
        """Share of *gross winning* P&L produced by the ``n`` largest winners.

        Gross winning rather than net: a card can have a small net result from large offsetting
        winners and losers, and dividing by the net would produce a meaningless ratio -- or a
        division by zero. `None` when the card had no winners at all.
        """
        gross_win = sum((c.contribution for c in self.winners), start=Decimal(0))
        if gross_win == 0:
            return None
        top = sum((c.contribution for c in self.winners[:n]), start=Decimal(0))
        return top / gross_win

    def without(self, n: int) -> Decimal:
        """The card's return with its ``n`` largest *winners* removed.

        The counterfactual a reader actually wants: strip the trades that made the number and see
        what is left. This is arithmetic on the realised log, not a re-simulation -- removing a
        position would in reality have freed capital and changed later fills, so read it as "how much
        of the result sat in these trades", never as "what the card would have returned".
        """
        removed = sum((c.contribution for c in self.winners[:n]), start=Decimal(0))
        return self.total_return - removed

    @property
    def unrealised_share(self) -> Decimal:
        """Share of the card's return still sitting in positions open at the window's end."""
        return sum(
            (c.contribution for c in self.contributions if c.unrealised), start=Decimal(0)
        )


def load_window(results_root: Path, window: str, agent_id: str) -> AgentResult | None:
    """One card's result in one window, or `None` when it did not run there."""
    matches = sorted((results_root / window / "runs").glob(f"*-{agent_id}.json"))
    if not matches:
        return None
    return AgentResult.model_validate_json(matches[0].read_text(encoding="utf-8"))


def attribute_window(result: AgentResult, window: str) -> WindowAttribution:
    """Decompose one card-window result into its per-trade contributions."""
    starting = result.starting_equity
    contributions = [
        TradeContribution(
            trade=t,
            contribution=t.pnl / starting,
            unrealised=t.exit_reason == "open_at_end",
        )
        for t in result.trades
    ]
    contributions.sort(key=lambda c: abs(c.contribution), reverse=True)
    return WindowAttribution(
        agent_id=result.card.agent_id,
        window=window,
        sessions=result.sessions,
        starting_equity=starting,
        ending_equity=result.ending_equity,
        total_return=result.ending_equity / starting - 1,
        benchmark_return=result.benchmark_return,
        capital_exposure=(
            Decimal(str(result.capital_exposure))
            if getattr(result, "capital_exposure", None) is not None
            else None
        ),
        max_drawdown=result.max_drawdown,
        contributions=tuple(contributions),
    )


def _pct(value: Decimal | None, places: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.{places}f}%"


def _money(value: Decimal) -> str:
    return f"{value:+,.0f}"


def render_agent_markdown(attributions: list[WindowAttribution], *, top_n: int = 3) -> str:
    """A per-agent section: benchmark comparison per window, then what drove each result."""
    if not attributions:
        return "_No windows run._\n"

    agent = attributions[0].agent_id
    out: list[str] = [f"## `{agent}` — versus SPY, and what moved the number\n"]

    out.append("| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |")
    out.append("|---|---|---|---|---|---|---|---|")
    for a in attributions:
        out.append(
            f"| `{a.window}` | {a.sessions} | **{_pct(a.total_return)}** | {_pct(a.benchmark_return)} "
            f"| {_pct(a.excess)} | {_pct(a.adjusted_excess)} | "
            f"{'n/a' if a.capital_exposure is None else f'{a.capital_exposure * 100:.1f}%'} "
            f"| {_pct(a.max_drawdown)} |"
        )
    out.append("")

    for a in attributions:
        out.append(f"### `{a.window}`\n")
        if not a.contributions:
            out.append("Took no trades in this window.\n")
            continue

        share = a.top_share(top_n)
        out.append(
            f"{len(a.contributions)} trades. Card **{_pct(a.total_return)}** against SPY "
            f"**{_pct(a.benchmark_return)}** — excess **{_pct(a.excess)}**."
        )
        if share is not None:
            out.append(
                f" The {top_n} largest winners produced **{share * 100:.0f}%** of gross winning P&L; "
                f"without them the card returns **{_pct(a.without(top_n))}**."
            )
        if a.unrealised_share != 0:
            out.append(
                f" **{_pct(a.unrealised_share)}** of the return sits in positions still open at the "
                f"window's close — a mark, not money taken."
            )
        out.append("")

        shown = a.material or a.contributions[:top_n]
        out.append("| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |")
        out.append("|---|---|---|---|---|---|---|---|")
        for c in shown:
            t = c.trade
            exit_date = t.exit_date.isoformat() if t.exit_date else "_open_"
            reason = f"**{t.exit_reason}**" if c.unrealised else t.exit_reason
            out.append(
                f"| {t.symbol} | {t.entry_date.isoformat()} | {exit_date} | {t.bars_held} "
                f"| {reason} | {_pct(t.return_pct)} | {_money(t.pnl)} | {_pct(c.contribution)} |"
            )
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument(
        "--agent", action="append", default=None, help="agent_id; repeatable, default all"
    )
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    windows = [p.name for p in sorted(args.results.iterdir()) if (p / "runs").is_dir()]
    if not windows:
        print(f"no window directories with a runs/ folder under {args.results}")
        return 1

    agents = args.agent
    if not agents:
        seen: set[str] = set()
        for w in windows:
            for f in (args.results / w / "runs").glob("*.json"):
                seen.add(f.stem.split("-", 1)[1])
        agents = sorted(seen)

    payload: dict[str, list[dict[str, object]]] = {}
    for agent in agents:
        attributions = [
            attribute_window(r, w)
            for w in windows
            if (r := load_window(args.results, w, agent)) is not None
        ]
        if not attributions:
            continue
        print(render_agent_markdown(attributions, top_n=args.top))
        payload[agent] = [
            {
                "window": a.window,
                "total_return": str(a.total_return),
                "benchmark_return": None if a.benchmark_return is None else str(a.benchmark_return),
                "excess": None if a.excess is None else str(a.excess),
                "adjusted_excess": None if a.adjusted_excess is None else str(a.adjusted_excess),
                "capital_exposure": None
                if a.capital_exposure is None
                else str(a.capital_exposure),
                "unrealised_share": str(a.unrealised_share),
                "top3_share_of_gross_wins": None
                if a.top_share(args.top) is None
                else str(a.top_share(args.top)),
                "return_without_top3_winners": str(a.without(args.top)),
                "trades": [
                    {
                        "symbol": c.trade.symbol,
                        "entry_date": c.trade.entry_date.isoformat(),
                        "exit_date": None
                        if c.trade.exit_date is None
                        else c.trade.exit_date.isoformat(),
                        "bars_held": c.trade.bars_held,
                        "exit_reason": c.trade.exit_reason,
                        "return_pct": str(c.trade.return_pct),
                        "pnl": str(c.trade.pnl),
                        "contribution": str(c.contribution),
                        "unrealised": c.unrealised,
                    }
                    for c in a.contributions
                ],
            }
            for a in attributions
        ]

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
