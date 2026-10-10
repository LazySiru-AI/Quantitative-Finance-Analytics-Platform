/**
 * Hand-rolled inline SVG chart for the Account page's warnings box (`WarningsSection` in
 * `Portfolio.tsx`), mounted only while that box is expanded.
 *
 * No charting dependency backs this: `lightweight-charts`, the one chart library already in this
 * app, is a candlestick/time-series renderer and the wrong tool for a categorical bar chart of
 * warning counts. Follows the geometry/palette approach `AllocationPie.tsx` already established for
 * this codebase's hand-rolled SVG charts -- a fixed `viewBox`, CSS custom properties for colour so
 * the chart repaints correctly in both themes, and a `<title>` per data element for a hover tooltip.
 *
 * Two panels:
 *  - a horizontal bar per warning `kind` (`WarningGroup.kind`), each bar segmented by account so a
 *    reader can see at a glance whether a kind is one broker's problem or spread across several;
 *  - a "top symbols" bar list built from `TaxWarning.symbol` -- the individual warnings, not the
 *    pre-aggregated groups, since `WarningGroup` carries no symbol at all.
 *
 * Deliberately reuses the page's own `warningKindLabel` decoder for bar labels, so a reader sees the
 * exact same wording here as in the group table and the "show all" list right below the chart --
 * the chart is a different view of the same warnings, not a second vocabulary for them.
 */
import { useMemo } from "react";

import { warningKindLabel, type TaxWarning, type WarningGroup } from "@/api/portfolio";
import { useT } from "@/i18n";

import "./WarningsChart.css";

export interface WarningsChartProps {
  warningGroups: WarningGroup[];
  warnings: TaxWarning[];
}

/** Design tokens first, cycling once every 5 accounts -- this app rarely holds more than a handful
 *  of brokers, so a longer fixed numbered palette (as `AllocationPie.tsx` needs for potentially many
 *  ticker slices) would be solving a problem this chart does not have. Kept self-contained rather
 *  than importing `AllocationPie.css`'s numbered `--alloc-pie-color-*` set, which is scoped to that
 *  component and must not become an implicit dependency of this one. */
const SERIES_COLORS = ["var(--accent)", "var(--accent-2)", "var(--warn)", "var(--up)", "var(--down)"] as const;

interface KindSegment {
  key: string;
  account: string;
  count: number;
  color: string;
}

interface KindRow {
  kind: string;
  label: string;
  total: number;
  segments: KindSegment[];
}

/** `"account_id (broker)"`, or an em dash for the rare group with no account at all -- mirrors how
 *  `WarningsSection`'s own group table already renders the same two fields side by side. */
function accountLabel(accountId: string | null, broker: string | null): string {
  if (accountId === null) return "—";
  return broker ? `${accountId} (${broker})` : accountId;
}

function buildKindRows(groups: WarningGroup[]): { rows: KindRow[]; accounts: string[] } {
  // Account colour is assigned once, by that account's OVERALL count across every kind -- so the
  // same account gets the same colour in every bar it appears in, rather than a colour that shifts
  // depending on which kind happens to list it first.
  const accountTotals = new Map<string, number>();
  for (const g of groups) {
    const key = accountLabel(g.account_id, g.broker);
    accountTotals.set(key, (accountTotals.get(key) ?? 0) + g.count);
  }
  const accounts = Array.from(accountTotals.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([key]) => key);
  const colorByAccount = new Map(
    accounts.map((a, i) => [a, SERIES_COLORS[i % SERIES_COLORS.length] ?? SERIES_COLORS[0]]),
  );

  const byKind = new Map<string, WarningGroup[]>();
  for (const g of groups) {
    const list = byKind.get(g.kind);
    if (list) list.push(g);
    else byKind.set(g.kind, [g]);
  }

  const rows: KindRow[] = Array.from(byKind.entries())
    .map(([kind, kindGroups]) => {
      const segments: KindSegment[] = kindGroups.map((g) => {
        const account = accountLabel(g.account_id, g.broker);
        return {
          key: `${kind}:${g.account_id ?? ""}:${g.broker ?? ""}`,
          account,
          count: g.count,
          color: colorByAccount.get(account) ?? SERIES_COLORS[0],
        };
      });
      const total = segments.reduce((sum, s) => sum + s.count, 0);
      return { kind, label: warningKindLabel(kind), total, segments };
    })
    .sort((a, b) => b.total - a.total || a.kind.localeCompare(b.kind));

  return { rows, accounts };
}

interface TopSymbol {
  symbol: string;
  count: number;
}

/** Counts occurrences of `TaxWarning.symbol` across the individual warnings, skipping the null ones
 *  (a warning with no specific symbol contributes nothing to a per-symbol ranking), sorted
 *  descending by count and capped to `limit` -- a long tail here would crowd out the symbols that
 *  actually matter. */
function buildTopSymbols(warnings: TaxWarning[], limit = 8): TopSymbol[] {
  const counts = new Map<string, number>();
  for (const w of warnings) {
    if (!w.symbol) continue;
    counts.set(w.symbol, (counts.get(w.symbol) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([symbol, count]) => ({ symbol, count }))
    .sort((a, b) => b.count - a.count || a.symbol.localeCompare(b.symbol))
    .slice(0, limit);
}

const LABEL_WIDTH = 170;
const BAR_MAX_WIDTH = 320;
const COUNT_GUTTER = 44;
const ROW_HEIGHT = 30;
const BAR_HEIGHT = 16;
const TOP_PAD = 8;
const CHART_WIDTH = LABEL_WIDTH + BAR_MAX_WIDTH + COUNT_GUTTER;

export default function WarningsChart({ warningGroups, warnings }: WarningsChartProps) {
  const { t } = useT();
  const { rows, accounts } = useMemo(() => buildKindRows(warningGroups), [warningGroups]);
  const topSymbols = useMemo(() => buildTopSymbols(warnings), [warnings]);

  if (rows.length === 0) {
    return <p className="placeholder wc-empty">{t("portfolio.warningsChart.empty")}</p>;
  }

  const maxTotal = Math.max(1, ...rows.map((r) => r.total));
  const chartHeight = rows.length * ROW_HEIGHT + TOP_PAD * 2;
  const maxSymbolCount = topSymbols[0]?.count ?? 0;

  return (
    <div className="wc-root">
      <svg
        className="wc-svg"
        viewBox={`0 0 ${CHART_WIDTH} ${chartHeight}`}
        role="img"
        aria-label={t(
          rows.length === 1 ? "portfolio.warningsChart.ariaLabel_one" : "portfolio.warningsChart.ariaLabel_other",
          { count: rows.length },
        )}
      >
        {rows.map((row, i) => {
          const y = TOP_PAD + i * ROW_HEIGHT;
          let cursor = LABEL_WIDTH;
          const segments = row.segments.map((seg) => {
            const width = (seg.count / maxTotal) * BAR_MAX_WIDTH;
            const x = cursor;
            cursor += width;
            return { ...seg, x, width };
          });
          return (
            <g key={row.kind}>
              <text x={0} y={y + BAR_HEIGHT / 2} dominantBaseline="middle" className="wc-kind-label">
                {row.label}
              </text>
              {segments.map((seg) => (
                <rect
                  key={seg.key}
                  x={seg.x}
                  y={y}
                  width={Math.max(seg.width, 0)}
                  height={BAR_HEIGHT}
                  fill={seg.color}
                >
                  <title>{`${row.label} · ${seg.account} · ${seg.count}`}</title>
                </rect>
              ))}
              <text x={cursor + 6} y={y + BAR_HEIGHT / 2} dominantBaseline="middle" className="wc-count-label">
                {row.total}
              </text>
            </g>
          );
        })}
      </svg>

      {accounts.length > 0 && (
        <ul className="wc-legend">
          {accounts.map((a, i) => (
            <li key={a} className="wc-legend-row">
              <span
                className="wc-swatch"
                style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }}
                aria-hidden="true"
              />
              <span>{a}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="wc-top-symbols">
        <h3 className="wc-top-symbols-title">{t("portfolio.warningsChart.topSymbolsTitle")}</h3>
        {topSymbols.length === 0 ? (
          <p className="muted wc-top-symbols-empty">{t("portfolio.warningsChart.noSymbols")}</p>
        ) : (
          <ul className="wc-top-symbols-list">
            {topSymbols.map((s) => {
              const pct = maxSymbolCount > 0 ? (s.count / maxSymbolCount) * 100 : 0;
              return (
                <li key={s.symbol} className="wc-top-symbol-row">
                  <span className="wc-top-symbol-label">{s.symbol}</span>
                  <span className="wc-top-symbol-bar-track">
                    <span className="wc-top-symbol-bar-fill" style={{ width: `${pct}%` }} />
                  </span>
                  <span className="wc-top-symbol-count">{s.count}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
