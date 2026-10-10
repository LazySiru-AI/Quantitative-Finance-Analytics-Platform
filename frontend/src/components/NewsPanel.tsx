/**
 * News & Sentiment panel for a ticker: recent headlines plus a social-sentiment snapshot.
 *
 * **Presentational only — this component fetches nothing.** `data`/`phase`/`message` arrive as
 * props from whatever hook the caller wires up (see `useMacroSnapshot` for the house shape this
 * mirrors: a `Phase` union drives which of loading/error/loaded renders, and only one of the three
 * ever does).
 *
 * This file exists to enforce three display rules, all traceable to a real StockTwits window where
 * 8 of 12 messages carried no directional label at all:
 *
 * 1. **A bull ratio never renders without its labelled-count denominator beside it** — see
 *    `SocialSection` below. "50% bullish" over 4 of 12 messages is true and misleading alone.
 * 2. **`null` renders as an em dash, never `0%` or an empty bar.** `social: null` (provider
 *    unreachable) and a reachable-but-empty snapshot (nobody posted) are different claims and get
 *    different sentences — `macro.tickerNews.social.unreachable` vs `macro.tickerNews.social.emptyWindow`
 *    in the catalog, both rendered by `SocialSection` below.
 * 3. **Non-empty `warnings` are always rendered**, not swallowed — `WarningsList` below, matching
 *    `MacroTile`'s warnings rendering.
 *
 * See `@/api/news` for the full reasoning behind the three-way split between "unreachable", "empty
 * window", and "non-empty window, nothing labelled" — this component's `SocialSection` is the render
 * side of that split, not a restatement of it.
 */
import {
  formatBullRatio,
  formatRelativeAge,
  snapshotLabelled,
  snapshotTotal,
} from "@/api/news";
import type { NewsItem, NewsWarning, SocialSummary, TickerNewsPanel } from "@/api/news";
import { useT } from "@/i18n";
import { safeHref } from "@/safeHref";

export type Phase = "loading" | "loaded" | "error";

export interface NewsPanelProps {
  data: TickerNewsPanel | null;
  phase: Phase;
  message: string | null;
}

export default function NewsPanel({ data, phase, message }: NewsPanelProps) {
  const { t } = useT();
  return (
    <section className="panel">
      <h2>{t("macro.tickerNews.title")}</h2>

      {phase === "loading" && <div className="placeholder">{t("macro.tickerNews.loading")}</div>}

      {phase === "error" && (
        <div className="placeholder">{message ?? t("macro.tickerNews.error")}</div>
      )}

      {phase === "loaded" && data && (
        <>
          <SocialSection social={data.social} />
          <Headlines symbol={data.symbol} news={data.news} />
          <WarningsList warnings={data.warnings} />
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Social sentiment
// ---------------------------------------------------------------------------

function SocialSection({ social }: { social: SocialSummary | null }) {
  const { t } = useT();
  if (social === null) {
    return (
      <div className="stat">
        <span className="label">{t("macro.tickerNews.social.label")}</span>
        <span className="value">—</span>
        <p className="tile-hint">{t("macro.tickerNews.social.unreachable")}</p>
      </div>
    );
  }

  const total = snapshotTotal(social.snapshot);
  const labelled = snapshotLabelled(social.snapshot);

  if (total === 0) {
    return (
      <div className="stat">
        <span className="label">
          {t("macro.tickerNews.social.labelWithSource", { source: social.snapshot.source })}
        </span>
        <span className="value">—</span>
        <p className="tile-hint">{t("macro.tickerNews.social.emptyWindow")}</p>
      </div>
    );
  }

  // `bull_ratio` can still be `null` here on a *non-empty* window (every message was neutral). The
  // ratio and its denominator always render on the same line so a reader can never see one without
  // the other -- this is the one place in the app where "50% bullish" alone would be misleading.
  return (
    <div className="stat">
      <span className="label">
        {t("macro.tickerNews.social.labelWithSource", { source: social.snapshot.source })}
      </span>
      <span className="value">
        {t("macro.tickerNews.social.ratioLine", {
          ratio: formatBullRatio(social.bull_ratio),
          labelled,
          total,
        })}
      </span>
      <p className="tile-hint">{t("macro.asOf", { date: formatRelativeAge(social.snapshot.as_of) })}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Headlines
// ---------------------------------------------------------------------------

function Headlines({ symbol, news }: { symbol: string; news: NewsItem[] }) {
  const { t } = useT();
  if (news.length === 0) {
    return <div className="placeholder">{t("macro.tickerNews.headlines.empty", { symbol })}</div>;
  }
  return (
    <ul>
      {news.map((item, i) => {
        const href = safeHref(item.url);
        return (
          <li key={`${item.url}-${i}`}>
            {href === null ? (
              <span>{item.title}</span>
            ) : (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {item.title}
              </a>
            )}
            <div className="muted tile-hint">
              {item.publisher} · {formatRelativeAge(item.published)}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Warnings -- same shape as `MacroTile`'s warnings rendering, so a `provider_fallback` (or any
// other) warning on this panel reads the same way one does everywhere else in the app.
// ---------------------------------------------------------------------------

function WarningsList({ warnings }: { warnings: NewsWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <ul className="warning-list">
      {warnings.map((w, i) => (
        <li key={`${w.kind}-${i}`}>
          <span className="kind">{w.kind}</span> {w.message}
        </li>
      ))}
    </ul>
  );
}
