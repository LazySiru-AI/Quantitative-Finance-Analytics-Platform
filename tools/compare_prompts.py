"""Paired before/after harness for prompt-compression changes to the Trading Agents pipeline and the
`followup_review` Vibe Trading preset.

**Why this exists.** A prompt-compression change is only shippable if it provably does not change any
downstream decision -- see `docs/reports/prompt-compression-comparison.md` for the protocol this
script implements. This module never scores a compression change as "good"; it only proves (or
disproves) that two runs over the *same* fixed evidence -- one on the prompts at a baseline git ref,
one on the prompts in the current working tree -- reached the same decisions, while reporting the
token delta between them.

**Baseline-selection mechanism: `--baseline-ref`.** The candidate side always runs the working tree's
own `app.tradingagents.prompts.SYSTEM_FOR_ROLE` and `backend/app/vibedesk/presets/followup_review.json`
exactly as imported. The baseline side reads the prior version of both files out of git via
`git show <ref>:<path>`, execs the prompts module in an isolated namespace to recover its
`SYSTEM_FOR_ROLE` dict, and parses the preset JSON directly -- then monkeypatches those two objects in
for the duration of the baseline run only. This is the mechanism described in the task brief as the
"cleanest": no second checkout, no second venv, and the working tree is never touched. (Its
alternative -- two separately-edited prompt-module file paths passed on the command line -- was not
implemented; state that clearly if you extend this script.)

**HARD CONSTRAINT: dry-run by default, zero model calls.** `main()` never calls
`app.tradingagents.service.start_run` or `app.vibedesk.service.start_run` unless invoked with
`--live`, and `--live` additionally requires an explicit `--budget-usd` (the whole comparison's cap,
split evenly across the two sides' two child desks). Running `--live` is a decision for a human with
a wallet, not for this script's own defaults -- see `main`'s own docstring.

**The four invariance conditions** (see the module docstring in `docs/reports/prompt-compression-
comparison.md` for the full protocol):

1. Identical `final_rating` (TA), identical `VERDICT:` value (Vibe), identical pass/fail for all four
   `app.workflow.pipeline.ALL_ARMS` gates -- checked by `compare_sides` via
   `app.workflow.pipeline._passes_gate` itself, never a reimplementation of that logic.
2. Every decision-bearing field still present and semantically unchanged, not merely shorter --
   `compare_sides` cannot automate a semantic judgement, so it emits `ComparisonReport.field_dump`,
   a side-by-side of every decision-bearing field, for a human to read.
3. `GroundingVerdict.ok` still true on the candidate side, with no new grounding retries (an
   `attempts` count that rose over the baseline's own).
4. `checked_tokens` does not collapse toward zero, checked as a ratio against the baseline's own count
   (`--min-checked-token-ratio`, default 0.5) -- a compression change that strips the quantitative
   content out of a stage rather than the padding would show up here even if condition 1 still passed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

from app.agentdesk import evidence  # noqa: E402
from app.agentdesk.models import DeskRun, GroundingVerdict  # noqa: E402
from app.config import Settings  # noqa: E402
from app.tradingagents import pipeline as ta_pipeline  # noqa: E402
from app.tradingagents import prompts as ta_prompts  # noqa: E402
from app.tradingagents import service as ta_service  # noqa: E402
from app.vibedesk import presets as vibe_presets  # noqa: E402
from app.vibedesk import runtime as vibe_runtime  # noqa: E402
from app.vibedesk import service as vibe_service  # noqa: E402
from app.workflow import pipeline as wf_pipeline  # noqa: E402
from app.workflow import verdict as wf_verdict  # noqa: E402

#: `app.agentdesk.telemetry` may not exist yet in a concurrently-developing tree (see the task brief
#: this script was built against). Imported softly so every code path that does not need token/cost
#: aggregation -- argument parsing, the dry-run plan, the comparison logic -- keeps working without it.
try:
    from app.agentdesk import telemetry as agent_telemetry
except ImportError:  # pragma: no cover - exercised by test_compare_prompts when telemetry.py is absent
    agent_telemetry = None  # type: ignore[assignment]

__all__ = [
    "TELEMETRY_AVAILABLE",
    "BaselineLoadError",
    "ComparisonReport",
    "LiveExecutionUnavailable",
    "SideResult",
    "StageGrounding",
    "build_plan",
    "compare_sides",
    "evidence_fingerprint",
    "load_baseline_preset",
    "load_baseline_prompts",
    "main",
    "parse_args",
    "render_report",
    "run_one_side",
    "ta_service",
    "vibe_service",
]

TELEMETRY_AVAILABLE = agent_telemetry is not None

#: The Vibe preset this harness compares -- fixed, per the task brief's pipelines-to-run list.
VIBE_PRESET_NAME = "followup_review"
PROMPTS_REL_PATH = "backend/app/tradingagents/prompts.py"
PRESET_REL_PATH = "backend/app/vibedesk/presets/followup_review.json"

#: The evidence sections the TA pipeline's debate/judge/trader/risk/portfolio stages all share --
#: mirrors `app.tradingagents.pipeline._UNION_SECTIONS` exactly (imported, not retyped, so this
#: fingerprint can never silently drift from what the pipeline itself actually builds).
_UNION_SECTIONS = ta_pipeline._UNION_SECTIONS

#: How long a live child run may run before this harness gives up waiting on it.
_CHILD_TIMEOUT_S = 15 * 60
_CHILD_POLL_S = 2.0
_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="compare_prompts.py",
        description=(
            "Paired before/after comparison of the Trading Agents pipeline and the followup_review "
            "Vibe preset, for proving a prompt-compression change is decision-invariant. Defaults to "
            "a dry run that makes zero model calls."
        ),
    )
    parser.add_argument("--symbol", default="AAPL", help="Fixed instrument for both sides (default: AAPL).")
    parser.add_argument(
        "--trade-date",
        required=True,
        type=_parse_date,
        help=(
            "Fixed ISO trade date (YYYY-MM-DD), backed by STORED historical data. Required, not "
            "defaulted, so the fixture can never silently drift to 'the latest stored session' -- see "
            "the determinism requirement in docs/reports/prompt-compression-comparison.md."
        ),
    )
    parser.add_argument(
        "--baseline-ref",
        default="HEAD",
        help=(
            "Git ref to read the PRIOR prompts.py and followup_review.json from (default: HEAD, i.e. "
            "the last commit, compared against the current working tree as the candidate)."
        ),
    )
    parser.add_argument(
        "--question",
        default="",
        help="The follow-up question text for the Vibe preset's {question} variable.",
    )
    parser.add_argument(
        "--min-checked-token-ratio",
        type=float,
        default=0.5,
        help=(
            "Condition 4's floor: candidate checked_tokens must be at least this fraction of the "
            "baseline's own (default 0.5) -- guards against compression stripping quantitative "
            "content rather than padding."
        ),
    )
    parser.add_argument(
        "--child-timeout-min",
        type=float,
        default=15.0,
        help=(
            "How long (minutes) to wait for each child desk run to reach a terminal state before "
            "giving up (default: 15). A grounding-retry-heavy TA run under API rate-limiting can take "
            "35-45 min; raise this (e.g. 50) when retrying during a low-load window."
        ),
    )
    parser.add_argument(
        "--ta-only",
        action="store_true",
        help=(
            "Run only the Trading Agents pipeline on both sides, skipping the Vibe preset. Use when "
            "the preset has no recoverable baseline at --baseline-ref (e.g. it was never committed), "
            "so git show would fail. The TA pipeline is the dominant cost and its baseline is "
            "recoverable, so this still yields the headline output-token measurement."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Actually make model calls (spends real money). Requires --budget-usd. Without this flag "
            "the script only prints the plan it would run and exits 0."
        ),
    )
    parser.add_argument(
        "--budget-usd",
        type=_parse_positive_decimal,
        default=None,
        help=(
            "Required with --live: the WHOLE comparison's spend cap, split evenly across the two "
            "sides' two child desks (TA + Vibe) each. A stated budget is the human's decision, not "
            "this script's default."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Worker model override passed to both child desks (default: each desk's own default).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override Settings.data_dir (default: the application's own default data directory).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Path to write the human-readable comparison report to, in --live mode (default: stdout only).",
    )

    args = parser.parse_args(argv)
    if args.live and args.budget_usd is None:
        parser.error("--live requires --budget-usd (an explicit, human-stated spend cap)")
    if not args.live and args.budget_usd is not None:
        parser.error("--budget-usd has no effect without --live; pass --live to actually spend it")
    return args


def _parse_date(raw: str) -> dt.date:
    try:
        return dt.date.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO date (YYYY-MM-DD): {raw!r}") from exc


def _parse_positive_decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"not a decimal: {raw!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"--budget-usd must be positive, got {raw!r}")
    return value


# ---------------------------------------------------------------------------
# The dry-run plan
# ---------------------------------------------------------------------------


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    """Everything this invocation WOULD run, with zero side effects. Printed verbatim by the dry-run
    path in `main`, and used by the smoke test to assert the dry run never reaches a model call."""
    per_child_budget = None
    if args.budget_usd is not None:
        # Two sides (baseline, candidate) x two child desks (TA, Vibe) each = four child runs.
        per_child_budget = str((args.budget_usd / 4).quantize(Decimal("0.0001")))
    return {
        "mode": "live" if args.live else "dry_run",
        "ta_only": bool(args.ta_only),
        "fixture": {
            "symbol": args.symbol,
            "trade_date": args.trade_date.isoformat(),
            "question": args.question or "(preset default)",
        },
        "baseline_selection_mechanism": "git-ref",
        "baseline_ref": args.baseline_ref,
        "sides": [
            {
                "label": "baseline",
                "prompts_source": f"git show {args.baseline_ref}:{PROMPTS_REL_PATH}",
                "preset_source": f"git show {args.baseline_ref}:{PRESET_REL_PATH}",
                "runs": ["tradingagents.pipeline (14-stage TA run)", f"vibedesk preset '{VIBE_PRESET_NAME}'"],
            },
            {
                "label": "candidate",
                "prompts_source": "working tree: app.tradingagents.prompts.SYSTEM_FOR_ROLE",
                "preset_source": f"working tree: {PRESET_REL_PATH}",
                "runs": ["tradingagents.pipeline (14-stage TA run)", f"vibedesk preset '{VIBE_PRESET_NAME}'"],
            },
        ],
        "budget_usd_total": str(args.budget_usd) if args.budget_usd is not None else None,
        "budget_usd_per_child_run": per_child_budget,
        "invariance_conditions_checked": [
            "1. identical TA final_rating, identical Vibe VERDICT, identical pass/fail on all four "
            "app.workflow.pipeline.ALL_ARMS gates (via _passes_gate itself)",
            "2. side-by-side field dump emitted for human review (not automated)",
            "3. GroundingVerdict.ok true on the candidate side, no attempts increase over baseline",
            f"4. candidate checked_tokens >= {args.min_checked_token_ratio} x baseline checked_tokens",
        ],
        "will_make_model_calls": bool(args.live),
    }


# ---------------------------------------------------------------------------
# Baseline prompt/preset loading from git
# ---------------------------------------------------------------------------


class BaselineLoadError(RuntimeError):
    """`git show <ref>:<path>` failed, or the content it returned did not parse."""


def _git_show(ref: str, rel_path: str, *, repo_root: Path = REPO_ROOT) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel_path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BaselineLoadError(
            f"git show {ref}:{rel_path} failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def load_baseline_prompts(ref: str, *, repo_root: Path = REPO_ROOT) -> ModuleType:
    """The `app.tradingagents.prompts` module as it existed at `ref`, executed in an isolated
    namespace -- never imported into `sys.modules`, so it cannot shadow the working tree's own copy
    for anything else running in this process."""
    source = _git_show(ref, PROMPTS_REL_PATH, repo_root=repo_root)
    module = ModuleType(f"_compare_prompts_baseline_{ref!r}")
    try:
        exec(compile(source, f"<git:{ref}:{PROMPTS_REL_PATH}>", "exec"), module.__dict__)
    except Exception as exc:
        raise BaselineLoadError(f"baseline prompts.py at {ref!r} failed to exec: {exc}") from exc
    if not hasattr(module, "SYSTEM_FOR_ROLE"):
        raise BaselineLoadError(f"baseline prompts.py at {ref!r} has no SYSTEM_FOR_ROLE")
    return module


def load_baseline_preset(ref: str, *, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The `followup_review.json` preset as it existed at `ref`, parsed but not yet validated as a
    `Preset` -- `_run_side` hands this to `app.vibedesk.presets._parse_preset` at call time."""
    source = _git_show(ref, PRESET_REL_PATH, repo_root=repo_root)
    try:
        data: dict[str, Any] = json.loads(source)
    except json.JSONDecodeError as exc:
        raise BaselineLoadError(f"baseline followup_review.json at {ref!r} did not parse as JSON: {exc}") from exc
    return data


# ---------------------------------------------------------------------------
# Evidence determinism
# ---------------------------------------------------------------------------


def evidence_fingerprint(symbol: str, trade_date: dt.date, *, settings: Settings) -> str:
    """SHA-256 of the rendered evidence pack the debate/judge/trader/risk/portfolio stages share, for
    `(symbol, trade_date)`. Evidence assembly does not depend on which prompts module is active, so
    this must come out byte-identical for both sides of a real comparison -- `_run_side` asserts that
    and aborts loudly if it ever does not, per the determinism requirement."""
    pack = evidence.build_pack(symbol, trade_date, settings=settings, sections=_UNION_SECTIONS)
    rendered = evidence.render_pack(pack)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageGrounding:
    """One stage's grounding outcome, carried out of a `DeskRun.stages` entry."""

    stage_id: str
    ok: bool
    attempts: int
    checked_tokens: int


@dataclass(frozen=True)
class SideResult:
    """Everything `compare_sides` needs from one side (baseline or candidate) of the comparison.

    Built from real `DeskRun`s in `--live` mode; built by hand from scripted values in the smoke test,
    which is exactly why this is a plain, easily-constructed dataclass rather than something wired
    only to the live path.
    """

    label: str
    symbol: str
    trade_date: dt.date

    ta_run_id: str = ""
    ta_state: str = ""
    ta_final_rating: str = ""
    ta_final_md: str = ""
    ta_stage_grounding: tuple[StageGrounding, ...] = ()
    ta_fields: dict[str, str] = field(default_factory=dict)
    """Decision-bearing fields for condition 2's human field dump: rating, recommendation, entry,
    stop, sizing, thesis-equivalent (investment_thesis), price_target, time_horizon."""

    vibe_run_id: str = ""
    vibe_state: str = ""
    vibe_verdict: wf_verdict.VibeVerdict = "INCONCLUSIVE"
    vibe_verdict_explicit: bool = False
    vibe_final_md: str = ""
    vibe_stage_grounding: tuple[StageGrounding, ...] = ()
    vibe_fields: dict[str, str] = field(default_factory=dict)
    """Decision-bearing fields for the Vibe side's field dump: the supporting/skeptical/referee
    summaries and the parsed verdict."""

    call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: Decimal = Decimal(0)

    @property
    def total_checked_tokens(self) -> int:
        return sum(g.checked_tokens for g in (*self.ta_stage_grounding, *self.vibe_stage_grounding))

    @property
    def all_grounding_ok(self) -> bool:
        return all(g.ok for g in (*self.ta_stage_grounding, *self.vibe_stage_grounding))


def _stage_groundings(run: DeskRun) -> tuple[StageGrounding, ...]:
    out: list[StageGrounding] = []
    for stage in run.stages:
        v: GroundingVerdict | None = stage.grounding
        if v is None:
            continue
        out.append(StageGrounding(stage_id=stage.stage_id, ok=v.ok, attempts=v.attempts, checked_tokens=v.checked_tokens))
    return tuple(out)


def _ta_fields(run: DeskRun) -> dict[str, str]:
    """The portfolio manager's final stage, plus the trader's proposal stage -- together these carry
    every decision-bearing field named in condition 2 (rating, recommendation lives in final_md,
    entry/stop/sizing, thesis)."""
    fields: dict[str, str] = {"final_rating": run.final_rating}
    for stage in run.stages:
        if stage.stage_id in ("trader", "portfolio_manager"):
            fields[f"{stage.stage_id}_output_md"] = stage.output_md
    return fields


def _vibe_fields(run: DeskRun) -> dict[str, str]:
    verdict, explicit = wf_verdict.parse_verdict(run.final_md)
    fields: dict[str, str] = {"verdict": verdict, "verdict_was_explicit": str(explicit)}
    for stage in run.stages:
        fields[f"{stage.stage_id}_output_md"] = stage.output_md
    return fields


# ---------------------------------------------------------------------------
# Live execution (never called except by --live)
# ---------------------------------------------------------------------------


class LiveExecutionUnavailable(RuntimeError):
    """Raised instead of running anything when a live prerequisite (telemetry, in particular) is
    missing, so the failure names exactly what to fix rather than a bare traceback."""


def _await_terminal(kind: str, run_id: str, *, settings: Settings, timeout_s: float = _CHILD_TIMEOUT_S) -> DeskRun:
    """Poll a child run's own store snapshot until it reaches a terminal state or this harness's own
    timeout -- the same polling contract `app.workflow.pipeline._await_child` uses for its children,
    reimplemented locally (rather than imported) because that function also owns cancellation
    plumbing this harness has no run of its own to cancel."""
    from app.agentdesk.store import RunStore

    store = RunStore(settings, kind)  # type: ignore[arg-type]
    deadline = time.monotonic() + timeout_s
    while True:
        run = store.load(run_id)
        if run is not None and run.state in _TERMINAL_STATES:
            return run
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{kind} run {run_id} did not finish within {timeout_s:.0f}s")
        time.sleep(_CHILD_POLL_S)


@dataclass
class _TARequest:
    symbol: str
    trade_date: dt.date | None
    analysts: list[str] | None
    debate_rounds: int | None
    risk_rounds: int | None
    budget_usd: str | None
    model: str | None


def run_one_side(
    label: str,
    args: argparse.Namespace,
    *,
    settings: Settings,
    prompts_module: ModuleType | None,
    preset_data: dict[str, Any] | None,
    per_child_budget_usd: Decimal,
    ta_only: bool = False,
) -> SideResult:
    """Run both child desks for one side of the comparison and fold the results into a `SideResult`.

    `prompts_module=None` / `preset_data=None` means "use the working tree as imported" (the
    candidate side); a non-`None` value means "monkeypatch this in for the duration of this call, then
    restore" (the baseline side). Monkeypatching is scoped to this function's own try/finally, never
    left in place afterward, so the two sides' calls in the same process never bleed into each other.

    Two separate names have to be patched for the preset override, not one: `app.vibedesk.service.
    start_run` calls `load_preset` once (its own imported name) to validate the request and build the
    stage plan, but the actual worker run happens on a registry thread inside `app.vibedesk.runtime.
    run_swarm`, which re-resolves the preset through *its own* imported `load_preset` name from the
    bare `config.preset_name` string. Patching only the former changes the stage labels but not a
    single system prompt the worker actually sends -- see each module's own `from app.vibedesk.presets
    import ... load_preset` line.

    Never called from a dry run -- `main` only reaches this function when `args.live` is true.
    """
    if agent_telemetry is None:
        raise LiveExecutionUnavailable(
            "app.agentdesk.telemetry is not importable; cannot summarize token/cost totals. "
            "This module has not landed yet in the working tree -- rerun once it has."
        )

    original_system_for_role = ta_prompts.SYSTEM_FOR_ROLE
    original_service_load_preset = vibe_service.load_preset  # type: ignore[attr-defined]
    original_runtime_load_preset = vibe_runtime.load_preset  # type: ignore[attr-defined]
    try:
        if prompts_module is not None:
            ta_prompts.SYSTEM_FOR_ROLE = prompts_module.SYSTEM_FOR_ROLE
        if preset_data is not None:
            baseline_preset = vibe_presets._parse_preset(VIBE_PRESET_NAME, preset_data)

            def _load_preset_override(name: str) -> Any:
                if name == VIBE_PRESET_NAME:
                    return baseline_preset
                return original_service_load_preset(name)

            vibe_service.load_preset = _load_preset_override  # type: ignore[attr-defined]
            vibe_runtime.load_preset = _load_preset_override  # type: ignore[attr-defined]

        ta_req = _TARequest(
            symbol=args.symbol,
            trade_date=args.trade_date,
            analysts=None,
            debate_rounds=None,
            risk_rounds=None,
            budget_usd=str(per_child_budget_usd),
            model=args.model,
        )
        child_timeout_s = float(getattr(args, "child_timeout_min", 15.0)) * 60.0
        ta_run = ta_service.start_run(ta_req, settings=settings)
        ta_run = _await_terminal("tradingagents", ta_run.run_id, settings=settings, timeout_s=child_timeout_s)

        vibe_run = None
        if not ta_only:
            from app.vibedesk.schemas import StartSwarmRequest

            vibe_req = StartSwarmRequest(
                preset=VIBE_PRESET_NAME,
                symbol=args.symbol,
                question=args.question,
                budget_usd=str(per_child_budget_usd),
                model=args.model,
            )
            vibe_run = vibe_service.start_run(vibe_req, settings=settings)
            vibe_run = _await_terminal("vibedesk", vibe_run.run_id, settings=settings, timeout_s=child_timeout_s)
    finally:
        ta_prompts.SYSTEM_FOR_ROLE = original_system_for_role
        vibe_service.load_preset = original_service_load_preset  # type: ignore[attr-defined]
        vibe_runtime.load_preset = original_runtime_load_preset  # type: ignore[attr-defined]

    ta_call_ids = [c for s in ta_run.stages for c in s.call_ids]
    vibe_call_ids = [c for s in vibe_run.stages for c in s.call_ids] if vibe_run is not None else []
    cost_summary = agent_telemetry.summarize_calls([*ta_call_ids, *vibe_call_ids], settings=settings)
    if vibe_run is not None:
        vibe_verdict, vibe_explicit = wf_verdict.parse_verdict(vibe_run.final_md)
    else:
        vibe_verdict, vibe_explicit = "INCONCLUSIVE", False

    return SideResult(
        label=label,
        symbol=args.symbol,
        trade_date=args.trade_date,
        ta_run_id=ta_run.run_id,
        ta_state=ta_run.state,
        ta_final_rating=ta_run.final_rating,
        ta_final_md=ta_run.final_md,
        ta_stage_grounding=_stage_groundings(ta_run),
        ta_fields=_ta_fields(ta_run),
        vibe_run_id=vibe_run.run_id if vibe_run is not None else "",
        vibe_state=vibe_run.state if vibe_run is not None else "(skipped: --ta-only)",
        vibe_verdict=vibe_verdict,
        vibe_verdict_explicit=vibe_explicit,
        vibe_final_md=vibe_run.final_md if vibe_run is not None else "",
        vibe_stage_grounding=_stage_groundings(vibe_run) if vibe_run is not None else (),
        vibe_fields=_vibe_fields(vibe_run) if vibe_run is not None else {},
        call_count=cost_summary.call_count,
        input_tokens=cost_summary.input_tokens,
        output_tokens=cost_summary.output_tokens,
        cache_read_input_tokens=cost_summary.cache_read_input_tokens,
        cache_creation_input_tokens=cost_summary.cache_creation_input_tokens,
        cost_usd=cost_summary.cost_usd,
    )


# ---------------------------------------------------------------------------
# The comparison itself
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComparisonReport:
    passed: bool
    issues: tuple[str, ...]
    arm_results: dict[str, tuple[bool, bool]]
    """arm name -> (baseline_passed, candidate_passed)."""
    field_dump: dict[str, tuple[str, str]]
    """field name -> (baseline_value, candidate_value), for condition 2's human review."""
    token_delta: dict[str, Any]


def _candidate_for_gate(result: SideResult) -> wf_pipeline._Candidate:
    """Build the same `_Candidate` shape `app.workflow.pipeline._passes_gate` itself consumes, from
    one side's results -- reusing the real gate function rather than reimplementing its four-arm
    logic, per the task brief."""
    return wf_pipeline._Candidate(
        symbol=result.symbol,
        entry_rank=1,
        ta_rating=result.ta_final_rating,
        ta_ok=(result.ta_state == "succeeded"),
        vibe_verdict=result.vibe_verdict,
        vibe_explicit=result.vibe_verdict_explicit,
    )


def compare_sides(
    baseline: SideResult, candidate: SideResult, *, min_checked_token_ratio: float = 0.5
) -> ComparisonReport:
    """Automate conditions 1, 3 and 4; emit the raw material for a human to judge condition 2.

    Never raises for a failing comparison -- a compression change that changes a decision is exactly
    the outcome this function exists to report, not an exceptional circumstance. `passed` is `False`
    and `issues` names every reason; the caller (`main`, or a human reading the report) decides what
    to do about it.
    """
    issues: list[str] = []

    # --- Condition 1a: identical TA rating, identical Vibe verdict -----------------------------
    if baseline.ta_final_rating != candidate.ta_final_rating:
        issues.append(
            f"TA final_rating changed: baseline={baseline.ta_final_rating!r} "
            f"candidate={candidate.ta_final_rating!r}"
        )
    if baseline.vibe_verdict != candidate.vibe_verdict:
        issues.append(f"Vibe VERDICT changed: baseline={baseline.vibe_verdict!r} candidate={candidate.vibe_verdict!r}")

    # --- Condition 1b: identical pass/fail on all four arms, via the real gate function --------
    base_cand = _candidate_for_gate(baseline)
    new_cand = _candidate_for_gate(candidate)
    arm_results: dict[str, tuple[bool, bool]] = {}
    for arm in wf_pipeline.ALL_ARMS:
        base_pass = wf_pipeline._passes_gate(arm, base_cand)
        cand_pass = wf_pipeline._passes_gate(arm, new_cand)
        arm_results[arm] = (base_pass, cand_pass)
        if base_pass != cand_pass:
            issues.append(f"arm {arm!r} gate outcome changed: baseline={base_pass} candidate={cand_pass}")

    # --- Condition 3: grounding still ok on the candidate, no new retries ----------------------
    if not candidate.all_grounding_ok:
        failing = [g.stage_id for g in (*candidate.ta_stage_grounding, *candidate.vibe_stage_grounding) if not g.ok]
        issues.append(f"candidate has ungrounded/degraded stage(s): {', '.join(failing)}")

    base_attempts = {g.stage_id: g.attempts for g in (*baseline.ta_stage_grounding, *baseline.vibe_stage_grounding)}
    cand_attempts = {g.stage_id: g.attempts for g in (*candidate.ta_stage_grounding, *candidate.vibe_stage_grounding)}
    for stage_id, cand_n in cand_attempts.items():
        base_n = base_attempts.get(stage_id)
        if base_n is not None and cand_n > base_n:
            issues.append(
                f"stage {stage_id!r} needed more grounding retries on the candidate "
                f"(baseline={base_n} attempt(s), candidate={cand_n})"
            )

    # --- Condition 4: checked_tokens does not collapse toward zero -----------------------------
    base_tokens = baseline.total_checked_tokens
    cand_tokens = candidate.total_checked_tokens
    if base_tokens > 0:
        ratio = cand_tokens / base_tokens
        if ratio < min_checked_token_ratio:
            issues.append(
                f"candidate checked_tokens collapsed: {cand_tokens} vs baseline {base_tokens} "
                f"(ratio {ratio:.2f} < floor {min_checked_token_ratio})"
            )
    elif cand_tokens == 0:
        # Baseline itself checked nothing (both sides wrote no numbers) -- not a regression to flag.
        pass

    # --- Condition 2 material: side-by-side field dump, not scored here ------------------------
    field_dump: dict[str, tuple[str, str]] = {}
    all_keys = sorted({*baseline.ta_fields.keys(), *candidate.ta_fields.keys()})
    for key in all_keys:
        field_dump[f"ta.{key}"] = (baseline.ta_fields.get(key, ""), candidate.ta_fields.get(key, ""))
    all_vibe_keys = sorted({*baseline.vibe_fields.keys(), *candidate.vibe_fields.keys()})
    for key in all_vibe_keys:
        field_dump[f"vibe.{key}"] = (baseline.vibe_fields.get(key, ""), candidate.vibe_fields.get(key, ""))

    token_delta: dict[str, Any] = {
        "baseline": {
            "input_tokens": baseline.input_tokens,
            "output_tokens": baseline.output_tokens,
            "cache_read_input_tokens": baseline.cache_read_input_tokens,
            "cache_creation_input_tokens": baseline.cache_creation_input_tokens,
            "cost_usd": str(baseline.cost_usd),
            "checked_tokens": base_tokens,
        },
        "candidate": {
            "input_tokens": candidate.input_tokens,
            "output_tokens": candidate.output_tokens,
            "cache_read_input_tokens": candidate.cache_read_input_tokens,
            "cache_creation_input_tokens": candidate.cache_creation_input_tokens,
            "cost_usd": str(candidate.cost_usd),
            "checked_tokens": cand_tokens,
        },
    }
    if baseline.output_tokens > 0:
        saved = baseline.output_tokens - candidate.output_tokens
        token_delta["output_tokens_saved"] = saved
        token_delta["output_tokens_saved_pct"] = round(100 * saved / baseline.output_tokens, 1)

    return ComparisonReport(
        passed=not issues, issues=tuple(issues), arm_results=arm_results, field_dump=field_dump, token_delta=token_delta
    )


def render_report(report: ComparisonReport, baseline: SideResult, candidate: SideResult) -> str:
    lines = [
        "# Prompt compression comparison",
        "",
        f"Symbol: {baseline.symbol}  Trade date: {baseline.trade_date.isoformat()}",
        f"Overall: {'PASS' if report.passed else 'FAIL'}",
        "",
        "## Issues" if report.issues else "## Issues: none",
    ]
    lines += [f"- {issue}" for issue in report.issues]
    lines += ["", "## Arm gate results (baseline, candidate)"]
    lines += [f"- {arm}: {result}" for arm, result in report.arm_results.items()]
    lines += ["", "## Token delta", json.dumps(report.token_delta, indent=2)]
    lines += ["", "## Field dump (baseline, candidate)"]
    for key, (base_val, cand_val) in report.field_dump.items():
        lines += [f"### {key}", "**baseline:**", base_val, "", "**candidate:**", cand_val, ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Dry run (default): print the plan and exit 0, making zero model calls.

    Live (`--live --budget-usd X`): actually run both sides, assert evidence determinism, compare,
    print the report, and return 1 if any automated invariance condition failed (0 otherwise). This
    script never decides to go live on its own -- `--live` must be passed explicitly by whoever is
    invoking it, per this repo's hard constraint on spending money.
    """
    args = parse_args(argv)
    plan = build_plan(args)

    if not args.live:
        print(json.dumps(plan, indent=2))
        return 0

    settings = Settings(data_dir=args.data_dir) if args.data_dir is not None else Settings()

    baseline_fp = evidence_fingerprint(args.symbol, args.trade_date, settings=settings)
    candidate_fp = evidence_fingerprint(args.symbol, args.trade_date, settings=settings)
    if baseline_fp != candidate_fp:
        print(
            "ABORT: evidence pack fingerprint is not stable for the same (symbol, trade_date) -- "
            f"{baseline_fp} != {candidate_fp}. The comparison is meaningless until this is fixed.",
            file=sys.stderr,
        )
        return 2

    per_child_budget = args.budget_usd / 4

    baseline_prompts = load_baseline_prompts(args.baseline_ref)
    baseline_preset = None if args.ta_only else load_baseline_preset(args.baseline_ref)

    baseline_result = run_one_side(
        "baseline", args, settings=settings,
        prompts_module=baseline_prompts, preset_data=baseline_preset,
        per_child_budget_usd=per_child_budget, ta_only=args.ta_only,
    )
    candidate_result = run_one_side(
        "candidate", args, settings=settings,
        prompts_module=None, preset_data=None,
        per_child_budget_usd=per_child_budget, ta_only=args.ta_only,
    )

    report = compare_sides(baseline_result, candidate_result, min_checked_token_ratio=args.min_checked_token_ratio)
    text = render_report(report, baseline_result, candidate_result)
    # Write the file BEFORE printing: the report contains a real minus sign (U+2212) from the model's
    # own prose, and a Windows console defaulting to cp1252 raises UnicodeEncodeError on it -- if the
    # print came first, that crash would lose the whole report even though both runs completed. Write
    # persists it regardless, and the stdout copy is emitted through the UTF-8 buffer so the console
    # encoding cannot kill it either.
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.buffer.write(text.encode("utf-8", "replace") + b"\n")

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
