/**
 * CNN Fear & Greed panel: score, band, component breakdown, and provenance.
 *
 * Two things the contract (`frontend/src/api/macro.ts`) calls out that this component exists to
 * get right:
 *
 * - `data` itself can be `null` -- CNN's unofficial endpoint is down *and* the local composite
 *   could not be computed either. That is a real state, not a crash: render an explained absence.
 * - `data.source === "composite"` means this number is **our approximation of CNN's index, not
 *   CNN's own number** -- CNN publishes each component's raw value but not the normalisation that
 *   maps it to 0-100, so the composite re-derives its own scoring. It tracks direction and rough
 *   level but will not match, and the UI says so in the body of the panel, not just a tooltip.
 */
import type { FearGreed, FearGreedComponent, Rating } from "@/api/macro";
import { formatObservationDate, ratingFor } from "@/api/macro";
import FearGreedHistoryChart from "@/components/FearGreedHistoryChart";
import { useT, type MessageKey, type Translator } from "@/i18n";
import { resolveVocab, resolveVocabOrNull } from "@/i18n/messages/serverVocab";

const RATING_LABEL_KEYS: Record<Rating, MessageKey> = {
  "extreme fear": "misc.fearGreed.rating.extremeFear",
  fear: "misc.fearGreed.rating.fear",
  neutral: "misc.fearGreed.rating.neutral",
  greed: "misc.fearGreed.rating.greed",
  "extreme greed": "misc.fearGreed.rating.extremeGreed",
};

const BAND_RATINGS: Rating[] = ["extreme fear", "fear", "neutral", "greed", "extreme greed"];

function ratingLabel(rating: Rating, t: Translator): string {
  return t(RATING_LABEL_KEYS[rating]);
}

/**
 * The component's name and the phrase under it, from `serverVocab` when this build knows the id.
 *
 * `component.key` is the stable wire token (`market_momentum_sp500`, `put_call_options`); CNN's own
 * English name and description ride along on the same row. An id this build has not seen -- an
 * eighth component, a rename upstream -- renders exactly what the server sent, which is a Korean
 * page with one English row rather than no page at all. Never a closed union over a server string.
 */
function componentName(component: FearGreedComponent, t: Translator): string {
  return resolveVocab(t, `serverVocab.fearGreed.${component.key}.name`, component.label);
}

function componentDescription(component: FearGreedComponent, t: Translator): string | null {
  return resolveVocabOrNull(
    t,
    `serverVocab.fearGreed.${component.key}.description`,
    component.raw_description,
  );
}

/**
 * `raw_value` with its unit -- the local, translated twin of `formatComponentRaw` in `api/macro.ts`.
 *
 * Same two decimal places on every component regardless of magnitude, and the same rule that an
 * absent `raw_unit` renders as *no suffix* rather than a guessed one: the seven numbers are in seven
 * different units and a wrong label is worse than an absent one. Only the suffix differs -- `index`,
 * `ratio` and `pp` are words, so they go through the vocabulary, and an unrecognised unit prints as
 * the server sent it.
 */
function formatRaw(component: FearGreedComponent, t: Translator): string {
  if (component.raw_value === null) return "—";
  const value = component.raw_value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  if (!component.raw_unit) return value;
  return `${value} ${resolveVocab(t, `serverVocab.fearGreed.unit.${component.raw_unit}`, component.raw_unit)}`;
}

export default function FearGreedGauge({ data }: { data: FearGreed | null }) {
  const { t } = useT();

  if (data === null) {
    return (
      <div className="panel">
        <h2>{t("misc.fearGreed.title")}</h2>
        <div className="placeholder">{t("misc.fearGreed.unavailable")}</div>
      </div>
    );
  }

  const clampedScore = Math.max(0, Math.min(100, data.score));
  const isComposite = data.source === "composite";

  return (
    <div className="panel">
      <div className="fg-head">
        <h2>{t("misc.fearGreed.title")}</h2>
        <span className={`fg-source-badge${isComposite ? " composite" : " cnn"}`}>
          {isComposite ? t("misc.fearGreed.badge.composite") : "CNN"}
        </span>
      </div>

      {isComposite && (
        <div className="fg-composite-note">{t("misc.fearGreed.compositeNote")}</div>
      )}

      <div className="fg-score-row">
        <div className="fg-score">
          <span className="fg-score-value">{Math.round(data.score)}</span>
          <span className="fg-score-rating">{ratingLabel(data.rating, t)}</span>
          <ScoreDelta today={data.score} previousClose={data.previous_close} />
        </div>
        <div
          className="fg-meter"
          role="img"
          aria-label={t("misc.fearGreed.meterAriaLabel", {
            score: Math.round(data.score),
            rating: ratingLabel(data.rating, t),
          })}
        >
          <div className="fg-meter-track">
            <div className="fg-meter-marker" style={{ left: `${clampedScore}%` }} />
          </div>
          <div className="fg-meter-bands">
            {BAND_RATINGS.map((r) => (
              <span key={r} className="fg-band-label">
                {ratingLabel(r, t)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="fg-history">
        <FearGreedHistoryChart points={data.history} />
      </div>

      <div className="fg-prev-grid status-grid">
        <PrevStat label={t("misc.fearGreed.prev.close")} value={data.previous_close} />
        <PrevStat label={t("misc.fearGreed.prev.week")} value={data.previous_week} />
        <PrevStat label={t("misc.fearGreed.prev.month")} value={data.previous_month} />
        <PrevStat label={t("misc.fearGreed.prev.year")} value={data.previous_year} />
      </div>

      <div className="fg-asof">{t("misc.fearGreed.asOf", { date: formatObservationDate(data.as_of) })}</div>

      {data.components.length > 0 && (
        <div className="table-wrap">
          <table className="data-table fg-components">
            <thead>
              <tr>
                <th scope="col">{t("misc.fearGreed.table.component")}</th>
                <th scope="col">{t("misc.fearGreed.table.raw")}</th>
                {/* Empty for every row on a CNN-sourced reading, and that is not a gap in the
                    feed: CNN publishes each component's raw value and rating but never the
                    normalisation that maps one onto the other. Only the local composite computes a
                    per-component score, because only it can show its work. Seven unexplained em
                    dashes read as missing data, so the header says which case you are looking at.
                    Reported by a UAT persona, who could not tell the two apart. */}
                <th scope="col" title={scoreColumnNote(isComposite, t)}>
                  {t("misc.fearGreed.table.score")}
                  <span className="muted fg-col-note">
                    {isComposite
                      ? t("misc.fearGreed.table.scoreComputedHere")
                      : t("misc.fearGreed.table.scoreNotPublished")}
                  </span>
                </th>
                <th scope="col">{t("misc.fearGreed.table.rating")}</th>
                <th scope="col">{t("misc.fearGreed.table.asOf")}</th>
              </tr>
            </thead>
            <tbody>
              {data.components.map((c) => (
                <ComponentRow key={c.key} component={c} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.warnings.length > 0 && (
        <ul className="warning-list">
          {data.warnings.map((w, i) => (
            <li key={`${w.kind}-${i}`}>
              <span className="kind">{w.kind}</span> {w.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Today's score against yesterday's, shown right under the headline number.
 *
 * `previous_close` is CNN's prior *trading-day* close, so this is the day-over-day move a reader
 * would otherwise have to compute by eye from the "Previous close" tile further down the card.
 * Both sides are rounded to the same integer the headline shows before subtracting, so the arrow
 * can never say "+1" while the two visible whole numbers are equal. `previous_close` can be null
 * (the composite fallback does not always carry one); the row is omitted entirely in that case
 * rather than inventing a "0" that would read as "flat".
 */
function ScoreDelta({ today, previousClose }: { today: number; previousClose: number | null }) {
  const { t } = useT();
  if (previousClose === null) return null;
  const delta = Math.round(today) - Math.round(previousClose);
  const tone = delta > 0 ? "pos" : delta < 0 ? "neg" : "";
  const arrow = delta > 0 ? "▲" : delta < 0 ? "▼" : "▬";
  const sign = delta > 0 ? "+" : "";
  return (
    <span className={`fg-score-delta${tone ? ` ${tone}` : ""}`}>
      {t("misc.fearGreed.scoreDelta", { arrow, sign, delta })}
    </span>
  );
}

function PrevStat({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <span className="value">{value === null ? "—" : Math.round(value)}</span>
    </div>
  );
}

function scoreColumnNote(isComposite: boolean, t: Translator): string {
  return isComposite
    ? t("misc.fearGreed.table.scoreTitleComposite")
    : t("misc.fearGreed.table.scoreTitleCnn");
}

function ComponentRow({ component }: { component: FearGreedComponent }) {
  const { t } = useT();
  // CNN never publishes a per-component score, so fall back to the shared band boundaries -- the
  // same helper the backend uses, so a source switch can never move where a rating flips.
  const rating: Rating | null =
    component.rating ?? (component.score !== null ? ratingFor(component.score) : null);
  const description = componentDescription(component, t);
  return (
    <tr>
      <td>
        {componentName(component, t)}
        {/* What the raw number on this row actually is. The seven components are measured in
            different units -- an index level, a ratio, a spread -- and until this was carried
            through they rendered as seven bare decimals under a column headed "Raw", inviting
            exactly the comparison the model's own docstring says is invalid. */}
        {description && <div className="muted fg-component-desc">{description}</div>}
      </td>
      <td title={description ?? undefined}>{formatRaw(component, t)}</td>
      <td>{component.score === null ? "—" : Math.round(component.score)}</td>
      <td>{rating === null ? "—" : ratingLabel(rating, t)}</td>
      <td>{formatObservationDate(component.as_of)}</td>
    </tr>
  );
}
