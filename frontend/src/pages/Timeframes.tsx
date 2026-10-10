/**
 * Timeframes: the rule x interval accuracy matrix, and a drill-down into one cell's evidence.
 *
 * A rule x interval x symbol accuracy matrix is neither a rule *definition* (it needs bars, so it
 * cannot live on the symbol-independent `Rules.tsx`) nor a single symbol's *evaluation* (it compares
 * across intervals and optionally across symbols/sectors, so it does not fit `Ticker.tsx`'s
 * one-symbol-at-length shape). See `docs/research/timeframes/05-feature-surface-design.md` §3 for
 * the full placement argument; this page is the "new top-level page" that document recommends.
 *
 * **The single most important rendering rule on this page** (contract §5, rule 1): a cell whose
 * `sufficient` is `false` must never render a number, never `0%`, never a blank that reads as zero.
 * `MatrixCell` below branches on `sufficient` *before* touching `lift`/`hit_rate` at all, so an
 * insufficient cell's JSX has no code path that can print one of those fields even by accident.
 *
 * **`lift` drives the cell's colour and headline figure; `hit_rate` is secondary, always beside its
 * `base_rate`** (contract §5, rule 2). A zero-skill rule's hit rate looks excellent in a rising
 * market while its lift sits near zero — showing hit rate alone would make noise look like a
 * strategy, the same failure `@/api/rules`' own module docstring warns about for `Evidence`.
 *
 * **Columns are intervals in the fixed canonical order from `@/api/market`'s `INTERVALS`**, and any
 * alignment across them uses `horizon_minutes`, never `horizon_bars` (contract §5, rule 3) — 20 bars
 * is 100 minutes at 5m and a month at 1d.
 *
 * **The `4h` column carries a persistent low-confidence marker** (contract §5, rule 5): its bars
 * alternate 4h/2.5h and it only clears ~73 independent windows/symbol against daily's ~250. The
 * marker sits on the column header, unconditionally, independent of any one cell's own sufficiency.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { ApiRequestError } from "@/api/client";
import { INTERVALS, type Interval } from "@/api/market";
import { formatRate, formatSignedRate } from "@/api/rules";
import {
  liftOf,
  regimeLabel,
  timeframesApi,
  type MatrixCoverage,
  type RuleAccuracyCell,
  type Scope,
  type SignalTrace,
  type UniverseEntry,
} from "@/api/timeframes";
import { Card, CardGrid } from "@/components/Card";
import Chart, { type ChartMarker } from "@/components/Chart";
import InfoNote from "@/components/InfoNote";
import { ScrollRegion } from "@/components/ScrollPanel";
import Skeleton from "@/components/Skeleton";
import Term from "@/components/Term";
import { Trans, type Translator, useT } from "@/i18n";

import "./Timeframes.css";

type Phase = "loading" | "loaded" | "empty" | "error";

/** A rule fires -- it is an event, not a price direction, so its marker borrows neither `--up` nor
 *  `--down`. Matches `--warn` (`#ffb454`) verbatim: `Chart.tsx`'s markers are consumed directly by
 *  lightweight-charts' canvas rendering, which cannot resolve a CSS custom property the way the DOM
 *  can, so this has to be a literal colour rather than `"var(--warn)"`. */
const FIRE_MARKER_COLOR = "#ffb454";

/** Below half a percentage point of lift reads as neutral, never as "mildly good" or "mildly bad" --
 *  the dead zone contract §5 rule 2's spirit implies: a near-zero lift is the honest picture for a
 *  zero-skill rule, and colouring it green or red the same way a real edge is coloured would blur
 *  exactly the distinction this page exists to preserve. */
const NEUTRAL_LIFT_DEADZONE = 0.005;
/** Lift magnitude at or above which the colour saturates -- 15 percentage points, the same order of
 *  magnitude `DecisionTable.tsx`'s own significance thresholds use for "a lot". */
const LIFT_SATURATION = 0.15;

function scopeLabel(scope: Scope, t: Translator): string {
  switch (scope) {
    case "symbol":
      return t("common.symbol");
    case "sector":
      return t("strategy.timeframes.scope.sector");
    case "universe":
      return t("strategy.timeframes.scope.universe");
  }
}

/** `"pos" | "neg" | ""` on `lift`, with a neutral dead zone around zero. */
function liftClass(lift: number | null): "pos" | "neg" | "" {
  if (lift === null || Math.abs(lift) < NEUTRAL_LIFT_DEADZONE) return "";
  return lift > 0 ? "pos" : "neg";
}

/** Diverging background tint keyed off `lift`'s sign and magnitude, capped at `LIFT_SATURATION` so
 *  one outlier rule cannot wash out every other cell's colour by comparison. Returns `undefined`
 *  (no tint) for `null` or a lift inside the neutral dead zone -- a near-zero cell must not read as
 *  even mildly positive. */
function liftBackground(lift: number | null): string | undefined {
  if (lift === null || Math.abs(lift) < NEUTRAL_LIFT_DEADZONE) return undefined;
  const magnitude = Math.min(Math.abs(lift), LIFT_SATURATION) / LIFT_SATURATION;
  const alpha = 0.08 + magnitude * 0.32;
  const rgb = lift > 0 ? "53, 226, 138" : "255, 77, 106"; // --up / --down, as rgb triples
  return `rgba(${rgb}, ${alpha.toFixed(2)})`;
}

/** `fired_at` is rising edges only (contract §3), so one marker per entry is exactly `n_episodes`
 *  worth of arrows -- never every bar a sustained condition held true. */
function firedAtToMarkers(firedAt: readonly string[]): ChartMarker[] {
  return firedAt.map((time) => ({
    time,
    position: "belowBar",
    shape: "arrowUp",
    color: FIRE_MARKER_COLOR,
    text: "fired",
  }));
}

interface HorizonBucket {
  horizon_minutes: number;
  horizon_label: string;
}

/** Distinct `(horizon_minutes, horizon_label)` pairs present in `cells`, ascending. Grouping happens
 *  entirely on `horizon_minutes` -- never `horizon_bars` -- per contract §5 rule 3. */
function horizonBucketsOf(cells: readonly RuleAccuracyCell[]): HorizonBucket[] {
  const seen = new Map<number, string>();
  for (const cell of cells) {
    if (!seen.has(cell.horizon_minutes)) seen.set(cell.horizon_minutes, cell.horizon_label);
  }
  return [...seen.entries()]
    .map(([horizon_minutes, horizon_label]) => ({ horizon_minutes, horizon_label }))
    .sort((a, b) => a.horizon_minutes - b.horizon_minutes);
}

/** Distinct `rule_id`s present in `cells`, alphabetical -- the matrix's rows. Computed across every
 *  horizon bucket, not just the selected one, so switching horizons never reshuffles or drops a row
 *  that happens to have no cell at the newly-selected horizon (it renders "n/a" for that column
 *  instead, same as any other uncomputed combination). */
function ruleIdsOf(cells: readonly RuleAccuracyCell[]): string[] {
  return [...new Set(cells.map((c) => c.rule_id))].sort();
}

export interface TimeframesProps {
  /**
   * True when this page is mounted as a TAB BODY (`Evidence.tsx`) rather than as its own route.
   * Drops the page heading from `<h1>` to `<h2>`; see `Rules.tsx`'s identical prop for the whole
   * argument. Optional and defaulted, so `/timeframes` keeps the `<h1>` it had.
   */
  embedded?: boolean | undefined;
}

export default function Timeframes({ embedded = false }: TimeframesProps = {}) {
  const { t } = useT();
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [cells, setCells] = useState<RuleAccuracyCell[]>([]);
  const [coverage, setCoverage] = useState<MatrixCoverage | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  const [universe, setUniverse] = useState<UniverseEntry[]>([]);

  const [scope, setScope] = useState<Scope>("symbol");
  const [scopeKey, setScopeKey] = useState<string>("SPY");
  const [selectedHorizon, setSelectedHorizon] = useState<number | null>(null);
  const [selected, setSelected] = useState<{ ruleId: string; interval: Interval } | null>(null);

  // The universe populates the symbol/sector picker. Best-effort: a failed fetch leaves the picker
  // on its built-in fallback options rather than blocking the whole page on a secondary endpoint.
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    timeframesApi
      .universe(controller.signal)
      .then((entries) => {
        if (!cancelled) setUniverse(entries);
      })
      .catch(() => {
        // Non-fatal -- the matrix fetch below is the page's actual content.
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  const symbolOptions = useMemo(() => {
    const symbols = universe.map((u) => u.symbol);
    return symbols.length > 0 ? symbols : [scopeKey];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [universe]);

  const sectorOptions = useMemo(() => {
    const sectors = [...new Set(universe.map((u) => u.sector))].sort();
    return sectors.length > 0 ? sectors : [scopeKey];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [universe]);

  // Reset the scope key to a sensible default whenever the scope itself changes, and close any open
  // drill-down -- its `(ruleId, interval)` selection was made against the previous scope's cells.
  function handleScopeChange(next: Scope) {
    setScope(next);
    setSelected(null);
    if (next === "symbol") {
      setScopeKey(symbolOptions[0] ?? "SPY");
    } else if (next === "sector") {
      setScopeKey(sectorOptions[0] ?? "Technology");
    } else {
      setScopeKey("ALL");
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setPhase("loading");
    setMessage(null);

    const params =
      scope === "universe"
        ? { scope: "universe" as const }
        : scope === "sector"
          ? { scope: "sector" as const, sectors: [scopeKey] }
          : { scope: "symbol" as const, symbols: [scopeKey] };

    timeframesApi
      .matrix(params, controller.signal)
      .then((result) => {
        if (cancelled) return;
        setCells(result.cells);
        setCoverage(result.coverage);
        setGeneratedAt(result.generated_at);
        setWarnings(result.warnings);
        setPhase(result.cells.length === 0 ? "empty" : "loaded");
      })
      .catch((error: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setMessage(
          error instanceof ApiRequestError
            ? t("strategy.error.apiStatus", { status: error.status, message: error.message })
            : t("strategy.timeframes.matrixLoadError"),
        );
        setPhase("error");
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, scopeKey]);

  const horizonBuckets = useMemo(() => horizonBucketsOf(cells), [cells]);
  const ruleIds = useMemo(() => ruleIdsOf(cells), [cells]);

  // Keep the selected horizon valid as the cell set changes -- default to the finest (smallest
  // `horizon_minutes`) bucket, and fall back the same way if the previously-selected one disappears
  // (a scope change can return a different set of computed horizons).
  useEffect(() => {
    const first = horizonBuckets[0];
    if (first === undefined) {
      setSelectedHorizon(null);
      return;
    }
    setSelectedHorizon((current) => {
      if (current !== null && horizonBuckets.some((b) => b.horizon_minutes === current)) {
        return current;
      }
      return first.horizon_minutes;
    });
  }, [horizonBuckets]);

  function cellFor(ruleId: string, interval: Interval): RuleAccuracyCell | undefined {
    return cells.find(
      (c) =>
        c.rule_id === ruleId && c.interval === interval && c.horizon_minutes === selectedHorizon,
    );
  }

  const coveragePct =
    coverage && coverage.cells_total > 0
      ? Math.round((coverage.cells_sufficient / coverage.cells_total) * 100)
      : null;

  const selectedCell = selected ? cellFor(selected.ruleId, selected.interval) : undefined;

  const Heading = embedded ? "h2" : "h1";

  return (
    <>
      <Heading>{t("strategy.timeframes.pageTitle")}</Heading>
      <p className="subtitle">{t("strategy.timeframes.subtitle")}</p>

      <section className="panel tf-controls">
        <div className="tf-scope-switch" role="tablist" aria-label={t("strategy.timeframes.scopeAriaLabel")}>
          {(["symbol", "sector", "universe"] as const).map((s) => (
            <button
              key={s}
              type="button"
              role="tab"
              aria-selected={scope === s}
              className={`timeframe-tab${scope === s ? " active" : ""}`}
              onClick={() => handleScopeChange(s)}
            >
              {scopeLabel(s, t)}
            </button>
          ))}
        </div>

        {scope !== "universe" && (
          <label className="tf-scope-key">
            {scope === "symbol" ? t("common.symbol") : t("strategy.timeframes.scope.sector")}
            <select value={scopeKey} onChange={(e) => setScopeKey(e.target.value)}>
              {(scope === "symbol" ? symbolOptions : sectorOptions).map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
        )}

        {horizonBuckets.length > 0 && (
          <div className="tf-horizon-picker" role="tablist" aria-label={t("strategy.timeframes.horizonAriaLabel")}>
            <span className="decision-horizon-label">{t("strategy.timeframes.horizonAriaLabel")}</span>
            {horizonBuckets.map((b) => (
              <button
                key={b.horizon_minutes}
                type="button"
                role="tab"
                aria-selected={b.horizon_minutes === selectedHorizon}
                className={`timeframe-tab${b.horizon_minutes === selectedHorizon ? " active" : ""}`}
                onClick={() => setSelectedHorizon(b.horizon_minutes)}
              >
                {b.horizon_label}
              </button>
            ))}
          </div>
        )}
      </section>

      {/* "Loading the accuracy matrix…" on one line, for a fetch that scores every rule against
          every interval, left an empty strip where a full grid was about to appear. `rows` draws
          that grid's rough height first, so the arrival of real data is a content change rather
          than the page growing under the reader's cursor. */}
      {phase === "loading" && (
        <div className="panel">
          <Skeleton variant="rows" rows={8} what={t("strategy.timeframes.pageTitle")} />
        </div>
      )}

      {phase === "error" && (
        <div className="panel">
          <div className="placeholder">{message}</div>
        </div>
      )}

      {phase === "empty" && (
        <div className="panel">
          <div className="placeholder">{t("strategy.timeframes.emptyScope")}</div>
        </div>
      )}

      {phase === "loaded" && (
        <>
          <section className="panel tf-coverage">
            <div className="tf-coverage-headline">
              <Trans
                k="strategy.timeframes.coverageHeadline"
                values={{
                  sufficient: <strong>{coverage?.cells_sufficient ?? 0}</strong>,
                  total: coverage?.cells_total ?? 0,
                }}
              />
              {coveragePct !== null && (
                <span className="muted">
                  {t("strategy.timeframes.coveragePct", { pct: coveragePct })}
                </span>
              )}
            </div>
            {generatedAt && (
              <div className="muted">{t("strategy.timeframes.generatedLabel", { date: generatedAt })}</div>
            )}
          </section>

          {warnings.length > 0 && (
            <ScrollRegion
              size="sm"
              label={t("strategy.timeframes.stat.warnings")}
              className="warnings-strip"
            >
              {warnings.map((w, i) => (
                <div className="warning-chip" key={i}>
                  <span className="message">{w}</span>
                </div>
              ))}
            </ScrollRegion>
          )}

          <section className="panel">
            <InfoNote summary={t("strategy.timeframes.blankCellsSummary")}>
              {t("strategy.timeframes.blankCells.detail")}
            </InfoNote>
            <ScrollRegion size="md" label={t("strategy.timeframes.matrixScrollLabel")}>
              <div className="table-wrap">
                <table className="data-table tf-matrix" aria-label={t("strategy.timeframes.tableAriaLabel")}>
                  <thead>
                    <tr>
                      <th scope="col">{t("strategy.rules.header.rule")}</th>
                      {INTERVALS.map((iv) => (
                        <th scope="col" key={iv} className={iv === "4h" ? "tf-interval-lowconf" : ""}>
                          {iv}
                          {iv === "4h" && (
                            <span
                              className="tf-lowconf-marker"
                              title={t("strategy.timeframes.lowConfidenceTitle")}
                              aria-label={t("strategy.timeframes.lowConfidenceAriaLabel")}
                            >
                              {" "}
                              †
                            </span>
                          )}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ruleIds.map((ruleId) => (
                      <tr key={ruleId}>
                        <th scope="row">{ruleId}</th>
                        {INTERVALS.map((iv) => (
                          <MatrixCell
                            key={iv}
                            cell={cellFor(ruleId, iv)}
                            onSelect={() => setSelected({ ruleId, interval: iv })}
                          />
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </ScrollRegion>
          </section>

          {selected && (
            <DrillDown
              ruleId={selected.ruleId}
              interval={selected.interval}
              scope={scope}
              scopeKey={scopeKey}
              cell={selectedCell}
              onClose={() => setSelected(null)}
            />
          )}
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Matrix cell
// ---------------------------------------------------------------------------

function MatrixCell({
  cell,
  onSelect,
}: {
  cell: RuleAccuracyCell | undefined;
  onSelect: () => void;
}) {
  const { t } = useT();
  if (!cell) {
    return (
      <td className="tf-cell tf-cell-na">
        <span className="muted">{t("strategy.timeframes.notApplicable")}</span>
      </td>
    );
  }

  if (!cell.sufficient) {
    // No number is derived from `cell` above this line, and none is below it -- an insufficient
    // cell has no code path in this branch that can print `lift`, `hit_rate`, or `0%` even by
    // accident (contract §5 rule 1).
    const title =
      cell.warnings.length > 0
        ? cell.warnings.join(" · ")
        : t("strategy.timeframes.insufficientTitle", { count: cell.n_independent });
    return (
      <td className="tf-cell tf-cell-insufficient">
        <button type="button" className="tf-cell-btn" onClick={onSelect} title={title}>
          <span className="tf-insufficient-block" aria-hidden="true" />
          <span className="tf-insufficient-label">{t("strategy.timeframes.insufficientLabel")}</span>
          <span className="tf-cell-sub muted">
            {t("strategy.timeframes.indepCount", { count: cell.n_independent })}
          </span>
        </button>
      </td>
    );
  }

  const lift = liftOf(cell);
  const cls = liftClass(lift);
  const background = liftBackground(lift);
  const title = cell.warnings.length > 0 ? cell.warnings.join(" · ") : undefined;

  return (
    <td className="tf-cell tf-cell-measured">
      <button
        type="button"
        className="tf-cell-btn"
        style={background ? { background } : undefined}
        onClick={onSelect}
        {...(title !== undefined ? { title } : {})}
      >
        <div className={`tf-lift-value ${cls}`}>{formatSignedRate(lift)}</div>
        <div className="tf-cell-sub muted">
          {t("strategy.timeframes.hitVsBase", {
            hit: formatRate(cell.hit_rate),
            base: formatRate(cell.base_rate),
          })}
        </div>
        <div className="tf-cell-sub muted">
          {t("strategy.timeframes.indepCount", { count: cell.n_independent })}
        </div>
      </button>
    </td>
  );
}

// ---------------------------------------------------------------------------
// Drill-down
// ---------------------------------------------------------------------------

type DrillPhase = "loading" | "loaded" | "error" | "unavailable";

function DrillDown({
  ruleId,
  interval,
  scope,
  scopeKey,
  cell,
  onClose,
}: {
  ruleId: string;
  interval: Interval;
  scope: Scope;
  scopeKey: string;
  cell: RuleAccuracyCell | undefined;
  onClose: () => void;
}) {
  const { t } = useT();
  const [drillPhase, setDrillPhase] = useState<DrillPhase>(scope === "symbol" ? "loading" : "unavailable");
  const [trace, setTrace] = useState<SignalTrace | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    // The per-bar signal trace is defined for exactly one symbol (contract §3's `signal_trace`
    // takes a single `symbol`, not a sector or the whole universe), so the chart half of the
    // drill-down only has something to fetch when the matrix itself is scoped to one symbol. A
    // sector/universe cell still shows its full statistics below -- it just cannot show candles for
    // a symbol that was never singled out.
    if (scope !== "symbol") {
      setDrillPhase("unavailable");
      return;
    }
    const controller = new AbortController();
    let cancelled = false;
    setDrillPhase("loading");
    setMessage(null);

    timeframesApi
      .signal({ symbol: scopeKey, interval, rule_id: ruleId }, controller.signal)
      .then((result) => {
        if (cancelled) return;
        setTrace(result);
        setDrillPhase("loaded");
      })
      .catch((error: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setMessage(
          error instanceof ApiRequestError
            ? t("strategy.error.apiStatus", { status: error.status, message: error.message })
            : t("strategy.timeframes.signalLoadError"),
        );
        setDrillPhase("error");
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, scopeKey, interval, ruleId]);

  const markers = useMemo(() => (trace ? firedAtToMarkers(trace.fired_at) : []), [trace]);
  const ts = useMemo(() => (trace ? trace.bars.map((b) => b.ts) : []), [trace]);

  return (
    <section
      className="panel tf-drilldown"
      aria-label={t("strategy.timeframes.drilldownAriaLabel", { ruleId, interval })}
    >
      <div className="tf-drilldown-head">
        <h2>
          {ruleId} @ {interval} — {scopeKey}
        </h2>
        {scope === "symbol" && (
          <Link to={`/symbol/${scopeKey}`} className="tf-drilldown-ticker-link">
            {t("strategy.timeframes.openOnTicker", { symbol: scopeKey })}
          </Link>
        )}
        <button type="button" className="tf-drilldown-close" onClick={onClose}>
          {t("strategy.timeframes.closeButton")}
        </button>
      </div>

      <CardGrid height="md" className="tf-drilldown-body">
        {/* `height="auto"`: the chart already sizes itself (`Chart`'s own fixed height), so this
            card never needs a scroll cap of its own -- it just needs to fill the same row height as
            the stats card beside it, which `CardGrid`'s `stretch` (not `align-items: start`)
            provides. */}
        <Card height="auto" panelClassName="tf-drilldown-chart">
          {drillPhase === "loading" && (
            <div className="placeholder">{t("strategy.timeframes.loadingSignalTrace")}</div>
          )}
          {drillPhase === "error" && <div className="placeholder">{message}</div>}
          {drillPhase === "unavailable" && (
            <div className="placeholder">
              {t("strategy.timeframes.drilldownUnavailable", { scopeKey })}
            </div>
          )}
          {drillPhase === "loaded" && trace && (
            <Chart bars={trace.bars} series={trace.indicators} ts={ts} interval={interval} markers={markers} />
          )}
        </Card>

        {/* `height="md"` gives this card its own `ScrollRegion` (`label` below names it) -- `CellStats`
            used to open its own `ScrollRegion` around the same `<dl>`; kept as a single scroller here
            rather than one nested inside the other, which `Card.test.tsx` calls out as the exact
            failure this primitive exists to make impossible ("a scroller inside a scroller traps the
            wheel"). */}
        <Card height="md" label={t("strategy.timeframes.statsScrollLabel")} panelClassName="tf-drilldown-stats">
          {cell ? (
            <CellStats cell={cell} />
          ) : (
            <div className="placeholder">{t("strategy.timeframes.noCellStats")}</div>
          )}
        </Card>
      </CardGrid>
    </section>
  );
}

/** Rendered as a bare `<dl>` -- its own `ScrollRegion` used to wrap it, but the `Card` this now
 *  renders inside (`DrillDown` above, `height="md"`) already supplies one around the whole card
 *  body. A second one here would nest scrollers, which `Card.test.tsx` documents as the exact
 *  failure the `Card`/`ScrollRegion` contract exists to make structurally impossible. */
function CellStats({ cell }: { cell: RuleAccuracyCell }) {
  const { t } = useT();
  const lift = liftOf(cell);
  return (
    <dl className="tf-stats-list">
      <div>
        <dt>{t("strategy.timeframes.stat.lift")}</dt>
        <dd className={liftClass(lift)}>{formatSignedRate(lift)}</dd>
      </div>
      <div>
        <dt>{t("strategy.timeframes.stat.hitRate")}</dt>
        <dd>{formatRate(cell.hit_rate)}</dd>
      </div>
      <div>
        <dt>{t("strategy.timeframes.stat.baseRate")}</dt>
        <dd>{formatRate(cell.base_rate)}</dd>
      </div>
      <div>
        <dt>{t("strategy.timeframes.stat.liftCi")}</dt>
        <dd>
          {t("strategy.timeframes.liftCiRange", {
            low: formatSignedRate(cell.lift_ci_low),
            high: formatSignedRate(cell.lift_ci_high),
          })}
        </dd>
      </div>
      <div>
        <dt>{t("strategy.timeframes.stat.medianReturn")}</dt>
        <dd>{formatSignedRate(cell.median_return)}</dd>
      </div>
      <div>
        <dt>{t("strategy.timeframes.stat.baselineMedian")}</dt>
        <dd>{formatSignedRate(cell.baseline_median_return)}</dd>
      </div>
      {/* The drill-down is where this page names its statistics, and it is the one place each name
          is rendered exactly once -- the matrix above repeats `INSUFFICIENT` and the independent
          count in every cell, so defining them there would mean defining them ninety times. */}
      <div>
        <dt>
          <Term k="pValue">{t("strategy.timeframes.stat.pValue")}</Term>
        </dt>
        <dd>{cell.p_value === null ? "—" : cell.p_value.toFixed(4)}</dd>
      </div>
      <div>
        <dt>
          <Term k="qValue">{t("strategy.timeframes.stat.qValue")}</Term>
        </dt>
        <dd>{cell.q_value === null ? "—" : cell.q_value.toFixed(4)}</dd>
      </div>
      <div>
        <dt>{t("strategy.timeframes.stat.costAdjustedEdge")}</dt>
        <dd>{formatSignedRate(cell.cost_adjusted_edge)}</dd>
      </div>
      <div>
        <dt>{t("strategy.timeframes.stat.costAssumed")}</dt>
        <dd>
          {cell.cost_bps_assumed} <Term k="bp">bps</Term>
        </dd>
      </div>
      <div>
        <dt>
          <Term k="indep">{t("strategy.timeframes.stat.sample")}</Term>
        </dt>
        <dd>
          {t("strategy.timeframes.sampleBreakdown", {
            raw: cell.n_raw,
            episodes: cell.n_episodes,
            indep: cell.n_independent,
          })}
        </dd>
      </div>
      <div>
        <dt>
          <Term k="insufficient">{t("strategy.timeframes.stat.sufficient")}</Term>
        </dt>
        <dd>{cell.sufficient ? t("strategy.timeframes.yes") : t("strategy.timeframes.no")}</dd>
      </div>
      <div>
        <dt>
          <Term k="regime">{t("strategy.timeframes.stat.regime")}</Term>
        </dt>
        <dd>{regimeLabel(cell.regime)}</dd>
      </div>
      <div>
        <dt>{t("strategy.timeframes.stat.span")}</dt>
        <dd>
          {t("strategy.timeframes.spanRange", { first: cell.first_bar, last: cell.last_bar })}
        </dd>
      </div>
      {cell.warnings.length > 0 && (
        <div className="tf-stats-warnings">
          <dt>{t("strategy.timeframes.stat.warnings")}</dt>
          <dd>
            <ul>
              {cell.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </dd>
        </div>
      )}
    </dl>
  );
}
