/**
 * Bits genuinely shared by `Institutions.tsx` and `Consensus.tsx`, now the two tabs of `Filers.tsx`.
 *
 * Before this file existed, both pages carried an identical `IssuerCell` and an identical five-way
 * action-label map, copy-pasted rather than shared -- see the merged-page task's finding E1. This
 * module is the one place both now import them from. Nothing outside `Filers.tsx`,
 * `Institutions.tsx` and `Consensus.tsx` imports it, and it owns nothing else: page-specific sort
 * state, filter state, table markup and action-badge TONE (colour) stay in each page's own file --
 * only the label vocabulary and the issuer cell were byte-identical between the two; the rest was
 * never actually duplicated, just similarly shaped.
 *
 * `Action` is imported from `@/api/institutions` rather than re-declared here -- `@/api/consensus`
 * already re-exports the exact same type (`export type { Action, ... }` in `api/consensus.ts`), so
 * there was never a second vocabulary to reconcile, only a second copy of the map naming it.
 */
import { Link } from "react-router-dom";

import type { Action } from "@/api/institutions";
import { useT, type MessageKey } from "@/i18n";

/**
 * One map, not two. Institutions' and Consensus' own copies of this map (`market.institutions.action.*`
 * vs `market.consensus.action.*`) were already byte-identical in both English and Korean -- the
 * catalog carried two translated copies of the same five words under two different prefixes.
 * Pointing both pages at the `institutions` keys removes the duplicate map without adding, or
 * retiring, any catalog string (`i18n/catalog.ts` is out of this task's scope fence).
 */
export const ACTION_LABEL_KEY: Record<Action, MessageKey> = {
  new: "market.institutions.action.new",
  exit: "market.institutions.action.exit",
  add: "market.institutions.action.add",
  trim: "market.institutions.action.trim",
  hold: "market.institutions.action.hold",
};

export interface IssuerCellProps {
  issuer: string;
  ticker: string | null;
}

/**
 * Issuer name is the primary identity on both tabs -- neither a 13F nor an NPORT filing carries a
 * ticker, so most rows have none. The ticker, when present, is a secondary badge meaning "this CUSIP
 * matched something in your own ledger," rendered as a real `Link` (not a `<span>` + `onClick`) so
 * middle-click / ctrl-click / "open in new tab" keep working for free. Never synthesised from
 * `issuer`; a `null` ticker renders the issuer alone.
 *
 * Reuses `market.institutions.issuerCell.*` on both tabs rather than also keeping
 * `market.consensus.issuerCell.*` alive as a second, separately-maintained copy of the same idea --
 * the two shards' English and Korean text already said the same thing (a CUSIP match against your
 * own ledger); only Consensus's badge additionally dropped the "you own this" qualifier the
 * Institutions copy carried, which this extraction now shows on both. Classnames
 * (`inst-issuer-cell`/`inst-issuer-name`/`inst-owned-badge`) are the pre-existing GLOBAL rules in
 * `styles.css` (see that file's own comment on why they live there, not in `Institutions.css`), so
 * this component needs no CSS of its own and renders correctly wherever it is mounted.
 */
export function IssuerCell({ issuer, ticker }: IssuerCellProps) {
  const { t } = useT();
  return (
    <span className="inst-issuer-cell">
      <span className="inst-issuer-name">{issuer}</span>
      {ticker != null && (
        <Link
          to={`/symbol/${encodeURIComponent(ticker)}`}
          className="badge inst-owned-badge"
          title={t("market.institutions.issuerCell.title")}
          aria-label={t("market.institutions.issuerCell.ariaLabel", { ticker })}
        >
          {t("market.institutions.issuerCell.badge", { ticker })}
        </Link>
      )}
    </span>
  );
}
