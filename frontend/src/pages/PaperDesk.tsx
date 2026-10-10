import { useCallback, useEffect, useRef, useState } from "react";

import { ApiRequestError, describeError } from "@/api/client";
import {
  formatFractionPctString,
  formatMoney,
  formatSignedMoney,
  moneyTone,
  paperdeskApi,
  type Book,
  type Desk,
  type PaperDeskState,
  type Purpose,
  type WashSaleFlag,
} from "@/api/paperdesk";
import {
  describePersonaActionError,
  isTraderJobActive,
  personasApi,
  type PersonaBook,
  type TraderBook,
  type TraderJob,
} from "@/api/personas";
import { ConfirmSheet } from "@/components/ConfirmSheet";
import Fetched from "@/components/Fetched";
import PanelBoundary from "@/components/PanelBoundary";
import PersonaBookCard from "@/components/PersonaBookCard";
import PersonaTraderCard, {
  type BackfillState,
  type DecideState,
} from "@/components/PersonaTraderCard";
import { ScrollRegion } from "@/components/ScrollPanel";
import { ToastRegion, useToasts } from "@/components/Toast";
import { useFetch, type FetchPhase } from "@/hooks/useFetch";
import { useT } from "@/i18n";
import "./PaperDesk.css";
import "./Personas.css";

import { BookSection, DeskHeader } from "./paperdesk/BookSection";
import LiveTape from "./paperdesk/LiveTape";

/**
 * The desk owner's default view on first load -- three chosen because that is what one screen
 * reads comfortably three-to-a-row, not because these three are somehow "the" desks. This is a
 * viewing preference, not a property of the strategies, and the chooser below lists every desk on
 * the roster so switching one on is one click.
 *
 * **Tracks the roster deliberately.** The owner's default view is the momentum card, the rotation
 * card and the ladder. Round 11 gave the ranked momentum seat to `B3-concentrated`, and the owner
 * then re-seated `B-momentum` beside it (`data/rounds/r11-2026-08/SELECTION.md` section 8), so the
 * desk now carries both. **The wider of the two is the default**, and the narrower is not lost by
 * that choice: `B3-concentrated` holds a strict subset of `B-momentum`'s names -- the same four,
 * where `B-momentum` holds six -- so a reader who never ticks it still sees every name it holds.
 * `B3-concentrated` and `C-trend` are listed in the chooser, unticked on first load.
 *
 * An id named here that the roster does not carry is degraded by `DeskVisibilityChooser` -- it
 * simply never renders a checkbox or panel, rather than crashing or leaving an empty slot -- and
 * that path has its own test. It is the safety net for a re-rostering, not the intended steady
 * state after one: leaving a retired card named here would default a newly seated card to hidden.
 *
 * `"autopilot-workflow"` was added alongside the `kind === "autopilot"` seat for the same reason
 * the three cards above are named: a reader should see the desk's own default view -- momentum,
 * rotation, ladder, and now the workflow's autopilot book -- without an extra click on first load.
 */
const DEFAULT_VISIBLE_AGENT_IDS: readonly string[] = [
  "B-momentum",
  "A-rotation",
  "ladder-qld-schd",
  "autopilot-workflow",
];

/**
 * Paper Desk: a live account view for the strategies on the desk's roster, each started with the
 * same cash balance on a common inception date and traded forward on the application's stored daily
 * bars. Which strategies, how much, and from when are all `app.paperdesk.desk`'s decisions
 * (`AGENT_IDS`, `INCEPTION`) and arrive in the payload — this page renders them and never restates
 * them, having once described two strategies and an August start above a table showing three and a
 * June one.
 *
 * The one fact this page must never let the reader forget: `as_of` is the store's most recent
 * session, not "now". Every figure below is marked to that session's close, and `stale_days` says
 * how far behind the calendar that mark actually is -- see `MarkNote` and the callout it renders
 * when the gap is large. A page that shows a three-day-old mark next to numbers that look live is
 * exactly the kind of quiet dishonesty `Portfolio.tsx`'s own rules (partial totals named at the
 * figure, `null` never coerced to zero) exist to rule out elsewhere in this app; the same discipline
 * applies here, just against staleness instead of missing data.
 *
 * `realised_pnl` and `unrealised_pnl` are rendered as two distinct, separately labelled figures and
 * are never added together on screen -- see `PnlTiles`. A mark against the last stored close is not
 * money the desk has actually taken, and folding the two into one "P&L" states a certainty about the
 * unrealised half that does not exist until a position is actually closed.
 */
export default function PaperDesk() {
  const { t } = useT();
  const [data, setData] = useState<PaperDeskState | null>(null);
  const [phase, setPhase] = useState<FetchPhase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  // The inception picker's own draft value -- a plain text field, not derived from `data.inception`
  // on every render, so a reader mid-edit is not fighting a value that keeps resetting under them.
  // Re-seeded only when the *served* inception actually changes (initial load, a successful apply, a
  // successful reset) -- see the effect below, keyed on `data?.inception` specifically rather than on
  // `data` as a whole, so an unrelated `Refresh` (which never changes `inception`) leaves an in-
  // progress edit alone.
  const [inceptionDraft, setInceptionDraft] = useState("");
  const [applyingInception, setApplyingInception] = useState(false);
  const [inceptionError, setInceptionError] = useState<string | null>(null);
  // Gates the one real mutation on this page: applying a new inception recomputes every book,
  // across every purpose, not just the one currently in view -- see the `ConfirmSheet` rendered
  // near `InceptionControl` below. `Apply` opens this instead of firing the request directly;
  // the request itself only ever fires from `confirmApplyInception`.
  const [confirmingInception, setConfirmingInception] = useState(false);

  const { toasts, push: pushToast, dismiss: dismissToast } = useToasts();

  // The influencer paper books -- fetched independently of `paperdeskApi.state()` above. This
  // section renders beside the reference-agent books but does not depend on them: a failure here
  // must never blank the rest of the desk, and the desk's own fetch must never wait on this one.
  const personaBooksResult = useFetch<PersonaBook[]>((signal) => personasApi.books(signal), []);

  // The persona MODEL-DRIVEN trader books (Phase 10) -- a second, independent section beside the
  // Phase-6 replay books above and the reference-agent desks. Same isolation rule: fetched on its
  // own, and a failure here must never blank the rest of the page.
  const traderBooksResult = useFetch<TraderBook[]>((signal) => personasApi.traderBooks(signal), []);

  // Per-persona (keyed by slug) in-flight state for the two on-demand trader actions -- a plain
  // record rather than one state variable per card, since the roster size is not known up front.
  const [decideStates, setDecideStates] = useState<Record<string, DecideState>>({});
  const [backfillStates, setBackfillStates] = useState<Record<string, BackfillState>>({});

  // Active backfill jobs, keyed by slug -- the poll target for the single interval below. Kept in a
  // ref alongside the state so the interval always reads the latest jobs without needing to be torn
  // down and rebuilt every time one job's own progress ticks (same reasoning as `PersonaDetail.tsx`'s
  // `ingestJobRef`, generalised across every persona's own job at once instead of one slug).
  const [activeBackfillJobs, setActiveBackfillJobs] = useState<Record<string, TraderJob>>({});
  const activeBackfillJobsRef = useRef(activeBackfillJobs);
  useEffect(() => {
    activeBackfillJobsRef.current = activeBackfillJobs;
  }, [activeBackfillJobs]);

  const handleTraderDecide = useCallback(
    (slug: string) => {
      setDecideStates((prev) => ({ ...prev, [slug]: { phase: "pending" } }));
      personasApi
        .traderDecide(slug)
        .then((updated) => {
          setDecideStates((prev) => ({ ...prev, [slug]: { phase: "idle" } }));
          traderBooksResult.setData((prev) =>
            prev ? prev.map((b) => (b.persona === slug ? updated : b)) : prev,
          );
        })
        .catch((err: unknown) => {
          setDecideStates((prev) => ({
            ...prev,
            [slug]: {
              phase: "error",
              message: describePersonaActionError(err, t("personaTrader.decideErrorFallback")),
            },
          }));
        });
    },
    [t, traderBooksResult],
  );

  const handleTraderBackfill = useCallback(
    (slug: string, inception: string) => {
      setBackfillStates((prev) => ({ ...prev, [slug]: { phase: "running", decided: 0 } }));
      personasApi
        .traderBackfill(slug, inception ? { inception } : {})
        .then((job) => {
          setActiveBackfillJobs((prev) => ({ ...prev, [slug]: job }));
        })
        .catch((err: unknown) => {
          setBackfillStates((prev) => ({
            ...prev,
            [slug]: {
              phase: "error",
              message: describePersonaActionError(err, t("personaTrader.backfillErrorFallback")),
            },
          }));
        });
    },
    [t],
  );

  const handleTraderReset = useCallback(
    (slug: string) => {
      personasApi
        .resetTrader(slug)
        .then(() => personasApi.traderBook(slug))
        .then((freshBook) => {
          traderBooksResult.setData((prev) =>
            prev ? prev.map((b) => (b.persona === slug ? freshBook : b)) : prev,
          );
        })
        .catch(() => {
          // A reset that fails leaves the book as last known -- a full reload picks up the true
          // state rather than this page guessing at a partial one.
          traderBooksResult.reload();
        });
    },
    [traderBooksResult],
  );

  // One interval, shared across every persona with an active backfill job -- polls each until it
  // settles, then refreshes that persona's own book once and clears its job/backfill state.
  const anyBackfillActive = Object.values(activeBackfillJobs).some((job) => isTraderJobActive(job.state));
  useEffect(() => {
    if (!anyBackfillActive) return;
    const id = setInterval(() => {
      for (const [slug, job] of Object.entries(activeBackfillJobsRef.current)) {
        if (!isTraderJobActive(job.state)) continue;
        personasApi
          .traderBackfillJob(slug, job.job_id)
          .then((updated) => {
            setActiveBackfillJobs((prev) => ({ ...prev, [slug]: updated }));
            if (isTraderJobActive(updated.state)) {
              setBackfillStates((prev) => ({
                ...prev,
                [slug]: { phase: "running", decided: updated.decided_count },
              }));
              return;
            }
            if (updated.state === "succeeded") {
              setBackfillStates((prev) => ({ ...prev, [slug]: { phase: "idle" } }));
              personasApi
                .traderBook(slug)
                .then((freshBook) => {
                  traderBooksResult.setData((prev) =>
                    prev ? prev.map((b) => (b.persona === slug ? freshBook : b)) : prev,
                  );
                })
                .catch(() => {
                  // A transient refresh failure after a settled job is not fatal -- the last
                  // known book stays on screen; the reader can trigger another action to retry.
                });
            } else {
              setBackfillStates((prev) => ({
                ...prev,
                [slug]: {
                  phase: "error",
                  message: updated.error ?? t("personaTrader.backfillErrorFallback"),
                },
              }));
            }
          })
          .catch(() => {
            // A transient poll failure is not fatal -- the next tick tries again.
          });
      }
    }, 2000);
    return () => clearInterval(id);
    // `anyBackfillActive` (not `activeBackfillJobs` itself) keys this effect, matching
    // `PersonaDetail.tsx`'s own `jobActive` reasoning -- a job's own progress ticking upward must
    // not tear down and rebuild the interval.
  }, [anyBackfillActive, t, traderBooksResult]);

  // Seeded once from the named constant, not from the payload -- this is local view state (which
  // panels to show), independent of the roster itself. Membership is checked by agent_id when
  // rendering, so an id here that never matches a desk in the current payload (dropped from the
  // roster, or simply never present) just never renders a checkbox or panel; it is not an error
  // state and does not need to be filtered out of this set. Not persisted across a reload -- see
  // the module-level note in the task brief; a plain in-memory default is enough for a viewing
  // preference that resets each visit.
  const [visibleAgentIds, setVisibleAgentIds] = useState<Set<string>>(
    () => new Set(DEFAULT_VISIBLE_AGENT_IDS),
  );
  const toggleDeskVisible = useCallback((agentId: string) => {
    setVisibleAgentIds((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) {
        next.delete(agentId);
      } else {
        next.add(agentId);
      }
      return next;
    });
  }, []);

  // Books this session has already seeded a default visibility for, so a reader who deliberately
  // unticks every desk in a book does not get them all ticked back on the next refresh.
  const seededBooks = useRef<Set<string>>(new Set());

  // **Seed each book's visibility the first time that book is seen.**
  //
  // `DEFAULT_VISIBLE_AGENT_IDS` above names three *trading* cards, chosen deliberately when this
  // page had one book (`B3-concentrated` and `C-trend` are listed-but-unticked on purpose -- see
  // that constant's own docstring). With three books it silently became a bug the constant itself
  // predicted: "leaving a retired card named here would default a newly seated card to hidden."
  // Savings and Roth own none of those three ids, so selecting either tab rendered "No desks are
  // selected in this book" -- which reads as *the reader* having hidden them, about books whose
  // cards were never offered in the first place.
  //
  // The rule: a book with no expressed preference shows everything it has. A book that does have
  // one keeps it exactly, so the trading book's considered defaults are untouched.
  useEffect(() => {
    if (!data) return;
    const unseeded = data.books.filter((b) => !seededBooks.current.has(b.purpose));
    if (unseeded.length === 0) return;
    const toShow = unseeded
      .filter((b) => !b.desks.some((d) => visibleAgentIds.has(d.agent_id)))
      .flatMap((b) => b.desks.map((d) => d.agent_id));
    for (const b of unseeded) seededBooks.current.add(b.purpose);
    if (toShow.length === 0) return;
    setVisibleAgentIds((prev) => new Set([...prev, ...toShow]));
  }, [data, visibleAgentIds]);

  // Which book the reader is looking at right now -- one at a time, not all three stacked.
  // "trading" is the account with cards seated today; defaulting to "savings" or "roth" would open
  // the page on an empty-book placeholder. Looked up by purpose, never by array position, so a
  // reordering of `data.books` (the wire contract does not promise one) can't silently swap which
  // tab a reader lands on.
  const [activePurpose, setActivePurpose] = useState<Purpose>("trading");
  const activeBook = data?.books.find((b) => b.purpose === activePurpose) ?? data?.books[0];

  useEffect(() => {
    const controller = new AbortController();
    setPhase("loading");
    setMessage(null);
    paperdeskApi
      .state(controller.signal)
      .then((state) => {
        setData(state);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setMessage(
          e instanceof ApiRequestError
            ? t("paperDesk.apiError", { status: e.status, message: e.message })
            : t("paperDesk.cannotReachApi"),
        );
        setPhase("error");
      });
    return () => {
      controller.abort();
    };
  }, []);

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    setRefreshError(null);
    paperdeskApi
      .refresh()
      .then((state) => {
        setData(state);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        setRefreshError(
          e instanceof ApiRequestError
            ? t("paperDesk.refreshFailedApi", { status: e.status, message: e.message })
            : t("paperDesk.refreshFailedUnreachable"),
        );
      })
      .finally(() => {
        setRefreshing(false);
      });
  }, []);

  useEffect(() => {
    if (data) setInceptionDraft(data.inception);
  }, [data?.inception]);

  /**
   * Apply/Reset both land here: a `PUT`/`DELETE` to `/api/paperdesk/inception`, which recomputes and
   * returns the *entire* desk state in one round trip -- no follow-up `state()` call, matching
   * `paperdeskApi.setInception`/`resetInception`'s own contract. `setPhase("loaded")` mirrors
   * `handleRefresh` above; it is a no-op on the happy path (the page is already `"loaded"` by the
   * time either control is reachable) and only matters if a caller somehow reaches this from another
   * phase.
   *
   * A rejected date (out of `[earliest_inception, latest_inception]`, or otherwise unusable) comes
   * back as a `422` whose body names the specific reason -- `describeError` reads `ApiRequestError`'s
   * own `.message`, which is already that reason after `paperdesk.ts`'s `detailOf` unwrapping, so
   * this never falls back to a generic string on that path.
   */
  const applyState = useCallback(
    (request: Promise<PaperDeskState>) => {
      setApplyingInception(true);
      setInceptionError(null);
      request
        .then((state) => {
          setData(state);
          setPhase("loaded");
          pushToast({ message: t("paperDesk.inception.appliedToast", { date: state.inception }), tone: "ok" });
        })
        .catch((e: unknown) => {
          setInceptionError(describeError(e, t("paperDesk.inceptionUnreachable")));
        })
        .finally(() => {
          setApplyingInception(false);
        });
    },
    [pushToast, t],
  );

  // `Apply` no longer fires the request directly -- it only opens the confirm sheet below.
  // `confirmApplyInception` is what `paperdeskApi.setInception` actually gets called from, once
  // the reader has seen and accepted the preview of what changes.
  const openInceptionConfirm = useCallback(() => {
    setConfirmingInception(true);
  }, []);

  const cancelInceptionConfirm = useCallback(() => {
    setConfirmingInception(false);
  }, []);

  const confirmApplyInception = useCallback(() => {
    setConfirmingInception(false);
    applyState(paperdeskApi.setInception(inceptionDraft));
  }, [applyState, inceptionDraft]);

  const handleResetInception = useCallback(() => {
    applyState(paperdeskApi.resetInception());
  }, [applyState]);

  return (
    <>
      <ToastRegion toasts={toasts} onDismiss={dismissToast} />
      <h1>{t("paperDesk.title")}</h1>
      {/* Built from the payload, never restated. This line previously hardcoded "Two ... strategies
          -- B-momentum and C-trend -- ... on 2026-08-01"; the roster then gained a third strategy
          and the desk was backdated, and the page went on confidently describing the old setup
          above a table showing the new one. A page that narrates its own data has to read it. */}
      <p className="subtitle">
        {data
          ? t(deskCount(data) === 1 ? "paperDesk.subtitle_one" : "paperDesk.subtitle_other", {
              count: deskCount(data),
              books: data.books.length,
              list: data.books.map((b) => b.label).join(", "),
              date: data.inception,
            })
          : t("paperDesk.subtitleLoading")}
      </p>

      {/* The reference model, stated plainly at page level -- these desks are read one at a time,
          each as its own independent signal, not summed into a book. A reader deciding what to buy
          in a single real account needs this said before the per-desk panels, not inferred from the
          absence of a combined total. */}
      <p className="muted desk-framing-note">
        {data ? t("paperDesk.framingNote") : t("paperDesk.framingNoteLoading")}
      </p>

      {phase === "loading" && (
        <div className="panel">
          <div className="placeholder">{t("paperDesk.loading")}</div>
        </div>
      )}

      {phase === "error" && (
        <div className="panel">
          <div className="placeholder">{message}</div>
        </div>
      )}

      {phase === "loaded" && data && (
        <>
          {/* The Live Tape: which symbols are actually in play right now, with live prices streaming
              in -- deliberately the first thing on the loaded page, above the inception control and
              every book section below it. Each top-level panel below gets its own boundary: a bad
              value anywhere in one desk's figures must not blank the inception control, the header,
              or every other book's cards along with it -- see `ErrorBoundary.tsx`'s own docstring
              for the concrete incident (an undefined money field) this pattern exists to contain. */}
          <PanelBoundary label={t("paperDesk.panel.liveTape")}>
            <LiveTape state={data} />
          </PanelBoundary>

          {/* The inception control sits beside `DeskHeader`'s own Refresh button, both being ways to
              trigger a recompute -- kept outside the busy overlay below so the control that is
              *causing* the busy state, and its own "Applying…" wording, stay legible while it runs. */}
          <PanelBoundary label={t("paperDesk.panel.inceptionControl")}>
            <InceptionControl
              state={data}
              draft={inceptionDraft}
              onDraftChange={setInceptionDraft}
              busy={applyingInception}
              onApply={openInceptionConfirm}
              onReset={handleResetInception}
              error={inceptionError}
            />
          </PanelBoundary>

          {/* The one real mutation-guard on this page: applying a new inception is a `PUT` that
              recomputes and replaces every book across every purpose, not just the one currently in
              view, and previously fired the moment `Apply` was clicked -- one date-field slip cost
              the whole desk's history. `question`/`preview` state plainly what is about to change,
              named against `data.books` rather than a generic sentence, so the reader is confirming
              the actual scope, not a guess at it. */}
          <ConfirmSheet
            open={confirmingInception}
            question={t("paperDesk.inception.confirmQuestion", { date: inceptionDraft })}
            preview={
              <p>
                {t("paperDesk.inception.confirmPreview", {
                  count: data.books.length,
                  books: data.books.map((b) => b.label).join(", "),
                })}
              </p>
            }
            busy={applyingInception}
            tone="warn"
            onConfirm={confirmApplyInception}
            onCancel={cancelInceptionConfirm}
          />

          {/* Recomputing every book from a new inception takes real time (a cold roster costs
              seconds per card) -- the whole desk below is dimmed and overlaid with a spinner that
              says what is happening, rather than leaving the old equity/return figures looking live
              while they are silently replaced underneath them. */}
          <div className={`desk-content${applyingInception ? " desk-content-busy" : ""}`}>
            {applyingInception && (
              <div className="desk-recompute-overlay" role="status" aria-live="polite">
                <span className="desk-recompute-spinner" aria-hidden="true" />
                <p>
                  {t("paperDesk.recomputeOverlay", { date: inceptionDraft || data.inception })}
                </p>
                <p className="desk-recompute-detail">{t("paperDesk.recomputeDetail")}</p>
              </div>
            )}

            <PanelBoundary label={t("paperDesk.panel.deskHeader")}>
              <DeskHeader
                data={{ ...data, notes: notesForHeader(data.notes) }}
                refreshing={refreshing}
                onRefresh={handleRefresh}
                refreshError={refreshError}
              />
            </PanelBoundary>

            {/* The honesty label: a custom inception can straddle the strategy design cutoff, which
                makes the sessions at or before it in-sample -- see this module's docstring and
                `InSampleWarning` below. Rendered once, here, near the header's own headline figures;
                `notesForHeader` above strips the backend's matching `notes` entry so the same
                sentence never prints twice. */}
            {(data.in_sample_sessions ?? 0) > 0 && (
              <PanelBoundary label={t("paperDesk.panel.inSampleWarning")}>
                <InSampleWarning state={data} />
              </PanelBoundary>
            )}

            {/* One book shown at a time -- this app's established in-page view-switch pattern (see
                Competition.tsx), used here because the tabs switch content in place rather than
                routing between pages. A book with `desks: []` is still a real, renderable state (a
                purpose can be funded before a card exists for it) and must still get a tab. */}
            <div className="view-tabs" role="tablist" aria-label={t("paperDesk.viewTabsAriaLabel")}>
              {data.books.map((b) => (
                <button
                  key={b.purpose}
                  type="button"
                  role="tab"
                  aria-selected={b.purpose === activePurpose}
                  className={`timeframe-tab${b.purpose === activePurpose ? " active" : ""}`}
                  onClick={() => setActivePurpose(b.purpose)}
                >
                  {b.label}
                </button>
              ))}
            </div>
            {activeBook && (
              <PanelBoundary label={t("paperDesk.panel.bookSection", { label: activeBook.label })}>
                <BookSection
                  book={activeBook}
                  asOf={data.as_of}
                  visible={visibleAgentIds}
                  onToggle={toggleDeskVisible}
                />
              </PanelBoundary>
            )}

            {/* One "After tax" panel per currently-visible rules desk that actually carries a `tax`
                summary -- see `taxedVisibleDesks` below for exactly which desks that is. Each desk
                gets its own boundary, same reasoning as every other per-desk panel on this page: a
                bad wash-sale figure on one desk must not blank the others, or the book above it. */}
            {activeBook &&
              taxedVisibleDesks(activeBook, visibleAgentIds).map((d) => (
                <PanelBoundary
                  key={d.agent_id}
                  label={t("paperDesk.panel.afterTax", { name: d.display_name })}
                >
                  <AfterTaxPanel desk={d} />
                </PanelBoundary>
              ))}
          </div>
        </>
      )}

      {/* Influencer paper books: descriptive paper projections following each followed influencer's
          own live bullish calls, rendered beside the reference-agent books above. Fetched
          independently of `paperdeskApi.state()` -- it renders regardless of that fetch's own
          phase, and a failure here (network error, non-200) never blanks the rest of the desk. */}
      <PanelBoundary label={t("personaBook.deskSection.heading")}>
        <section className="panel">
          <h2>{t("personaBook.deskSection.heading")}</h2>
          <p className="muted">{t("personaBook.deskSection.caveat")}</p>

          <Fetched
            state={personaBooksResult}
            loading={<div className="placeholder">{t("personaBook.deskSection.loading")}</div>}
            error={<div className="callout callout-warn">{t("personaBook.deskSection.error")}</div>}
            isEmpty={(books) => books.length === 0}
            empty={<p className="muted">{t("personaBook.deskSection.empty")}</p>}
          >
            {(books) => (
              <>
                {books.map((b) => (
                  <PersonaBookCard key={b.persona} book={b} />
                ))}
              </>
            )}
          </Fetched>
        </section>
      </PanelBoundary>

      {/* Persona MODEL-DRIVEN paper traders (Phase 10): each persona's model, as the persona,
          deciding what to buy/sell weekly against its own consolidated method -- distinct from the
          deterministic replay books above. Fetched independently of both `paperdeskApi.state()` and
          `personasApi.books()`; a failure here must never blank either of those sections. */}
      <PanelBoundary label={t("personaTrader.deskSection.heading")}>
        <section className="panel">
          <h2>{t("personaTrader.deskSection.heading")}</h2>
          <p className="muted">{t("personaTrader.deskSection.caveat")}</p>

          <Fetched
            state={traderBooksResult}
            loading={<div className="placeholder">{t("personaTrader.deskSection.loading")}</div>}
            error={<div className="callout callout-warn">{t("personaTrader.deskSection.error")}</div>}
            isEmpty={(books) => books.length === 0}
            empty={<p className="muted">{t("personaTrader.deskSection.empty")}</p>}
          >
            {(books) => (
              <>
                {books.map((b) => (
                  <PersonaTraderCard
                    key={b.persona}
                    book={b}
                    decideState={decideStates[b.persona] ?? { phase: "idle" }}
                    backfillState={backfillStates[b.persona] ?? { phase: "idle" }}
                    onDecide={() => handleTraderDecide(b.persona)}
                    onBackfill={(inception) => handleTraderBackfill(b.persona, inception)}
                    onReset={() => handleTraderReset(b.persona)}
                  />
                ))}
              </>
            )}
          </Fetched>
        </section>
      </PanelBoundary>
    </>
  );
}

/** How many desks the whole page is showing, across every book. */
function deskCount(data: PaperDeskState): number {
  return data.books.reduce((n, b) => n + b.desks.length, 0);
}

/**
 * `book`'s own desks, narrowed to the ones this page should actually show an "After tax" panel for:
 * currently ticked in the visibility chooser (`visible`, the same set `BookSection`'s own grid
 * filters by, so a hidden desk's tax panel does not linger below an empty grid), `kind === "rules"`
 * or `kind === "autopilot"` (a ladder or allocation desk's `tax` is always `null` server-side -- see
 * `Desk.tax`'s own docstring -- but this checks `kind` too rather than trusting that invariant
 * blindly), and `tax !== null` -- which is what actually decides "does this book's purpose realise a
 * taxable event", server-side (see `app.paperdesk.desk._build_desk`'s `taxable` argument): a Roth
 * desk always fails this filter, with no client-side purpose check needed to know that.
 *
 * An autopilot seat on a taxable book carries a real `tax` summary too -- the same
 * `summarize_paper_tax` engine runs over the workflow book's own persisted fills, exactly as it does
 * for a rules desk's closed trades -- so excluding `kind === "autopilot"` here would silently drop a
 * tax panel the server actually computed and sent.
 */
function taxedVisibleDesks(book: Book, visible: Set<string>): Desk[] {
  return book.desks.filter(
    (d) =>
      visible.has(d.agent_id) &&
      (d.kind === "rules" || d.kind === "autopilot") &&
      d.tax != null,
  );
}

/**
 * One desk's after-tax summary: net realised gain, the short/long split, tax owed at the desk's own
 * rate, the resulting after-tax figure, and every wash sale IRC 1091 disallowed over the window.
 *
 * Computed by the real cost-basis / wash-sale engine (`app.paper.papertax.summarize_paper_tax`) from
 * fills synthesised out of this desk's own closed trades -- not a client-side estimate. The one gap
 * that computation has is stated once, at the book level, in `Book.notes` (rendered by
 * `BookSection`/`DeskHeader` already, not repeated here): the synthesised fills carry no fees, so
 * this omits the paper broker's own per-leg regulatory fees.
 */
function AfterTaxPanel({ desk }: { desk: Desk }) {
  const { t } = useT();
  const tax = desk.tax;
  if (!tax) return null;

  return (
    <section className="panel desk-panel">
      <div className="desk-panel-head">
        <h2 className="desk-panel-title">
          {t("paperDesk.afterTax.title", { name: desk.display_name })}
        </h2>
        <span className="badge desk-discipline-badge">
          {tax.rate_basis === "statutory_upper_bound"
            ? t("paperDesk.afterTax.statutoryUpperBoundRate")
            : tax.rate_basis}
        </span>
      </div>
      <p className="muted">
        {t("paperDesk.afterTax.rateNote", {
          start: tax.start,
          end: tax.end,
          shortRate: formatFractionPctString(tax.short_term_rate),
          longRate: formatFractionPctString(tax.long_term_rate),
        })}
      </p>
      <div className="status-grid desk-book-grid">
        <TaxStat
          label={t("paperDesk.afterTax.netRealisedGain")}
          value={formatSignedMoney(tax.net_realized_gain)}
          tone={moneyTone(tax.net_realized_gain)}
        />
        <TaxStat
          label={t("paperDesk.afterTax.shortTermGain")}
          value={formatSignedMoney(tax.short_term_gain)}
          tone={moneyTone(tax.short_term_gain)}
        />
        <TaxStat
          label={t("paperDesk.afterTax.longTermGain")}
          value={formatSignedMoney(tax.long_term_gain)}
          tone={moneyTone(tax.long_term_gain)}
        />
        <TaxStat label={t("paperDesk.afterTax.taxOwed")} value={formatMoney(tax.tax_owed)} />
        <TaxStat
          label={t("paperDesk.afterTax.afterTaxRealisedGain")}
          value={formatSignedMoney(tax.after_tax_realized_gain)}
          tone={moneyTone(tax.after_tax_realized_gain)}
        />
      </div>

      <div className="desk-section">
        <h3>{t("paperDesk.afterTax.washSalesHeading")}</h3>
        {tax.wash_sales.length === 0 ? (
          <div className="placeholder">{t("paperDesk.afterTax.noWashSales")}</div>
        ) : (
          /* Bounded. This panel is not a `Card` -- it renders full width below the desk grid, one
             per taxed desk -- so nothing else was capping it, and a desk with a long wash-sale
             history pushed the page rather than the table. `md` matches every other table on this
             page; the heading above stays outside the region, per `ScrollPanel`'s own convention. */
          <ScrollRegion size="md" label={t("paperDesk.afterTax.washSalesHeading")}>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">{t("common.symbol")}</th>
                    <th scope="col">{t("paperDesk.afterTax.lossDate")}</th>
                    <th scope="col">{t("paperDesk.afterTax.repurchaseDate")}</th>
                    <th scope="col" className="num">
                      {t("paperDesk.afterTax.disallowedAmount")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {tax.wash_sales.map((w) => (
                    <WashSaleRow key={w.event_id} flag={w} />
                  ))}
                </tbody>
              </table>
            </div>
          </ScrollRegion>
        )}
      </div>
    </section>
  );
}

function WashSaleRow({ flag }: { flag: WashSaleFlag }) {
  return (
    <tr>
      <td>
        <span className="position-symbol">{flag.symbol}</span>
      </td>
      <td>{flag.loss_date}</td>
      <td>{flag.repurchase_date ?? "—"}</td>
      <td className="num">{formatMoney(flag.disallowed_amount)}</td>
    </tr>
  );
}

function TaxStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "" | "pos" | "neg";
}) {
  return (
    <div className="stat tile">
      <span className="label">{label}</span>
      <span className={`value${tone ? ` ${tone}` : ""}`}>{value}</span>
    </div>
  );
}

/**
 * `data.notes` minus a possible duplicate of the in-sample hazard `InSampleWarning` already states.
 * The backend adds a note to `PaperDeskState.notes` naming the same design-cutoff fact whenever
 * `in_sample_sessions > 0`; `DeskHeader` renders every note in that array generically, so passing it
 * through unfiltered would print the identical sentence twice on screen -- once as a plain list item,
 * once as this page's own dedicated `.callout-warn` treatment.
 *
 * Filtered by a case-insensitive "design cutoff" match rather than an exact string: this page does
 * not own the backend's exact wording, and the two are built in parallel. A false negative here (the
 * keyword not matching a differently-worded note) costs a duplicated sentence, not a dropped one --
 * the generic note still renders -- so the fallback direction is the safe one.
 */
function notesForHeader(notes: string[]): string[] {
  return notes.filter((note) => !/design cutoff/i.test(note));
}

/**
 * The honesty label this module's docstring calls "the part that matters most". A custom inception
 * can straddle the strategy design cutoff the same way a previous *default* inception once did (see
 * the backend's `INCEPTION` docstring); making the date user-settable reopens that hazard, so this
 * renders unconditionally whenever `in_sample_sessions > 0` -- not just for an override, since the
 * built-in default is not guaranteed safe against a future design-cutoff move either.
 *
 * `.callout-warn` reused as-is, per the task brief, rather than inventing a new style.
 */
function InSampleWarning({ state }: { state: PaperDeskState }) {
  const { t } = useT();
  return (
    <div className="callout callout-warn desk-insample-callout" role="alert">
      <strong>
        {t("paperDesk.inSample.strong", {
          count: state.in_sample_sessions ?? 0,
          cutoff: state.design_cutoff ?? t("paperDesk.inSample.unknown"),
        })}
      </strong>{" "}
      {t("paperDesk.inSample.body")}
    </div>
  );
}

/**
 * The inception picker, beside `DeskHeader`'s own Refresh control. Setting a new date (`Apply`) or
 * clearing an override (`Reset to default`) both change the window every book is traded over and
 * re-run every agent from that date -- neither fetches new market data, and neither changes which
 * strategies are seated. That distinction is stated in `.desk-inception-hint` below so a reader does
 * not read "Apply" as a lightweight refresh.
 *
 * `min`/`max` on the date input mirror `earliest_inception`/`latest_inception` so the browser rejects
 * most invalid dates before a request is even made; a date the browser lets through but the backend
 * still rejects (e.g. one landing on a non-trading day) surfaces as `error`, the server's own reason,
 * rather than a generic failure -- see `paperdeskApi.setInception`'s `detailOf` unwrapping.
 */
function InceptionControl({
  state,
  draft,
  onDraftChange,
  busy,
  onApply,
  onReset,
  error,
}: {
  state: PaperDeskState;
  draft: string;
  onDraftChange: (value: string) => void;
  busy: boolean;
  onApply: () => void;
  onReset: () => void;
  error: string | null;
}) {
  const { t } = useT();
  const applyDisabled = busy || !draft || draft === state.inception;

  return (
    <div className="panel desk-inception-panel">
      <div className="desk-inception-row">
        <label className="desk-inception-field">
          <span className="desk-inception-label">{t("paperDesk.inception.label")}</span>
          <input
            type="date"
            value={draft}
            min={state.earliest_inception}
            max={state.latest_inception}
            disabled={busy}
            onChange={(e) => onDraftChange(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="download-link desk-inception-apply"
          onClick={onApply}
          disabled={applyDisabled}
        >
          {busy ? t("paperDesk.inception.applying") : t("common.apply")}
        </button>
        {state.inception_is_custom && state.inception_default && (
          <button
            type="button"
            className="download-link desk-inception-reset"
            onClick={onReset}
            disabled={busy}
            title={t("paperDesk.inception.resetTitle", { date: state.inception_default })}
          >
            {t("paperDesk.inception.resetLabel", { date: state.inception_default })}
          </button>
        )}
      </div>
      <p className="muted desk-inception-hint">{t("paperDesk.inception.hint")}</p>
      {error && (
        <div className="callout callout-danger desk-inception-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
