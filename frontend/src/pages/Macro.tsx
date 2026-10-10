/**
 * Macro panel: rates, oil, sentiment and the major ETFs/indices, in one scope.
 *
 * The six sections (Fear & Greed, Key Indicators, Rates, Oil, Movers, News) are a `FolderTabs` rail
 * rather than a sequential stack -- see `MACRO_TABS` below. The rail's left-to-right order preserves
 * the same reading-priority rationale the old vertical stack used: sentiment first -- "how does the
 * market feel" -- then the four numbers a reader checks daily (10-year yield, WTI, the Dollar Index,
 * Bitcoin), then the full per-series detail (including the 2s10s spread and every mover) for whoever
 * wants to dig further, with News last since it is, per `useMacroNews`'s docstring, the slowest fetch
 * on this page by an order of magnitude. Only the active tab's subtree is mounted, matching the
 * pattern `Tax.tsx` established for its own four-section rail.
 *
 * Rates and oil stay in the neutral, non-judgemental tone -- an "up" 10-year yield is not a P&L
 * gain -- and only the movers grid gets the conventional green-up/red-down treatment, since that is
 * the one section where the number really is a price. See `components/MacroTile.tsx` for how
 * `tone` is threaded through, and `components/MacroKeyIndicators.tsx` for why the key-indicators
 * card applies that same split (neutral for the 10-year, signed for WTI/DXY/BTC) rather than
 * treating all four uniformly.
 *
 * Loading / error / loaded are mutually exclusive by construction: they all read the same `phase`
 * from `useMacroSnapshot`, so exactly one branch below ever renders.
 */
import type { ReactNode } from "react";

import { formatPrice, type MarketWarning } from "@/api/market";
import type { MacroTile as MacroTileData, MacroUnit, MoverTile } from "@/api/macro";
import { formatValue } from "@/api/macro";
import FearGreedGauge from "@/components/FearGreedGauge";
import { FolderTabs } from "@/components/FolderTabs";
import MacroKeyIndicators from "@/components/MacroKeyIndicators";
import MacroNewsPanel from "@/components/MacroNewsPanel";
import MacroTile, { type TileTone } from "@/components/MacroTile";
import ProviderNote from "@/components/ProviderNote";
import { ScrollPanel } from "@/components/ScrollPanel";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import { useMacroNews } from "@/hooks/useMacroNews";
import { useMacroSnapshot } from "@/hooks/useMacroSnapshot";
import { useUrlState } from "@/hooks/useUrlState";
import { type Translator, useT } from "@/i18n";
import { resolveVocab } from "@/i18n/messages/serverVocab";

import "./Macro.css";

/**
 * The six sections this page scans in, as a `FolderTabs` rail rather than one long scroll -- see the
 * module docstring for the ordering rationale. Lives in the URL via `useUrlState` (not a plain
 * `useState`) so a reload on `/macro?tab=movers` opens directly on Movers, matching the same contract
 * `Tax.tsx`'s `TaxTab` rail already gives its own four sections.
 */
type MacroTab = "sentiment" | "indicators" | "rates" | "oil" | "movers" | "news";
const MACRO_TABS: readonly MacroTab[] = ["sentiment", "indicators", "rates", "oil", "movers", "news"];

export default function Macro() {
  const { snapshot, phase, message, refresh } = useMacroSnapshot();
  // Independent fetch from `useMacroSnapshot` above, on purpose -- see `useMacroNews`'s docstring.
  // GDELT and Polymarket are both keyless public upstreams (GDELT throttles hard), and the slowest
  // thing on this page must not hold Fear & Greed or any tile hostage to a headline feed nobody is
  // waiting on. Its own `phase` therefore drives only `MacroNewsPanel` below, not this component's
  // early loading/error returns.
  const macroNews = useMacroNews();
  const { t } = useT();
  // Which of the six sections is showing. See `MacroTab`'s docstring above for why this lives in the
  // URL rather than a plain `useState`. A hostile or stale `?tab=` falls back to `sentiment` via
  // `valid` rather than ever reaching a component that switches on it.
  const [tab, setTab] = useUrlState<MacroTab>("tab", "sentiment", { valid: MACRO_TABS });

  return (
    <>
      <h1>{t("macro.title")}</h1>
      <p className="subtitle">{t("macro.subtitle")}</p>

      <div className="panel macro-toolbar">
        <button
          type="button"
          className="symbol-submit"
          onClick={refresh}
          aria-label={t("macro.refreshAriaLabel")}
        >
          {t("common.refresh")}
        </button>
        {phase === "loaded" && snapshot && (
          <span className="macro-generated">{t("macro.generatedAt", { date: snapshot.generated_at })}</span>
        )}
      </div>

      {phase === "loading" && (
        <div className="panel">
          <div className="placeholder">{t("macro.loading")}</div>
        </div>
      )}

      {phase === "error" && (
        <div className="panel">
          <div className="placeholder">{message ?? t("macro.snapshotError")}</div>
        </div>
      )}

      {phase === "loaded" && snapshot && (
        <>
          {/* Above the tab rail, unconditionally on every tab -- a reader who lands on `?tab=news`
              from a bookmark must see a data-quality warning too, not only a reader on the default
              tab. Mirrors `Tax.tsx`'s own promoted-caveat-above-the-rail placement. */}
          <WarningsStrip warnings={snapshot.warnings} />

          <FolderTabs
            label={t("macro.tabs.label")}
            active={tab}
            // `FolderTabs` is generic over plain `string` ids; the cast is safe because every `id`
            // below is drawn from `MACRO_TABS`, the same union `useUrlState`'s `valid` list enforces.
            onChange={(id) => setTab(id as MacroTab)}
            items={[
              { id: "sentiment", label: t("macro.tabs.sentiment") },
              { id: "indicators", label: t("macro.tabs.indicators") },
              { id: "rates", label: t("macro.tabs.rates") },
              { id: "oil", label: t("macro.tabs.oil") },
              { id: "movers", label: t("macro.tabs.movers") },
              { id: "news", label: t("macro.tabs.news") },
            ]}
          />

          {/* Only the active tab's subtree is mounted -- the whole point of this refactor, matching
              `Tax.tsx`'s `tab === "..."` guards for its own rail. */}

          {tab === "sentiment" && (
            /* Fear & Greed is a short, fixed-size card -- bounded defensively (never expandable)
               rather than left to grow unbounded like the tile grids in the other tabs.
               `EmbeddedPanel` wraps a component that already renders its own `.panel` card (see
               Macro.css for why that seam is closed with a class, not a second copy of its markup). */
            <EmbeddedPanel label={t("misc.fearGreed.title")}>
              <FearGreedGauge data={snapshot.fear_greed} />
            </EmbeddedPanel>
          )}

          {tab === "indicators" && (
            <EmbeddedPanel label={t("misc.keyIndicators.title")}>
              <MacroKeyIndicators snapshot={snapshot} />
            </EmbeddedPanel>
          )}

          {tab === "rates" && (
            <Section title={t("macro.section.rates")} expandable>
              <LevelTileGrid tiles={snapshot.rates} tone="neutral" emptyText={t("macro.rates.emptyText")} />
            </Section>
          )}

          {tab === "oil" && (
            <Section title={t("macro.section.oil")} expandable>
              <LevelTileGrid tiles={snapshot.oil} tone="neutral" emptyText={t("macro.oil.emptyText")} />
            </Section>
          )}

          {tab === "movers" && (
            <Section title={t("macro.section.movers")} expandable>
              <MoverTileGrid movers={snapshot.movers} />
            </Section>
          )}

          {tab === "news" && (
            <EmbeddedPanel label={t("macro.news.title")} expandable>
              <MacroNewsPanel data={macroNews.data} phase={macroNews.phase} message={macroNews.message} />
            </EmbeddedPanel>
          )}

          {/* Rates/Oil/Movers are the three tabs whose tiles are actually prices from the one
              upstream this note names; Sentiment, Indicators and News are not, so the note only
              renders alongside the tabs it is actually true of rather than unconditionally on every
              tab regardless of content, which is what a single always-rendered placement would do. */}
          {(tab === "rates" || tab === "oil" || tab === "movers") && <ProviderNote />}
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

/**
 * A section that owns its own heading -- Rates, Oil, Movers. These are tile grids whose length
 * scales with how many series/movers the backend sends, so they are the "long ones" that get the
 * expand control; `ScrollPanel` bounds them to a scannable height by default.
 */
function Section({
  title,
  children,
  expandable = false,
}: {
  title: string;
  children: ReactNode;
  expandable?: boolean;
}) {
  return (
    <ScrollPanel title={<h2>{title}</h2>} label={title} expandable={expandable} size="md">
      {children}
    </ScrollPanel>
  );
}

/**
 * A section built around a component that already renders its own `.panel` card (`FearGreedGauge`,
 * `MacroKeyIndicators`, `MacroNewsPanel`) and is out of this page's scope to edit. Rather than
 * duplicating that component's heading in a second `title`, this wraps it bare -- `ScrollPanel`
 * bounds and (optionally) makes it expandable, and `Macro.css`'s `.macro-embed` rule strips the
 * outer panel's own border/background so the result reads as one card, not two nested ones.
 */
function EmbeddedPanel({
  label,
  children,
  expandable = false,
}: {
  label: string;
  children: ReactNode;
  expandable?: boolean;
}) {
  return (
    <ScrollPanel label={label} expandable={expandable} size="md" panelClassName="macro-embed">
      {children}
    </ScrollPanel>
  );
}

/**
 * Maps a Rates/Oil tile's stable `key` to the macro series id its optional expandable chart should
 * fetch (`MacroSeriesChart`'s `seriesId` prop, ultimately `/api/macro/series/{id}`). One lookup
 * object rather than scattering these four string literals across call sites -- get one wrong and
 * the tile's chart 404s silently until someone notices. Movers are deliberately absent: `MacroTile`
 * only renders a chart when `seriesId` is passed, and `MoverTileGrid` below never passes one, so
 * every mover tile keeps behaving exactly as it did before this lookup existed.
 */
const TILE_SERIES_ID: Record<string, string> = {
  us10y: "DGS10",
  "2s10s": "T10Y2Y",
  wti: "DCOILWTICO",
  brent: "DCOILBRENTEU",
};

/**
 * Rates and oil tiles.
 *
 * `tile.label` is server copy ("US 10-Year Treasury", "WTI Crude") keyed by the same stable `tile.key`
 * this grid already uses for React keys and for `TILE_SERIES_ID`, so it goes through the vocabulary
 * rather than straight onto the page -- under 한국어 those four labels were the only English left in
 * this tab. A key this build has not seen renders the server's own label, never a throw.
 */
function LevelTileGrid({
  tiles,
  tone,
  emptyText,
}: {
  tiles: MacroTileData[];
  tone: TileTone;
  emptyText: string;
}) {
  const { t } = useT();
  if (tiles.length === 0) {
    return <div className="placeholder">{emptyText}</div>;
  }
  return (
    <div className="tile-grid macro-tile-grid">
      {tiles.map((tile) => (
        <MacroTile
          key={tile.key}
          tileKey={tile.key}
          label={resolveVocab(t, `serverVocab.macroTile.${tile.key}.label`, tile.label)}
          valueText={formatValue(tile.value, tile.unit)}
          change={tile.change}
          spark={tile.spark}
          asOf={tile.as_of}
          source={tile.source}
          warnings={tile.warnings}
          tone={tone}
          seriesId={TILE_SERIES_ID[tile.key]}
          chartUnit={tile.unit}
        />
      ))}
    </div>
  );
}

/**
 * Picks the mover's headline formatter from `mover.unit`, not from `mover.currency`. `currency`
 * says what currency a price is quoted in and is only meaningful when the number *is* a currency
 * amount (`unit === "usd"`) -- every mover still carries a `currency` string on the wire (index
 * levels and spreads included) because the field exists for the movers that need it, not because
 * every mover is priced. Always reaching for `formatPrice` regardless of `unit` is exactly how the
 * Dollar Index rendered as `$98.90` and the VIX as `$15.13`: both are index levels with no currency
 * at all. Exported as a pure function so the unit-selection logic can be tested without a DOM (see
 * the project note: there is no existing test file for this page, so this is left for whoever adds
 * one).
 */
export function formatMoverValue(mover: Pick<MoverTile, "price" | "currency" | "unit">): string {
  // `unit` is a wire field landing from a concurrent backend change and is typed as required (not
  // `unit?: MacroUnit`) because every other call site should be able to rely on it. But a payload
  // fetched before that deploy lands is still valid JS at runtime -- the key is simply missing --
  // so this single point of use guards against `undefined` rather than trusting the type, and falls
  // back to the pre-existing `usd`/`formatPrice` behaviour so a stale payload degrades instead of
  // crashing or mis-rendering.
  const unit: MacroUnit = mover.unit ?? "usd";
  if (unit === "usd") return formatPrice(mover.price, mover.currency);
  return formatValue(mover.price, unit);
}

function MoverTileGrid({ movers }: { movers: MoverTile[] }) {
  const { t } = useT();
  if (movers.length === 0) {
    return <div className="placeholder">{t("macro.movers.emptyText")}</div>;
  }
  return (
    <div className="tile-grid macro-tile-grid">
      {movers.map((mover) => (
        <MacroTile
          key={mover.symbol}
          tileKey={mover.symbol}
          // The ticker is an identifier and stays; only the fund/index name beside it is vocabulary.
          label={`${mover.symbol} · ${resolveVocab(t, `serverVocab.mover.${mover.symbol}.label`, mover.label)}`}
          valueText={formatMoverValue(mover)}
          change={mover.change}
          spark={mover.spark}
          asOf={mover.as_of}
          source={mover.source}
          warnings={mover.warnings}
          tone="signed"
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Warnings -- top-level snapshot warnings only; per-tile and Fear & Greed warnings render inside
// their own components so a warning about one dead series doesn't get lost among unrelated ones.
// ---------------------------------------------------------------------------

/**
 * `MarketWarning.kind` is a stable wire token (`stale`, `provider_fallback`, `clamped`,
 * `short_history`, `partial_bar`, `gap`, ...), not UI copy -- rendering it bare used to put literal
 * snake_case on screen. This maps the known tokens to a tone + translated label for `StatusPill`;
 * an unrecognised future token still gets a readable (if generic) pill rather than falling back to
 * the raw string, so a new backend kind cannot regress this page to the old bug.
 */
function warningPillMeta(kind: string, t: Translator): { tone: PillTone; label: string } {
  switch (kind) {
    case "stale":
      // Reuses the shared `ui.pill.stale` label rather than a page-owned copy of the same word.
      return { tone: "warn", label: t("ui.pill.stale") };
    case "provider_fallback":
      return { tone: "warn", label: t("macro.warningKind.providerFallback") };
    case "clamped":
      return { tone: "info", label: t("macro.warningKind.clamped") };
    case "short_history":
      return { tone: "warn", label: t("macro.warningKind.shortHistory") };
    case "partial_bar":
      return { tone: "info", label: t("macro.warningKind.partialBar") };
    case "gap":
      return { tone: "warn", label: t("macro.warningKind.gap") };
    default:
      return { tone: "neutral", label: t("macro.warningKind.other") };
  }
}

function WarningsStrip({ warnings }: { warnings: MarketWarning[] }) {
  const { t } = useT();
  if (warnings.length === 0) return null;
  return (
    <div className="panel">
      <h2>{t("macro.warnings.title")}</h2>
      <div className="warnings-strip">
        {warnings.map((w, i) => {
          const meta = warningPillMeta(w.kind, t);
          return (
            <div className="warning-chip" key={`${w.kind}-${i}`}>
              <StatusPill tone={meta.tone} label={meta.label} />
              <span className="message">{w.message}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
