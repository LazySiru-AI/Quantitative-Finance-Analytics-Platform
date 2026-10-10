/**
 * One influencer's call scorecard (Phase 3a) -- how their dated ticker calls would have looked if
 * acted on the day they were made. Sits alongside `PersonaCard.tsx` (the rolling digest) and
 * `PersonaProfile.tsx` (the standing profile) under the same persona on `/personas`: this component
 * is the backward-looking measurement of what actually happened to the calls they made, priced
 * against real bars.
 *
 * **Presentational only -- this component fetches nothing.** `Personas.tsx` owns fetching
 * `GET /{slug}/scorecard`, the same split `PersonaCard.tsx`'s and `PersonaProfile.tsx`'s own
 * docstrings establish. `state` is the discriminated union below rather than a bare
 * `PersonaScorecard | null`, so "still loading" / "the fetch actually failed" cannot be confused
 * with a loaded scorecard -- see `docs/INFLUENCER-CONTRACT.md`, "Phase 3a", and `@/api/personas`'s
 * docstring on the same section.
 *
 * **Unlike `PersonaProfile.tsx`'s `ProfileFetchState`, there is no `not_found` phase here.** Per the
 * contract, `GET /scorecard`'s `404` means "unknown persona slug" -- an actual error, not "not yet
 * scored" the way `GET /profile`'s `404` means "never consolidated". A persona with no dated calls
 * still answers `200` with `scored_calls: []` and `hit_rate: null`; that empty state is handled
 * entirely inside the `"loaded"` phase below, not as a separate fetch-state branch.
 *
 * This file exists to enforce the Phase 3a product guardrails, not merely style them:
 *
 * 1. **Descriptive, backward-looking framing, never a claim they beat the market and never
 *    advice.** The caption at the top of every rendered state says exactly that, in those terms --
 *    "how their past calls would have looked if acted on the day they were made". Hit rate is never
 *    presented as a prediction or an endorsement.
 * 2. **`hit_rate: null` renders differently from `0`, and so does `median_return_pct: null`.** `null`
 *    reads as "not enough scored calls yet" / "not enough data yet"; `0` reads as the real number it
 *    is (`0/N (0%)` / `+0.00%`). See `@/api/personas`'s docstring, "Phase 3a", for why these must
 *    never be conflated.
 * 3. **Per-call return is colored by the *sign* of `return_pct`, never by `outcome`.** A bearish call
 *    that "played out" (price fell) still shows a *negative*, red `return_pct` -- that is the actual
 *    price move, not a verdict. `outcome` renders as its own separate badge instead.
 * 4. **A `null` return renders as an em dash plus its outcome badge**, so the reason the number is
 *    missing (`pending` / `no_data`) is never lost alongside the missing number.
 * 5. **Every outcome gets its own plainly-worded, visually distinct badge** -- `played_out`,
 *    `went_against`, `flat`, `not_directional`, `pending`, `no_data` -- via `outcomeLabel`
 *    (`@/api/personas`), the one place that wording lives.
 * 6. **Non-empty `warnings` always render**, the same `.warning-list` treatment `PersonaCard.tsx`
 *    gives `DigestCard.warnings` -- never swallowed.
 * 7. **`basis` ("adjusted" vs "close") is surfaced subtly** as a `title` attribute on the return
 *    figure via `callBasisNote` (`@/api/personas`) -- not hidden, but not shouted either, since most
 *    calls share one basis and only a mixed-basis persona needs the reader to notice.
 * 8. **Each call's symbol links to `/symbol/{symbol}`**, matching `PersonaCard.tsx`'s ticker chips
 *    and `PersonaProfile.tsx`'s thesis links.
 *
 * **Internationalised** through `misc.personas.scorecard.*`/`personaScorecard.*` and the shared
 * `outcomeLabel`/`callBasisNote`/`stanceLabel` (`@/api/personas`), like the rest of `/personas`.
 * Numbers stay in en-US formatting and each warning's backend `source`/`reason` renders verbatim;
 * everything else routes through `t()`.
 *
 * **Fixed-horizon extension.** `scorecard.horizon_stats` (one `HorizonStat` per 5/20/60 trading
 * days) is the window-independent counterpart to the top-level `hit_rate`/`median_return_pct`,
 * which are "so far" -- return-to-today, still growing as more calls elapse. Each `HorizonStat`'s
 * `hit_rate_ci`/`return_ci` render through the shared `StatValue` (`@/components/StatValue`),
 * which already carries the null-vs-zero and small-n-vs-large-n discipline this file's rule 2
 * requires; `median_return_pct: null` (no elapsed call at that horizon yet) still gets its own
 * explicit "not enough data yet" render, matching the aggregate. The top-level `hit_rate_ci`
 * renders beside the aggregate hit-rate stat for the same reason. Per-call `CallScore.horizons`
 * render inside `ScorecardRow` as compact badges; a `HorizonReturn` with `complete: false` (the
 * window has not elapsed yet) renders as "too recent", never as a `0%` return -- the same
 * distinction rule 2 draws for `null`, extended to "not yet measurable" rather than "measured and
 * zero".
 */
import { Link } from "react-router-dom";

import {
  callBasisNote,
  formatRelativeAge,
  formatReturnPct,
  outcomeLabel,
  stanceLabel,
  type CallScore,
  type HorizonReturn,
  type HorizonStat,
  type PersonaScorecard as Scorecard,
} from "@/api/personas";
import { ScrollRegion } from "@/components/ScrollPanel";
import { StatValue } from "@/components/StatValue";
import { useT } from "@/i18n";

/** Distinguishes "still loading" / "the fetch actually failed" from a loaded scorecard -- see this
 * file's own docstring on why there is no `not_found` phase here (unlike `ProfileFetchState`).
 * `Personas.tsx` is the only producer. */
export type ScorecardFetchState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "loaded"; scorecard: Scorecard };

export interface PersonaScorecardProps {
  displayName: string;
  state: ScorecardFetchState;
}

export default function PersonaScorecard({ displayName, state }: PersonaScorecardProps) {
  const { t } = useT();
  return (
    <div className="panel persona-scorecard">
      <h3 className="persona-card-subhead">{t("misc.personas.scorecard.heading")}</h3>
      <p className="muted persona-scorecard-caption">
        {t("misc.personas.scorecard.caption", { name: displayName })}
      </p>

      <ScrollRegion size="md" label={t("misc.personas.scorecard.heading")}>
        {state.phase === "loading" && (
          <div className="placeholder persona-scorecard-loading">
            {t("misc.personas.scorecard.loading")}
          </div>
        )}

        {state.phase === "error" && (
          <div className="callout callout-danger persona-scorecard-error" role="alert">
            {state.message}
          </div>
        )}

        {state.phase === "loaded" && <ScorecardBody scorecard={state.scorecard} />}
      </ScrollRegion>
    </div>
  );
}

/** `persona-scorecard-return`(-pos|-neg) by the SIGN of the value alone, per this file's rule 3 --
 * `null` gets no sign class, so a caller falls back to a neutral render. Shared by the aggregate
 * body, the horizon summary, and each `ScorecardRow`'s per-call horizon badges. */
function returnSignClass(value: number | null): string {
  if (value === null) return "persona-scorecard-return";
  return `persona-scorecard-return persona-scorecard-return-${value >= 0 ? "pos" : "neg"}`;
}

function ScorecardBody({ scorecard }: { scorecard: Scorecard }) {
  const { t } = useT();
  const {
    directional_count,
    played_out,
    hit_rate,
    hit_rate_ci,
    median_return_pct,
    horizon_stats,
    scored_calls,
    warnings,
  } = scorecard;

  return (
    <div className="persona-scorecard-body">
      <div className="persona-scorecard-aggregate">
        <div className="persona-scorecard-stat">
          <span className="persona-scorecard-stat-label">{t("misc.personas.scorecard.hitRate")}</span>
          <span className="persona-scorecard-stat-value">
            {hit_rate === null
              ? t("misc.personas.scorecard.hitRateNone")
              : `${played_out}/${directional_count} (${Math.round(hit_rate * 100)}%)`}
          </span>
          <span className="persona-scorecard-stat-label">
            {t("personaScorecard.aggregate.hitRateCiLabel")}
          </span>
          <StatValue estimate={hit_rate_ci} format="rate" data-testid="scorecard-hit-rate-ci" />
        </div>
        <div className="persona-scorecard-stat">
          <span className="persona-scorecard-stat-label">{t("misc.personas.scorecard.medianReturn")}</span>
          <span className="persona-scorecard-stat-value">
            {median_return_pct === null
              ? t("misc.personas.scorecard.medianNone")
              : formatReturnPct(median_return_pct)}
          </span>
        </div>
      </div>

      {horizon_stats.length > 0 && (
        <div className="persona-scorecard-body">
          <h4 className="persona-card-subhead">{t("personaScorecard.horizon.heading")}</h4>
          <p className="muted persona-scorecard-caption">{t("personaScorecard.horizon.caption")}</p>
          <ul className="persona-scorecard-list">
            {horizon_stats.map((hs) => (
              <HorizonStatRow key={hs.days} stat={hs} />
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <ul className="warning-list persona-scorecard-warnings">
          {warnings.map((w, i) => (
            <li key={i}>{`${w.source}: ${w.reason}`}</li>
          ))}
        </ul>
      )}

      {scored_calls.length === 0 ? (
        <p className="muted persona-scorecard-empty">{t("misc.personas.scorecard.empty")}</p>
      ) : (
        <ul className="persona-scorecard-list">
          {scored_calls.map((call, i) => (
            <ScorecardRow key={`${call.note_id}-${call.symbol}-${i}`} call={call} />
          ))}
        </ul>
      )}
    </div>
  );
}

/** One fixed-horizon aggregate row -- hit rate + its Wilson CI, the median return-to-that-horizon
 * (plain, null-safe like the aggregate above), and the mean return + its bootstrap CI. Both CI
 * fields route through `StatValue`, so a `directional_count === 0` horizon renders "no data" for
 * both rather than a fabricated `0%`. */
function HorizonStatRow({ stat }: { stat: HorizonStat }) {
  const { t } = useT();
  return (
    <li className="persona-scorecard-row" data-testid={`horizon-row-${stat.days}`}>
      <span className="persona-scorecard-stat-value">{t("personaScorecard.horizon.label", { days: stat.days })}</span>
      <div className="persona-scorecard-stat">
        <span className="persona-scorecard-stat-label">{t("personaScorecard.horizon.hitRate")}</span>
        <StatValue estimate={stat.hit_rate_ci} format="rate" data-testid={`horizon-hit-rate-${stat.days}`} />
      </div>
      <div className="persona-scorecard-stat">
        <span className="persona-scorecard-stat-label">{t("personaScorecard.horizon.medianReturn")}</span>
        <span
          className={
            stat.median_return_pct === null ? "muted" : returnSignClass(stat.median_return_pct)
          }
          data-testid={`horizon-median-${stat.days}`}
        >
          {stat.median_return_pct === null
            ? t("personaScorecard.horizon.noData")
            : formatReturnPct(stat.median_return_pct)}
        </span>
      </div>
      <div className="persona-scorecard-stat">
        <span className="persona-scorecard-stat-label">{t("personaScorecard.horizon.meanReturn")}</span>
        <StatValue estimate={stat.return_ci} format="percent" data-testid={`horizon-mean-${stat.days}`} />
      </div>
    </li>
  );
}

/** One scored call -- rules 3-4 and 7-8 in this file's docstring: return is colored by sign alone,
 * outcome is its own badge, basis rides along as a `title`, symbol links to `/symbol/{symbol}`. */
function ScorecardRow({ call }: { call: CallScore }) {
  const sign = call.return_pct === null ? null : call.return_pct >= 0 ? "pos" : "neg";
  const basisNote = callBasisNote(call.basis);

  return (
    <li className="persona-scorecard-row">
      <Link className="persona-ticker-chip" to={`/symbol/${encodeURIComponent(call.symbol)}`}>
        <span className="position-symbol">{call.symbol}</span>
        <span className={`persona-ticker-stance persona-ticker-stance-${call.stance}`}>
          {stanceLabel(call.stance)}
        </span>
      </Link>
      <span className="persona-scorecard-said-on" title={call.said_on}>
        {formatRelativeAge(call.said_on)}
      </span>
      <span
        className={`persona-scorecard-return${sign ? ` persona-scorecard-return-${sign}` : ""}`}
        title={basisNote ?? undefined}
      >
        {formatReturnPct(call.return_pct)}
      </span>
      <span className={`persona-outcome-badge persona-outcome-${call.outcome}`}>
        {outcomeLabel(call.outcome)}
      </span>
      {call.horizons.length > 0 && (
        <span className="persona-scorecard-said-on" data-testid={`call-horizons-${call.note_id}-${call.symbol}`}>
          {call.horizons.map((h, i) => (
            <HorizonBadge key={h.days} horizon={h} separator={i > 0} />
          ))}
        </span>
      )}
    </li>
  );
}

/** One per-call fixed-horizon badge -- `complete: false` (the window has not elapsed yet) renders
 * as "too recent", NEVER as `0%`; this is the same null-vs-measured-zero distinction this file's
 * rule 2 draws for the aggregate, extended to "not yet measurable". */
function HorizonBadge({ horizon, separator }: { horizon: HorizonReturn; separator: boolean }) {
  const { t } = useT();
  return (
    <>
      {separator ? " · " : null}
      {t("personaScorecard.horizon.label", { days: horizon.days })}{" "}
      {horizon.complete ? (
        <span className={returnSignClass(horizon.return_pct)}>{formatReturnPct(horizon.return_pct)}</span>
      ) : (
        <span className="muted">{t("personaScorecard.horizon.tooRecent")}</span>
      )}
    </>
  );
}
