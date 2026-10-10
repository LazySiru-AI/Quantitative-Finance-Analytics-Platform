/**
 * Portfolio Planner -- the in-app home of what began as `portfolio-designer.html`.
 *
 * A per-account planning canvas: one column per open account, into which the owner drags tickers
 * (from their holdings or from a whole-universe search) to plan what to buy where. Every card is
 * decorated with the ticker's live wash-sale status -- can I buy it back yet, and is a deferred loss
 * embedded in what I already hold -- read fresh on each visit, never stored.
 *
 * **What persists vs. what is live.** The board (which tickers sit in which column, plus one note
 * per account) is saved server-side through `/api/designer/board` and survives a restart. Everything
 * a card *shows about* a ticker -- wash window, held quantity, unrealized, deferred loss, sector --
 * is derived on the fly from `/api/portfolio` and `/api/tax/wash-sales`, because those answers move
 * with the calendar and the ledger and must not be frozen into a saved file. The board therefore
 * stores intent only.
 *
 * **Empty by default; fills only from the owner's actions.** A never-saved board is one empty column
 * per open account. "Pull current holdings" is the button that reads the live portfolio and writes
 * each account's holdings into its column; nothing seeds holdings automatically. After any edit the
 * board autosaves (debounced), so "whatever the owner adds" is what comes back next session.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiRequestError } from "@/api/client";
import {
  type DesignerBoard,
  type DesignerColumn,
  type UniverseSymbol,
  designerApi,
} from "@/api/designer";
import { type PortfolioReport, portfolioApi } from "@/api/portfolio";
import { type WashSaleTracker, washSalesApi } from "@/api/washsales";
import { localeTag, useT, type Translator } from "@/i18n";

import "./Designer.css";

/** Per-symbol live holding facts the board decorates a card with (never persisted). */
interface HeldInfo {
  sector: string;
  unrealized: number | null;
  marketValue: number | null;
  /** Wash-sale-disallowed loss embedded in the *remaining* shares' basis (`wash_sale_adjustment`). */
  embeddedDeferred: number;
  /** account_id -> quantity held there, as a display string. */
  acctQty: Record<string, string>;
}

/** Per-symbol live wash-sale facts (never persisted). */
interface WashInfo {
  open: boolean;
  days: number;
  safeOn: string;
  deferred: number;
  lastSale: string | null;
}

type SaveStatus = "idle" | "saving" | "saved" | "error";

type WashClass = "ok" | "bad" | "warn";

interface WashView {
  cls: WashClass;
  label: string;
  badge: string;
  sub: string;
  tip: string;
}

const SAVE_DEBOUNCE_MS = 500;

function num(v: string | null | undefined): number | null {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function money(v: number | null, locale: string): string {
  if (v == null) return "";
  return "$" + v.toLocaleString(locale, { maximumFractionDigits: 0 });
}

function moneyc(v: number, locale: string): string {
  return "$" + Math.abs(v).toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Unrealized with an explicit sign, e.g. `+$139.40` / `−$37.50` (U+2212 minus, not a hyphen). */
function signed(v: number, locale: string): string {
  return (v < 0 ? "−" : "+") + moneyc(v, locale);
}

export default function Designer() {
  const { t, lang } = useT();
  const locale = localeTag(lang);

  const [board, setBoard] = useState<DesignerBoard | null>(null);
  const [universe, setUniverse] = useState<UniverseSymbol[]>([]);
  const [report, setReport] = useState<PortfolioReport | null>(null);
  const [tracker, setTracker] = useState<WashSaleTracker | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");

  const [search, setSearch] = useState("");
  const [scope, setScope] = useState<"held" | "all">("held");
  const [hotCol, setHotCol] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const dragCtx = useRef<{ from: "palette" | "card"; sym: string; col?: number; idx?: number } | null>(
    null,
  );
  const saveTimer = useRef<number | undefined>(undefined);
  const toastTimer = useRef<number | undefined>(undefined);

  // --- load ----------------------------------------------------------------
  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      try {
        // Board + universe are essential. Portfolio + wash-sales decorate the cards; if either
        // fails (it should not -- same owner scope) the board still renders, just without badges.
        const [b, u] = await Promise.all([
          designerApi.board(ac.signal),
          designerApi.universe(ac.signal),
        ]);
        setBoard(b);
        setUniverse(u);
        const [rep, trk] = await Promise.allSettled([
          portfolioApi.report(ac.signal),
          washSalesApi.tracker(ac.signal),
        ]);
        if (rep.status === "fulfilled") setReport(rep.value);
        if (trk.status === "fulfilled") setTracker(trk.value);
        setError(null);
      } catch (e) {
        if (ac.signal.aborted) return;
        if (e instanceof ApiRequestError) {
          setError(t("designer.apiError", { status: e.status, message: e.message }));
        } else {
          setError(t("designer.cannotReachApi"));
        }
      } finally {
        if (!ac.signal.aborted) setLoading(false);
      }
    })();
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- enrichment maps -----------------------------------------------------
  const universeMap = useMemo(() => {
    const m: Record<string, UniverseSymbol> = {};
    for (const u of universe) m[u.symbol] = u;
    return m;
  }, [universe]);

  const heldMap = useMemo(() => {
    const m: Record<string, HeldInfo> = {};
    if (!report) return m;
    for (const pos of report.positions) {
      const acctQty: Record<string, string> = {};
      for (const a of pos.accounts) acctQty[a.account_id] = a.quantity;
      m[pos.symbol] = {
        sector: pos.sector,
        unrealized: num(pos.unrealized),
        marketValue: num(pos.market_value),
        embeddedDeferred: num(pos.wash_sale_adjustment) ?? 0,
        acctQty,
      };
    }
    return m;
  }, [report]);

  const heldByAccount = useMemo(() => {
    const m: Record<string, string[]> = {};
    if (!report) return m;
    for (const pos of report.positions) {
      for (const a of pos.accounts) (m[a.account_id] ??= []).push(pos.symbol);
    }
    return m;
  }, [report]);

  const washMap = useMemo(() => {
    const m: Record<string, WashInfo> = {};
    if (!tracker) return m;
    for (const s of tracker.symbols) {
      m[s.symbol] = {
        open: s.window_is_open,
        days: s.days_until_safe,
        safeOn: s.repurchase_safe_on,
        deferred: num(s.deferred_disallowed) ?? 0,
        lastSale: s.last_sale_date,
      };
    }
    return m;
  }, [tracker]);

  const heldSymbols = useMemo(() => new Set(Object.keys(heldMap)), [heldMap]);

  const sectorOf = useCallback(
    (sym: string): string => universeMap[sym]?.sector ?? heldMap[sym]?.sector ?? "Unclassified",
    [universeMap, heldMap],
  );

  const fmtDate = useCallback(
    (iso: string): string =>
      new Date(iso + "T00:00:00").toLocaleDateString(locale, { month: "short", day: "numeric" }),
    [locale],
  );

  // --- wash classification -------------------------------------------------
  const washView = useCallback(
    (sym: string, acctType: string | null): WashView => {
      const w = washMap[sym];
      if (!w) {
        return {
          cls: "ok",
          label: t("designer.wash.ok"),
          badge: "✓",
          sub: t("designer.wash.noWindow"),
          tip: t("designer.wash.tip.none.detail"),
        };
      }
      const retirement = acctType === "retirement";
      if (w.open) {
        let tip = t("designer.wash.tip.open.detail", { date: w.safeOn });
        if (w.deferred > 0) tip += " " + t("designer.wash.tip.allTime.detail", { amount: money(w.deferred, locale) });
        return {
          cls: "bad",
          label: t("designer.wash.wait", { days: w.days }),
          badge: "⛔ " + t("designer.wash.wait", { days: w.days }),
          sub: t("designer.wash.safeOn", { date: fmtDate(w.safeOn) }),
          tip,
        };
      }
      if (retirement) {
        return {
          cls: "warn",
          label: t("designer.wash.iraOk"),
          badge: "▲ " + t("designer.wash.iraBadge"),
          sub: t("designer.wash.cleared", { date: fmtDate(w.safeOn) }),
          tip: t("designer.wash.tip.ira.detail"),
        };
      }
      let tip = t("designer.wash.tip.cleared.detail", { date: w.safeOn });
      if (w.deferred > 0) tip += " " + t("designer.wash.tip.allTime.detail", { amount: money(w.deferred, locale) });
      return { cls: "ok", label: t("designer.wash.ok"), badge: "✓", sub: t("designer.wash.cleared", { date: fmtDate(w.safeOn) }), tip };
    },
    [washMap, t, locale, fmtDate],
  );

  // --- persistence ---------------------------------------------------------
  const scheduleSave = useCallback((next: DesignerBoard) => {
    setSaveStatus("saving");
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(async () => {
      try {
        const saved = await designerApi.saveBoard(next);
        // Only adopt the server's `updated_at`, never its columns -- the user may have edited again
        // during the round trip, and replacing columns would clobber those in-flight edits.
        setBoard((b) => (b ? { ...b, updated_at: saved.updated_at } : b));
        setSaveStatus("saved");
      } catch {
        setSaveStatus("error");
      }
    }, SAVE_DEBOUNCE_MS);
  }, []);

  const mutate = useCallback(
    (columns: DesignerColumn[]) => {
      setBoard((b) => {
        if (!b) return b;
        const next = { ...b, columns };
        scheduleSave(next);
        return next;
      });
    },
    [scheduleSave],
  );

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 1800);
  }, []);

  useEffect(
    () => () => {
      window.clearTimeout(saveTimer.current);
      window.clearTimeout(toastTimer.current);
    },
    [],
  );

  // --- board mutations -----------------------------------------------------
  const addTicker = useCallback(
    (colIdx: number, sym: string, atIdx?: number) => {
      if (!board) return;
      const symbol = sym.toUpperCase();
      const col = board.columns[colIdx];
      if (!col) return;
      if (col.tickers.some((tk) => tk.symbol === symbol)) {
        showToast(t("designer.toast.duplicate", { symbol, account: col.label }));
        return;
      }
      const tickers = col.tickers.slice();
      tickers.splice(atIdx ?? tickers.length, 0, { symbol });
      const columns = board.columns.map((c, i) => (i === colIdx ? { ...c, tickers } : c));
      mutate(columns);
    },
    [board, mutate, showToast, t],
  );

  const removeTicker = useCallback(
    (colIdx: number, idx: number) => {
      if (!board) return;
      const col = board.columns[colIdx];
      if (!col) return;
      const tickers = col.tickers.filter((_, i) => i !== idx);
      mutate(board.columns.map((c, i) => (i === colIdx ? { ...c, tickers } : c)));
    },
    [board, mutate],
  );

  const moveTicker = useCallback(
    (fromCol: number, fromIdx: number, toCol: number, toIdx: number) => {
      if (!board) return;
      const src = board.columns[fromCol];
      const dst = board.columns[toCol];
      if (!src || !dst) return;
      const moved = src.tickers[fromIdx];
      if (!moved) return;
      if (fromCol !== toCol && dst.tickers.some((tk) => tk.symbol === moved.symbol)) {
        showToast(t("designer.toast.duplicate", { symbol: moved.symbol, account: dst.label }));
        return;
      }
      const columns = board.columns.map((c) => ({ ...c, tickers: c.tickers.slice() }));
      const srcCol = columns[fromCol]!;
      srcCol.tickers.splice(fromIdx, 1);
      let insertAt = toIdx;
      if (fromCol === toCol && fromIdx < toIdx) insertAt -= 1;
      columns[toCol]!.tickers.splice(insertAt, 0, moved);
      mutate(columns);
    },
    [board, mutate, showToast, t],
  );

  const setNote = useCallback(
    (colIdx: number, note: string) => {
      if (!board) return;
      mutate(board.columns.map((c, i) => (i === colIdx ? { ...c, note } : c)));
    },
    [board, mutate],
  );

  const pullHoldings = useCallback(() => {
    if (!board) return;
    let added = 0;
    const columns = board.columns.map((col) => {
      const have = new Set(col.tickers.map((tk) => tk.symbol));
      const symbols = (heldByAccount[col.account_id] ?? [])
        .slice()
        .sort((a, b) => (heldMap[b]?.marketValue ?? 0) - (heldMap[a]?.marketValue ?? 0));
      const additions = symbols.filter((s) => !have.has(s));
      added += additions.length;
      return additions.length
        ? { ...col, tickers: [...col.tickers, ...additions.map((symbol) => ({ symbol }))] }
        : col;
    });
    if (added === 0) {
      showToast(t("designer.pull.none"));
      return;
    }
    mutate(columns);
    showToast(t(added === 1 ? "designer.pull.added_one" : "designer.pull.added_other", { n: added }));
  }, [board, heldByAccount, heldMap, mutate, showToast, t]);

  const emptyBoard = useCallback(() => {
    if (!board) return;
    if (!window.confirm(t("designer.clear.confirm"))) return;
    mutate(board.columns.map((c) => ({ ...c, tickers: [] })));
  }, [board, mutate, t]);

  // --- drag & drop ---------------------------------------------------------
  const onDrop = useCallback(
    (toCol: number, toIdx: number) => {
      const ctx = dragCtx.current;
      setHotCol(null);
      if (!ctx) return;
      if (ctx.from === "card" && ctx.col != null && ctx.idx != null) {
        moveTicker(ctx.col, ctx.idx, toCol, toIdx);
      } else {
        addTicker(toCol, ctx.sym, toIdx);
      }
      dragCtx.current = null;
    },
    [addTicker, moveTicker],
  );

  // --- palette list --------------------------------------------------------
  const paletteItems = useMemo(() => {
    const q = search.trim().toUpperCase();
    if (q) {
      const items = universe
        .filter((u) => u.symbol.includes(q) || u.sector.toUpperCase().includes(q))
        .sort(
          (a, b) =>
            Number(b.symbol === q) - Number(a.symbol === q) ||
            Number(heldSymbols.has(b.symbol)) - Number(heldSymbols.has(a.symbol)) ||
            a.symbol.localeCompare(b.symbol),
        )
        .slice(0, 120);
      return items.map((u) => u.symbol);
    }
    if (scope === "held") {
      return [...heldSymbols].sort((a, b) => a.localeCompare(b));
    }
    return universe
      .slice()
      .sort(
        (a, b) =>
          Number(heldSymbols.has(b.symbol)) - Number(heldSymbols.has(a.symbol)) ||
          a.symbol.localeCompare(b.symbol),
      )
      .slice(0, 300)
      .map((u) => u.symbol);
  }, [search, scope, universe, heldSymbols]);

  if (loading) {
    return (
      <div className="designer">
        <p className="dz-loading">{t("designer.loading")}</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="designer">
        <p className="dz-error" role="alert">
          {error}
        </p>
      </div>
    );
  }
  if (!board) return <div className="designer" />;

  const q = search.trim().toUpperCase();
  const placed = board.columns.reduce((n, c) => n + c.tickers.length, 0);

  return (
    <div className="designer">
      <header className="dz-top">
        <div className="dz-titles">
          <h1>{t("designer.title")}</h1>
          <p className="dz-subtitle">{t("designer.subtitle")}</p>
        </div>
        <div className="dz-actions">
          <SaveIndicator status={saveStatus} updatedAt={board.updated_at} t={t} locale={locale} />
          <button className="dz-btn" onClick={pullHoldings} title={t("designer.pull.title")}>
            {t("designer.pull")}
          </button>
          <button className="dz-btn" onClick={emptyBoard}>
            {t("designer.clear")}
          </button>
        </div>
      </header>

      <div className="dz-legend" aria-hidden="true">
        <span className="dz-lg"><span className="dz-dot ok" />{t("designer.legend.ok")}</span>
        <span className="dz-lg"><span className="dz-dot bad" />{t("designer.legend.washOpen")}</span>
        <span className="dz-lg"><span className="dz-dot warn" />{t("designer.legend.ira")}</span>
        <span className="dz-lg">🔒 {t("designer.legend.deferred")}</span>
      </div>

      {board.columns.length === 0 ? (
        <div className="dz-empty">
          <h2>{t("designer.empty.title")}</h2>
          <p>{t("designer.empty.body")}</p>
        </div>
      ) : (
        <div className="dz-main">
          <aside className="dz-palette">
            <div className="dz-search">
              <input
                type="text"
                value={search}
                placeholder={t("designer.search.placeholder")}
                spellCheck={false}
                autoComplete="off"
                onChange={(e) => setSearch(e.target.value)}
                aria-label={t("designer.search.placeholder")}
              />
              {search && (
                <button className="dz-search-x" onClick={() => setSearch("")} aria-label={t("designer.search.clear")}>
                  ×
                </button>
              )}
            </div>
            <div className="dz-pal-meta">
              <span className="dz-pal-lbl">
                {q ? t("designer.palette.results") : scope === "held" ? t("designer.palette.held") : t("designer.palette.all")}
              </span>
              {!q && (
                <div className="dz-seg">
                  <button className={scope === "held" ? "on" : ""} onClick={() => setScope("held")}>
                    {t("designer.palette.held")}
                  </button>
                  <button className={scope === "all" ? "on" : ""} onClick={() => setScope("all")}>
                    {t("designer.palette.all")}
                  </button>
                </div>
              )}
            </div>
            <div className="dz-pal-list">
              {paletteItems.length === 0 && q && (
                <div className="dz-pal-empty">
                  <p>{t("designer.palette.noMatch", { q })}</p>
                  <button className="dz-btn" onClick={() => board.columns[0] && addTicker(0, q)}>
                    {t("designer.palette.useAnyway", { q })}
                  </button>
                </div>
              )}
              {paletteItems.length === 0 && !q && scope === "held" && (
                <p className="dz-pal-empty">{t("designer.palette.empty")}</p>
              )}
              {paletteItems.map((sym) => {
                const w = washView(sym, null);
                const held = heldSymbols.has(sym);
                const hasDef = (heldMap[sym]?.embeddedDeferred ?? 0) > 0;
                return (
                  <div
                    key={sym}
                    className="dz-chip"
                    draggable
                    onDragStart={(e) => {
                      dragCtx.current = { from: "palette", sym };
                      e.dataTransfer.effectAllowed = "copy";
                      e.dataTransfer.setData("text/plain", sym);
                    }}
                    onDragEnd={() => {
                      dragCtx.current = null;
                      setHotCol(null);
                    }}
                    onDoubleClick={() => board.columns[0] && addTicker(0, sym)}
                    title={sym}
                  >
                    <span className="dz-chip-id">
                      <span className="dz-sym">{sym}</span>
                      <span className="dz-sec">{sectorOf(sym)}</span>
                    </span>
                    {held && <span className="dz-held-tag">{t("designer.palette.heldTag")}</span>}
                    {hasDef && <span className="dz-lock" title={t("designer.lock.title")}>🔒</span>}
                    <span className={`dz-mini ${w.cls}`}>{w.cls === "bad" ? w.badge : "✓"}</span>
                  </div>
                );
              })}
            </div>
          </aside>

          <div className="dz-board">
            {board.columns.map((col, ci) => (
              <section
                key={col.account_id}
                className={`dz-col${hotCol === ci ? " hot" : ""}`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setHotCol(ci);
                }}
                onDragLeave={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node)) setHotCol((h) => (h === ci ? null : h));
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  onDrop(ci, col.tickers.length);
                }}
              >
                <div className="dz-col-head">
                  <div className="dz-col-title">
                    <span className="dz-col-name">{col.label || col.account_id}</span>
                    <span className="dz-col-meta">
                      {col.tax_treatment && (
                        <span className={`dz-tax tax-${col.tax_treatment}`}>{col.tax_treatment.replace("_", " ")}</span>
                      )}{" "}
                      <span className="dz-col-count">
                        {t(col.tickers.length === 1 ? "designer.column.count_one" : "designer.column.count_other", {
                          n: col.tickers.length,
                        })}
                      </span>
                    </span>
                  </div>
                </div>
                <textarea
                  className="dz-note"
                  rows={2}
                  value={col.note}
                  placeholder={t("designer.note.placeholder", { account: col.label || col.account_id })}
                  onChange={(e) => setNote(ci, e.target.value)}
                />
                <div className="dz-col-body">
                  {col.tickers.length === 0 ? (
                    <div className="dz-drop-hint">{t("designer.column.dropHint")}</div>
                  ) : (
                    col.tickers.map((tk, idx) => (
                      <Card
                        key={tk.symbol}
                        symbol={tk.symbol}
                        sector={sectorOf(tk.symbol)}
                        held={heldMap[tk.symbol]}
                        wash={washView(tk.symbol, col.account_type)}
                        accountId={col.account_id}
                        locale={locale}
                        t={t}
                        onRemove={() => removeTicker(ci, idx)}
                        onDragStart={(e) => {
                          dragCtx.current = { from: "card", sym: tk.symbol, col: ci, idx };
                          e.dataTransfer.effectAllowed = "move";
                          e.dataTransfer.setData("text/plain", tk.symbol);
                        }}
                        onDragEnd={() => {
                          dragCtx.current = null;
                          setHotCol(null);
                        }}
                        onDropBefore={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          onDrop(ci, idx);
                        }}
                      />
                    ))
                  )}
                </div>
              </section>
            ))}
          </div>
        </div>
      )}

      <p className="dz-placed" aria-live="polite">
        {t(placed === 1 ? "designer.column.count_one" : "designer.column.count_other", { n: placed })}
      </p>
      {toast && <div className="dz-toast">{toast}</div>}
    </div>
  );
}

function SaveIndicator({
  status,
  updatedAt,
  t,
  locale,
}: {
  status: SaveStatus;
  updatedAt: string | null;
  t: Translator;
  locale: string;
}) {
  if (status === "saving") return <span className="dz-save saving">{t("designer.saving")}</span>;
  if (status === "error") return <span className="dz-save error">{t("designer.saveFailed")}</span>;
  const label =
    updatedAt != null
      ? t("designer.updatedAt", { time: new Date(updatedAt).toLocaleString(locale) })
      : t("designer.saved");
  return <span className="dz-save saved">{label}</span>;
}

interface CardProps {
  symbol: string;
  sector: string;
  held: HeldInfo | undefined;
  wash: WashView;
  accountId: string;
  locale: string;
  t: Translator;
  onRemove: () => void;
  onDragStart: (e: React.DragEvent<HTMLDivElement>) => void;
  onDragEnd: () => void;
  onDropBefore: (e: React.DragEvent<HTMLDivElement>) => void;
}

function Card({
  symbol,
  sector,
  held,
  wash,
  accountId,
  locale,
  t,
  onRemove,
  onDragStart,
  onDragEnd,
  onDropBefore,
}: CardProps) {
  const def = held?.embeddedDeferred ?? 0;
  const hereQty = held?.acctQty[accountId];

  const tipParts: string[] = [wash.tip, wash.sub + "."];
  if (held) {
    if (hereQty) {
      const unrl = held.unrealized;
      tipParts.push(
        t("designer.card.tip.held.detail", {
          qty: hereQty,
          value: money(held.marketValue, locale),
          unrealized: unrl != null ? signed(unrl, locale) : "—",
        }),
      );
    } else {
      tipParts.push(t("designer.card.tip.notHeld.detail"));
    }
  }
  if (def > 0) tipParts.push(t("designer.card.tip.deferred.detail", { amount: moneyc(def, locale) }));

  return (
    <div
      className={`dz-card${def > 0 ? " has-deferred" : ""}`}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDropBefore}
    >
      <span className="dz-card-id dz-tip">
        <span className="dz-sym">{symbol}</span>
        <span className="dz-sec">{sector}</span>
        {hereQty && <span className="dz-qty">{t("designer.card.qty", { qty: hereQty })}</span>}
        <span className="dz-tip-body" role="tooltip">
          {tipParts.join(" ")}
        </span>
      </span>
      {def > 0 && (
        <span className="dz-lock" title={t("designer.lock.title")}>
          🔒
        </span>
      )}
      <span className={`dz-badge ${wash.cls}`}>{wash.cls === "ok" ? "✓" : wash.badge}</span>
      <button className="dz-card-x" onClick={onRemove} aria-label={t("designer.card.remove")}>
        ×
      </button>
    </div>
  );
}
