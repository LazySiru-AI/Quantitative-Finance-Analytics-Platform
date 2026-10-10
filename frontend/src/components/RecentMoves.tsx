/**
 * "What did this filer actually just do", in portfolio-weight terms.
 *
 * The number this panel exists to get right is `weight_delta`: a fraction of the filer's *whole*
 * reported book, not of the position itself. `+0.021` is "this grew by 2.1% of the portfolio", and
 * that is a different, much larger claim than "the position grew 2.1%" -- the module docstring in
 * `@/api/institutions` calls this out for `shares_pct_change`, and the same confusion is even easier
 * to fall into here, so every row spells out "of portfolio" rather than leaving a bare percent to be
 * misread as the smaller claim.
 *
 * Ranked by the *magnitude* of `weight_delta`, not `value_delta` -- a position's dollar value moves
 * on price as often as on trading (see the Chevron example in the same docstring), and `action` is
 * computed server-side from the share columns for exactly that reason. This panel never re-derives
 * it.
 */
import { compareDecimalStrings, type DecimalString } from "@/api/client";
import {
  formatSharesPctChange,
  formatSignedShares,
  type Action,
  type HoldingChange,
  type PortfolioDelta,
} from "@/api/institutions";
import { useT, type Language, type MessageKey } from "@/i18n";

import "./InstitutionsPanels.css";

export type RecentMovesPhase = "loading" | "loaded" | "empty" | "error";

export interface RecentMovesProps {
  delta: PortfolioDelta | null;
  phase: RecentMovesPhase;
  error?: string | null;
  /** How many moves to show. Default 6. */
  limit?: number;
  onSelectTicker?: (ticker: string) => void;
}

/** Sign-stripped magnitude of a decimal string, for ranking by `|weight_delta|`. String-level only
 *  -- never touches `Number`/`parseFloat`, so it stays safe to feed into `compareDecimalStrings`. */
function absDecimalString(value: DecimalString): DecimalString {
  return value.trim().replace(/^[+-]/, "") as DecimalString;
}

/**
 * `weight_delta` and `shares_pct_change` are both fractions of one with identical formatting needs
 * -- explicit `+`/`-`, the same under-threshold marker, the same exact-zero rendering -- so this
 * reuses `formatSharesPctChange` (`@/api/institutions`) rather than re-deriving that logic in a
 * second implementation. `weight_delta` is never `null` (unlike `shares_pct_change`, which is
 * `null` specifically for a brand-new position), so `formatSharesPctChange`'s `"new"` branch is
 * simply never reached from here.
 */
function formatWeightDelta(value: DecimalString): string {
  return formatSharesPctChange(value);
}

/** Human label + tone for an `Action`, derived from the server's own field -- never re-derived from
 *  `value_delta`, which moves on price as often as on a trade. Tone follows the action's framing,
 *  not the sign of `weight_delta` by itself: this is disclosure of what the filer did, not a
 *  P&L, so a `trim` is coloured as a change, not as a loss. */
const ACTION_LABEL_KEY: Record<Action, MessageKey> = {
  new: "desk.recentMoves.actionNew",
  exit: "desk.recentMoves.actionExit",
  add: "desk.recentMoves.actionAdd",
  trim: "desk.recentMoves.actionTrim",
  hold: "desk.recentMoves.actionHold",
};
const ACTION_TONE: Record<Action, "" | "inst-moves-up" | "inst-moves-down"> = {
  new: "inst-moves-up",
  add: "inst-moves-up",
  trim: "inst-moves-down",
  exit: "inst-moves-down",
  hold: "",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Formats a `"YYYY-MM-DD"` period string without ever constructing a `Date` from it.
 * `new Date("2026-06-30")` parses as UTC midnight, which prints as 2026-06-29 anywhere west of
 * Greenwich -- exactly the round-trip this function exists to avoid. `Number()` on the split
 * calendar components below is not the `DecimalString` precision concern the rest of this file cares
 * about: these are small integer month/day fields for display only, never compared or summed.
 *
 * Locale-aware (per the i18n contract's date rule) without going through `Date`/`toLocaleDateString`
 * at all -- Korean uses a numeric `YYYY년 M월 D일` order rather than an abbreviated month name, so
 * `lang` picks the format directly instead of handing this to `Intl`.
 */
function formatPeriodDate(iso: string, lang: Language): string {
  const [y, m, d] = iso.split("-");
  const monthIdx = Number(m) - 1;
  const day = d ? String(Number(d)) : "";
  if (lang === "ko") return `${y ?? ""}년 ${m ?? ""}월 ${day}일`;
  const month = MONTHS[monthIdx] ?? m ?? "";
  return `${month} ${day}, ${y ?? ""}`.trim();
}

export default function RecentMoves({ delta, phase, error, limit = 6, onSelectTicker }: RecentMovesProps) {
  const { t } = useT();
  return (
    <section className="panel inst-moves-panel">
      <h2 className="inst-moves-title">{t("desk.recentMoves.title")}</h2>

      {phase === "loading" && <div className="placeholder">{t("desk.recentMoves.loading")}</div>}

      {phase === "error" && (
        <div className="callout callout-warn">{error ?? t("desk.recentMoves.errorFallback")}</div>
      )}

      {phase === "empty" && <div className="placeholder">{t("desk.recentMoves.emptyState")}</div>}

      {phase === "loaded" && delta && <MovesList delta={delta} limit={limit} onSelectTicker={onSelectTicker} />}

      {phase === "loaded" && !delta && (
        <div className="placeholder">{t("desk.recentMoves.noComparisonData")}</div>
      )}
    </section>
  );
}

function MovesList({
  delta,
  limit,
  onSelectTicker,
}: {
  delta: PortfolioDelta;
  limit: number;
  onSelectTicker?: ((ticker: string) => void) | undefined;
}) {
  const { t, lang } = useT();
  const ranked = [...delta.changes]
    .sort((a, b) => compareDecimalStrings(absDecimalString(b.weight_delta), absDecimalString(a.weight_delta)))
    .slice(0, limit);

  return (
    <>
      <p className="muted inst-moves-period">
        {t("desk.recentMoves.periodLabel", {
          from: formatPeriodDate(delta.from_period, lang),
          to: formatPeriodDate(delta.to_period, lang),
        })}
      </p>

      {ranked.length === 0 ? (
        <div className="placeholder">{t("desk.recentMoves.noChanges")}</div>
      ) : (
        <ul className="inst-moves-list">
          {ranked.map((change) => (
            <MoveRow key={change.cusip} change={change} onSelectTicker={onSelectTicker} />
          ))}
        </ul>
      )}
    </>
  );
}

function MoveRow({
  change,
  onSelectTicker,
}: {
  change: HoldingChange;
  onSelectTicker?: ((ticker: string) => void) | undefined;
}) {
  const { t } = useT();
  const weightText = formatWeightDelta(change.weight_delta);
  const sharesText = formatSignedShares(change.shares_delta);
  const sharesPctText = formatSharesPctChange(change.shares_pct_change);
  const tone = ACTION_TONE[change.action];
  const actionLabel = t(ACTION_LABEL_KEY[change.action]);

  const body = (
    <>
      <span className="inst-moves-issuer">{change.issuer}</span>
      {change.ticker && <span className="badge inst-moves-ticker">{change.ticker}</span>}
      <span className={`badge inst-moves-action ${tone}`.trim()}>{actionLabel}</span>
      <span className={`inst-moves-weight-delta ${tone}`.trim()}>
        {weightText} <span className="inst-moves-of-portfolio">{t("desk.recentMoves.ofPortfolio")}</span>
      </span>
      <span className="muted inst-moves-shares-context">
        {t("desk.recentMoves.sharesContext", { shares: sharesText, pct: sharesPctText })}
      </span>
    </>
  );

  return (
    <li className="inst-moves-row">
      {change.ticker ? (
        <button
          type="button"
          className="inst-moves-row-btn"
          onClick={() => onSelectTicker?.(change.ticker as string)}
          aria-label={t("desk.recentMoves.rowAriaLabel", {
            issuer: change.issuer,
            ticker: change.ticker,
            action: actionLabel,
            weight: weightText,
          })}
        >
          {body}
        </button>
      ) : (
        <div className="inst-moves-row-static">{body}</div>
      )}
    </li>
  );
}
