/**
 * "Key indicators" card: the four numbers a reader actually checks every day, condensed into one
 * card that sits directly under Fear & Greed -- before the reader has to go hunting through the
 * Rates/Oil/Movers sections for them.
 *
 * Three of the four series (WTI, the Dollar Index, Bitcoin) already live in `snapshot.oil` /
 * `snapshot.movers`; the 10-year yield lives in `snapshot.rates`. This component does not fetch or
 * duplicate any of that -- it just re-presents four specific entries already on the snapshot, plus
 * one interactive chart per tile via `MacroSeriesChart`, which does its own fetching against
 * `/api/macro/series/{id}`.
 *
 * **Tone is not uniform across the four tiles**, and that split is the whole point of keeping this
 * a distinct component rather than a fifth generic tile grid:
 *   - US 10-Year Treasury is a *yield*, not a price someone holds. An "up" day is not a gain for
 *     anyone reading this card, so it stays `tone="neutral"` -- same rule `Macro.tsx` already
 *     applies to the Rates section, preserved here rather than reinvented.
 *   - WTI crude also stays `tone="neutral"`, despite being a price. Not because the argument for
 *     colouring it is weak -- a barrel is as tradeable as a coin -- but because `Macro.tsx` renders
 *     this very series again, a section further down, with `tone="neutral"`. Colouring the same
 *     number green here and leaving it grey there would make one page hold two conventions about
 *     one figure, and a reader who noticed would be right to trust neither. If oil should be
 *     signed, the Oil section is where that changes, and then this follows it.
 *   - The Dollar Index and Bitcoin get the conventional green-up/red-down `"signed"` treatment.
 *     Neither appears anywhere else on the page except inside the Movers grid, which already
 *     colours them exactly this way -- so here the consistent choice and the correct one agree.
 *
 * **Bitcoin degrades gracefully.** `BTC-USD` is being added to the backend movers list by another
 * workstream concurrently with this one, so `snapshot.movers` may or may not contain it depending
 * on deploy order. Rather than hard-coding a placeholder value (which would silently go stale the
 * moment the real number exists) this component just checks whether the entry is present and
 * renders a clearly-labelled "not yet available" slot when it isn't. No code change is needed here
 * once the backend ships it -- the tile lights up on its own the next time the snapshot is fetched.
 */
import type { MacroSnapshot, MacroUnit, SeriesChange } from "@/api/macro";
import { formatChange, formatObservationDate, formatValue } from "@/api/macro";
import { formatPrice } from "@/api/market";
import MacroSeriesChart from "@/components/MacroSeriesChart";
import { useT } from "@/i18n";

import "./MacroKeyIndicators.css";

export interface MacroKeyIndicatorsProps {
  snapshot: MacroSnapshot;
  /**
   * Colour every tile's up/down change green/red by sign, overriding the per-tile `tone` that
   * otherwise leaves the 10-Year yield and WTI grey. Off by default, so the Macro page keeps the
   * neutral convention its own Rates/Oil sections further down the page use for these same two
   * series (see the module docstring). The Overview page opts in: it is a glance-first summary with
   * no second copy of these numbers beside it to disagree with, and a reader there asked for the
   * direction to be readable at a glance rather than muted.
   */
  colorAllChanges?: boolean;
}

/** Which horizons render, and in what order -- matches `MacroTile`'s own `HORIZONS` list so the
 * two card styles read consistently across the page. */
const HORIZONS: { key: "day" | "week" | "month" | "ytd"; label: string }[] = [
  { key: "day", label: "1D" },
  { key: "week", label: "1W" },
  { key: "month", label: "1M" },
  { key: "ytd", label: "YTD" },
];

type Tone = "neutral" | "signed";

/** Normalised shape both a `MacroTile` (rates/oil) and a `MoverTile` (movers) can be reduced to --
 * lets the rendering half of this component stay ignorant of which snapshot array a value came
 * from. `null` means "the snapshot doesn't have this entry yet," not "the value is zero." */
interface IndicatorData {
  valueText: string;
  change: SeriesChange;
  asOf: string | null;
}

interface IndicatorConfig {
  key: string;
  title: string;
  tone: Tone;
  /** Series id `MacroSeriesChart` / `macroApi.series` can fetch. See the module docstring in
   * `@/api/macro` for why this is a distinct id from the tile/mover key. */
  seriesId: string;
  /** Unit for the embedded chart's axis formatting. Movers carry no `unit` field on the wire (only
   * `currency`), so this is sourced from the backend's own series catalog
   * (`backend/app/market/macro.py::_MOVERS`) rather than guessed. */
  chartUnit: MacroUnit;
  data: IndicatorData | null;
}

export default function MacroKeyIndicators({ snapshot, colorAllChanges = false }: MacroKeyIndicatorsProps) {
  const { t } = useT();
  const us10y = snapshot.rates.find((tile) => tile.key === "us10y") ?? null;
  const wti = snapshot.oil.find((tile) => tile.key === "wti") ?? null;
  const dxy = snapshot.movers.find((m) => m.symbol === "DX-Y.NYB") ?? null;
  const btc = snapshot.movers.find((m) => m.symbol === "BTC-USD") ?? null;

  const indicators: IndicatorConfig[] = [
    {
      key: "us10y",
      title: "US 10-Year Treasury",
      tone: "neutral",
      seriesId: "DGS10",
      chartUnit: "percent",
      data: us10y
        ? { valueText: formatValue(us10y.value, us10y.unit), change: us10y.change, asOf: us10y.as_of }
        : null,
    },
    {
      key: "wti",
      title: "WTI Crude",
      // Neutral to match the Oil section below, not because oil is unownable. See the module note.
      tone: "neutral",
      seriesId: "DCOILWTICO",
      chartUnit: "usd",
      data: wti
        ? { valueText: formatValue(wti.value, wti.unit), change: wti.change, asOf: wti.as_of }
        : null,
    },
    {
      key: "dxy",
      title: "US Dollar Index",
      tone: "signed",
      seriesId: "DX-Y.NYB",
      chartUnit: "index",
      // `formatValue(..., "index")`, NOT `formatPrice(..., dxy.currency)`. Every `MoverTile` carries
      // `currency: "USD"` because that is the currency its price is *quoted in*, and for SPY or GLD
      // that makes `formatPrice` right. DXY is not a dollar amount at all -- it is an index level
      // around 98.9, benchmarked to 100 -- so a `$` prefix asserts a unit the number does not have.
      // The backend already says so: `_MOVERS` declares this symbol `MacroUnit.INDEX`, which is the
      // same unit this tile's own chart axis uses. Formatting the headline as currency while the
      // chart beneath it plots a bare index made one tile disagree with itself.
      data: dxy
        ? { valueText: formatValue(dxy.price, "index"), change: dxy.change, asOf: dxy.as_of }
        : null,
    },
    {
      key: "btc",
      title: "Bitcoin",
      tone: "signed",
      seriesId: "BTC-USD",
      chartUnit: "usd",
      data: btc
        ? { valueText: formatPrice(btc.price, btc.currency), change: btc.change, asOf: btc.as_of }
        : null,
    },
  ];

  return (
    <section className="panel macro-key-card">
      <h2>{t("misc.keyIndicators.title")}</h2>
      <div className="macro-key-grid">
        {indicators.map(({ key, ...indicator }) => (
          <KeyIndicatorTile key={key} {...indicator} colorAllChanges={colorAllChanges} />
        ))}
      </div>
    </section>
  );
}

function KeyIndicatorTile({
  title,
  tone,
  seriesId,
  chartUnit,
  data,
  colorAllChanges,
}: Omit<IndicatorConfig, "key"> & { colorAllChanges: boolean }) {
  const { t } = useT();
  return (
    <div className="macro-key-tile" data-tile={seriesId} data-tone={tone}>
      <div className="macro-key-head">
        <span className="macro-key-label">{title}</span>
      </div>

      {data ? (
        <>
          <div className="macro-key-value">{data.valueText}</div>

          <div className="macro-key-changes">
            {HORIZONS.map((h) => (
              <ChangeStat
                key={h.key}
                label={h.label}
                value={data.change[h.key]}
                mode={data.change.mode}
                tone={tone}
                colorAllChanges={colorAllChanges}
              />
            ))}
          </div>

          <div className="macro-key-chart">
            <MacroSeriesChart seriesId={seriesId} title={title} unit={chartUnit} height={160} compact />
          </div>

          <div className="macro-key-foot">{t("misc.keyIndicators.asOf", { date: formatObservationDate(data.asOf) })}</div>
        </>
      ) : (
        // Backend hasn't shipped this entry to the snapshot yet (currently only reachable for BTC,
        // see the module docstring). Deliberately no chart here either -- `MacroSeriesChart` would
        // hit `/api/macro/series/BTC-USD` directly and might well succeed even while the mover list
        // lags behind, but showing a live chart above a headline value that says "unavailable"
        // would read as a contradiction rather than a coherent degraded state.
        <div className="macro-key-unavailable">
          <span className="macro-key-value macro-key-value-empty">—</span>
          <span className="macro-key-unavailable-note">{t("misc.keyIndicators.notYetAvailable")}</span>
        </div>
      )}
    </div>
  );
}

function ChangeStat({
  label,
  value,
  mode,
  tone,
  colorAllChanges,
}: {
  label: string;
  value: number | null;
  mode: SeriesChange["mode"];
  tone: Tone;
  colorAllChanges: boolean;
}) {
  const text = formatChange(value, mode);
  // `colorAllChanges` forces the green-up/red-down treatment onto the `tone="neutral"` tiles too;
  // without it, only `tone="signed"` tiles colour (the original convention, kept as the default).
  const signed = tone === "signed" || colorAllChanges;
  const cls = signed && value !== null ? (value > 0 ? "pos" : value < 0 ? "neg" : "") : "";
  return (
    <div className="macro-key-change-stat">
      <span className="macro-key-change-label">{label}</span>
      <span className={`macro-key-change-value${cls ? ` ${cls}` : ""}`}>{text}</span>
    </div>
  );
}
