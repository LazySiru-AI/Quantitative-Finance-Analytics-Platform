/**
 * Drawdown profile: the deepest historical episodes plus the current one, if the symbol is
 * underwater right now.
 *
 * `basis` (close / adj_close / intraday) changes the depth of every episode -- a split-adjusted
 * close and an intraday low are not the same instrument-history question, and neither is "wrong".
 * The rule from `api/backtest.ts`'s module docstring is that the basis must sit next to the numbers
 * it produced, not only in the selector: the column header names it (`Depth (basis)`) and the
 * current-drawdown card repeats it in its own label, so a screenshot of either is self-describing
 * without the control visible.
 *
 * `episodes_considered` is shown next to the table heading so a top-10 list never reads as the whole
 * history. `bars_to_recovery: null` renders as an em dash (never `0`), and `still_underwater`
 * episodes render through `formatUnderwater`, which appends "(ongoing)" rather than reporting a bars
 * count that looks final.
 */
import { useState } from "react";

import {
  formatDepth,
  formatUnderwater,
  type DrawdownBasis,
  type DrawdownEpisode,
} from "@/api/backtest";
import type { Interval, MarketWarning } from "@/api/market";
import StatGrid from "@/components/StatGrid";
import { useDrawdownProfile } from "@/hooks/useBacktest";
import { type Translator, useT } from "@/i18n";

const BASES: DrawdownBasis[] = ["close", "adj_close", "intraday"];

function basisLabel(basis: DrawdownBasis, t: Translator): string {
  switch (basis) {
    case "close":
      return t("strategy.drawdown.basis.close");
    case "adj_close":
      return t("strategy.drawdown.basis.adjClose");
    case "intraday":
      return t("strategy.drawdown.basis.intraday");
    default:
      return basis;
  }
}

interface DrawdownTableProps {
  symbol: string;
  interval: Interval;
}

export default function DrawdownTable({ symbol, interval }: DrawdownTableProps) {
  const { t } = useT();
  const [basis, setBasis] = useState<DrawdownBasis>("close");
  const { profile, phase, message } = useDrawdownProfile(symbol, interval, basis);

  return (
    <div className="panel">
      <h2>{t("strategy.drawdown.title")}</h2>

      <div className="bt-basis-picker" role="tablist" aria-label={t("strategy.drawdown.basisAriaLabel")}>
        <span className="bt-control-label">{t("strategy.drawdown.basisLabel")}</span>
        {BASES.map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={value === basis}
            className={`timeframe-tab${value === basis ? " active" : ""}`}
            onClick={() => setBasis(value)}
          >
            {basisLabel(value, t)}
          </button>
        ))}
      </div>

      {phase === "loading" && <div className="placeholder">{t("strategy.drawdown.loading")}</div>}
      {(phase === "notfound" || phase === "error") && (
        <div className="placeholder">{message}</div>
      )}

      {phase === "loaded" && profile && (
        <>
          <StatGrid
            items={[
              { label: t("common.symbol"), value: profile.symbol },
              {
                label: t("strategy.drawdown.stat.sample"),
                value: `${profile.first_bar ?? "—"} → ${profile.last_bar ?? "—"}`,
              },
              { label: t("strategy.drawdown.stat.bars"), value: profile.bars.toLocaleString() },
              {
                label: t("strategy.drawdown.stat.episodesConsidered"),
                value: profile.episodes_considered.toLocaleString(),
              },
            ]}
          />

          <DrawdownWarnings warnings={profile.warnings} />

          <CurrentDrawdownCard episode={profile.current} basis={profile.basis} />

          <h3>
            {t("strategy.drawdown.topEpisodesHeading", {
              n: profile.episodes.length,
              total: profile.episodes_considered.toLocaleString(),
            })}
          </h3>

          {profile.episodes.length === 0 ? (
            <div className="placeholder">{t("strategy.drawdown.noEpisodes", { symbol })}</div>
          ) : (
            <div className="table-wrap">
              <table
                className="data-table bt-drawdown-table"
                aria-label={t("strategy.drawdown.tableAriaLabel", {
                  symbol,
                  basis: basisLabel(profile.basis, t),
                })}
              >
                <thead>
                  <tr>
                    <th scope="col">{t("strategy.drawdown.header.peak")}</th>
                    <th scope="col">{t("strategy.drawdown.header.trough")}</th>
                    <th scope="col" className="num">
                      {t("strategy.drawdown.header.depth", { basis: basisLabel(profile.basis, t) })}
                    </th>
                    <th scope="col" className="num">
                      {t("strategy.drawdown.header.barsToTrough")}
                    </th>
                    <th scope="col">{t("strategy.drawdown.header.recovery")}</th>
                    <th scope="col">{t("strategy.drawdown.header.underwater")}</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.episodes.map((ep, i) => (
                    <EpisodeRow key={`${ep.peak_date}-${i}`} episode={ep} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function DrawdownWarnings({ warnings }: { warnings: MarketWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="warnings-strip">
      {warnings.map((w, i) => (
        <div className="warning-chip" key={`${w.kind}-${i}`}>
          <span className="kind">{w.kind}</span>
          <span className="message">{w.message}</span>
        </div>
      ))}
    </div>
  );
}

/** The live drawdown, if any -- often not in the top-N table by depth, and it is the question this
 *  card exists to answer at a glance. The basis is repeated here too, not only in the shared control.
 *
 *  Exported because the Report page renders the same card. It used to keep its own copy, and the
 *  copy did not receive the `depth_now` fix below: `/backtest` showed XLE 1.0% off its peak while
 *  `/report/XLE` showed 15.6% for the same episode on the same day, which is the pre-fix reading of
 *  the same defect this comment describes. A UAT persona found it by loading both. One renderer, so
 *  there is nothing left to diverge. */
export function CurrentDrawdownCard({
  episode,
  basis,
}: {
  episode: DrawdownEpisode | null;
  basis: DrawdownBasis;
}) {
  const { t } = useT();
  if (episode === null) {
    return (
      <div className="bt-current-drawdown bt-current-drawdown-clear">
        <span className="bt-current-drawdown-label">
          {t("strategy.drawdown.currentLabel", { basis: basisLabel(basis, t) })}
        </span>
        <span className="bt-current-drawdown-clear-text">{t("strategy.drawdown.notUnderwater")}</span>
      </div>
    );
  }
  // The headline is `depth_now` -- peak to the latest print -- because "current drawdown" is a
  // question about today. It used to show `depth`, the ongoing episode's worst bar, which read
  // -15.6% on a name trading 1.04% off its high. Both figures are worth having and they are now
  // shown as the two different things they are, with the worse one clearly labelled as the low.
  //
  // `depth` remains the fallback: it is what the field means for a recovered episode, where
  // `depth_now` is null by design.
  const now = episode.depth_now ?? episode.depth;
  return (
    <div
      className={`bt-current-drawdown${episode.still_underwater ? " bt-current-drawdown-active" : ""}`}
    >
      <span className="bt-current-drawdown-label">
        {t("strategy.drawdown.currentLabel", { basis: basisLabel(basis, t) })}
      </span>
      <span className="bt-current-drawdown-depth">{formatDepth(now)}</span>
      {episode.last_value_date !== null && (
        <span className="bt-current-drawdown-meta">
          {t("strategy.drawdown.asOf", { date: episode.last_value_date })}
        </span>
      )}
      <span className="bt-current-drawdown-meta">
        {t("strategy.drawdown.peakMeta", {
          date: episode.peak_date,
          value: episode.peak_value.toLocaleString(),
        })}
      </span>
      {episode.depth_now !== null && (
        // Phrased as an action in the past ("fell N% to its low on <date>") rather than as a second
        // labelled percentage. `formatDepth` drops the sign by convention, so two bare percentages
        // stacked on one card would read as two estimates of the same quantity that disagree --
        // which is the confusion this whole change exists to remove, reintroduced one line lower.
        <span className="bt-current-drawdown-meta">
          {t("strategy.drawdown.fellToLow", {
            depth: formatDepth(episode.depth),
            date: episode.trough_date,
          })}
        </span>
      )}
      <span className="bt-current-drawdown-meta">
        {t("strategy.drawdown.underwaterSuffix", { underwater: formatUnderwater(episode) })}
      </span>
      {episode.recovery_date !== null && (
        <span className="bt-current-drawdown-meta">
          {t("strategy.drawdown.recoveredMeta", { date: episode.recovery_date })}
        </span>
      )}
    </div>
  );
}

function EpisodeRow({ episode }: { episode: DrawdownEpisode }) {
  const { t } = useT();
  return (
    <tr>
      <td>
        {episode.peak_date}
        <div className="bt-cell-sub">{episode.peak_value.toLocaleString()}</div>
      </td>
      <td>
        {episode.trough_date}
        <div className="bt-cell-sub">{episode.trough_value.toLocaleString()}</div>
      </td>
      <td className="num">{formatDepth(episode.depth)}</td>
      <td className="num">{episode.bars_to_trough.toLocaleString()}</td>
      <td>
        {episode.recovery_date ?? "—"}
        <div className="bt-cell-sub">
          {episode.bars_to_recovery === null
            ? "—"
            : t("strategy.backtest.underwaterBars", { count: episode.bars_to_recovery.toLocaleString() })}
        </div>
      </td>
      <td className={episode.still_underwater ? "bt-underwater-ongoing" : ""}>
        {formatUnderwater(episode)}
      </td>
    </tr>
  );
}
