/**
 * Macro page news panel: Polymarket event tiles plus a GDELT-fed global-headline strip.
 *
 * **Presentational only -- this component fetches nothing.** `data`/`phase`/`message` arrive as
 * props from `useMacroNews`, the same `Phase`-driven shape `NewsPanel.tsx` uses for the ticker side;
 * only one of loading/error/loaded ever renders.
 *
 * This is `NewsPanel.tsx`'s sibling and follows its display rules, with one twist forced by the
 * response shape. The ticker panel's `social` field is `SocialSummary | null`, so "provider
 * unreachable" and "provider answered with nothing" are two structurally distinct states the
 * component can just pattern-match on. `MacroNewsPanel` (the wire type, see `@/api/news`) has no
 * equivalent `events_source` field -- `events: []` is what both a dead Polymarket chain and a
 * healthy one with zero matches look like on the wire. The only place those two cases differ is the
 * warning text: `app.market.news.build_macro_panel` appends a warning containing
 * `"prediction markets unavailable"` only on the dead-provider path (see `_fold_provider_error` in
 * the backend module, and the docstring on `MacroNewsPanel` in `@/api/news`). `EventsSection` below
 * is therefore the one place in this codebase that tells those two states apart by matching warning
 * text rather than reading a dedicated field -- change that backend wording and this breaks silently,
 * so `MacroNewsPanel.test.tsx` pins the exact phrase.
 *
 * The headline strip does not have that problem: `news_source: string | null` on the wire is exactly
 * `TickerNewsPanel.news_source`'s semantics, so `NewsStrip` below reads that field directly, the same
 * way `NewsPanel.tsx`'s `SocialSection` reads `social === null`.
 *
 * **Every count on this panel carries its own denominator.** Both sections render the full `events`/
 * `news` arrays the backend returned (never a silently truncated top-N), labelled against
 * `MACRO_NEWS_LIMIT` -- the cap this app itself requested -- so "6 markets" always reads as "6 of up
 * to 20 requested" rather than a bare number a reader could mistake for "all of them" or "today's
 * total". That is the same discipline `NewsPanel.tsx`'s bull ratio enforces for labelled-message
 * counts, applied to a panel that has no ratio to protect but still has a count that could mislead.
 */
import {
  MACRO_NEWS_LIMIT,
  formatProbability,
  formatRelativeAge,
} from "@/api/news";
import type { EventMarket, MacroNewsPanel as MacroNewsPanelData, NewsItem, NewsWarning } from "@/api/news";
import { formatObservationDate } from "@/api/macro";
import { formatPrice } from "@/api/market";
import { useT } from "@/i18n";
import { safeHref } from "@/safeHref";

export type Phase = "loading" | "loaded" | "error";

export interface MacroNewsPanelProps {
  data: MacroNewsPanelData | null;
  phase: Phase;
  message: string | null;
}

export default function MacroNewsPanel({ data, phase, message }: MacroNewsPanelProps) {
  const { t } = useT();
  return (
    <section className="panel">
      <h2>{t("macro.news.title")}</h2>

      {phase === "loading" && <div className="placeholder">{t("macro.news.loading")}</div>}

      {phase === "error" && (
        <div className="placeholder">{message ?? t("macro.news.error")}</div>
      )}

      {phase === "loaded" && data && (
        <>
          <p className="tile-hint">
            {t("macro.news.generatedQuery", { age: formatRelativeAge(data.generated_at), query: data.query })}
          </p>

          {/* Polymarket tiles first, GDELT strip second -- the order Phase C's plan text names them
              in ("Polymarket event tiles and a GDELT global-news strip"). */}
          <EventsSection events={data.events} warnings={data.warnings} />
          <NewsStrip news={data.news} newsSource={data.news_source} />
          <WarningsList warnings={data.warnings} />
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Event markets (Polymarket)
// ---------------------------------------------------------------------------

/** The exact substring `build_macro_panel`'s `_fold_provider_error` puts in a warning's `message`
 * when the Polymarket chain itself failed -- `f"{what} unavailable for {subject}: {exc}"` with
 * `what="prediction markets"`. Matched case-insensitively since nothing about the comparison depends
 * on case; kept as one named constant rather than an inline literal so the two places that must agree
 * with the backend's wording (this match, and the test that pins it) both point at one string.
 * Not translated for the same reason: it is matched against the backend's own (always-English)
 * warning text, so translating it would break the match rather than the display. */
const EVENTS_PROVIDER_DOWN_MARKER = "prediction markets unavailable";

function EventsSection({ events, warnings }: { events: EventMarket[]; warnings: NewsWarning[] }) {
  const { t } = useT();
  const providerDown = warnings.some((w) =>
    w.message.toLowerCase().includes(EVENTS_PROVIDER_DOWN_MARKER),
  );

  if (providerDown) {
    return (
      <div className="stat tile">
        <span className="label">{t("macro.news.events.label")}</span>
        <span className="value">—</span>
        <p className="tile-hint">{t("macro.news.events.unreachable")}</p>
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="stat tile">
        <span className="label">{t("macro.news.events.label")}</span>
        <span className="value">—</span>
        <p className="tile-hint">{t("macro.news.events.empty")}</p>
      </div>
    );
  }

  return (
    <div>
      <p className="tile-hint">
        {t("macro.news.events.matched", { count: events.length, limit: MACRO_NEWS_LIMIT })}
      </p>
      <div className="tile-grid">
        {events.map((event) => (
          <div className="stat tile" key={event.slug}>
            <span className="value">{formatProbability(event.probability)}</span>
            <span className="label">{event.question}</span>
            <p className="tile-hint">
              {t("macro.news.events.tileHint", {
                source: event.source,
                asOf: formatRelativeAge(event.as_of),
                resolves: formatObservationDate(event.resolution_date),
                volume: formatPrice(event.volume),
              })}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Headlines (GDELT strip)
// ---------------------------------------------------------------------------

function NewsStrip({ news, newsSource }: { news: NewsItem[]; newsSource: string | null }) {
  const { t } = useT();
  if (newsSource === null) {
    return (
      <div className="stat tile">
        <span className="label">{t("macro.news.headlines.label")}</span>
        <span className="value">—</span>
        <p className="tile-hint">{t("macro.news.headlines.unreachable")}</p>
      </div>
    );
  }

  if (news.length === 0) {
    return (
      <div className="stat tile">
        <span className="label">{t("macro.news.headlines.labelWithSource", { source: newsSource })}</span>
        <span className="value">—</span>
        <p className="tile-hint">{t("macro.news.headlines.empty")}</p>
      </div>
    );
  }

  return (
    <div>
      <p className="tile-hint">
        {t("macro.news.headlines.matched", { count: news.length, limit: MACRO_NEWS_LIMIT, source: newsSource })}
      </p>
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
    </div>
  );
}

// ---------------------------------------------------------------------------
// Warnings -- same shape as `NewsPanel.tsx`'s, so any warning on this panel reads the same way one
// does everywhere else in the app.
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
