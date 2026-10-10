/**
 * /personas -- one compact digest row per followed influencer, a form to add a persona, and the
 * two cross-persona consensus panels. Each row links to `/personas/{slug}` (`PersonaDetail.tsx`,
 * `./personas/PersonaDetail.tsx`) for that persona's full nine-panel stack (profile, scorecard,
 * timeline, backtest, ask, strategy card, critique, profile diff, plus the digest card itself).
 *
 * **Why this page no longer mounts those nine panels.** It used to, once per followed persona, all
 * at once -- with ~5 personas that was roughly thirteen screens of panels stacked vertically, and
 * every persona's profile/scorecard/timeline/backtest fetch fired on load whether or not anyone
 * scrolled down to look. Splitting the per-persona detail state and fetches out to `PersonaDetail`
 * means this page now only ever fetches the one list-level thing it actually needs to render a
 * digest row -- `GET /api/personas/cards` -- plus the two page-level cross-persona panels below.
 *
 * `usePersonas()` (`@/hooks/usePersonas`) owns that one fetch and this page's own loading/error
 * state; it always answers `200` (empty array with zero personas, a card with `as_of: null` for a
 * persona with no notes yet). Add and remove still live here at the page level, the same split
 * `TradingAgents.tsx` uses between its config/runs fetch hooks and its mutation callbacks -- each
 * mutation owns its own pending/error state, keyed by persona slug where more than one persona can
 * be mid-action at once, so one persona's failed removal never blanks another's row.
 *
 * **The mutating routes answer `501` today** (Phase 1 backend lands in parallel -- see
 * `docs/INFLUENCER-CONTRACT.md`). `describePersonaActionError` (`@/api/personas`) unwraps that
 * response's `detail` into the pending/error state below exactly like any other rejection, so this
 * page needs no change at all once the backend actually lands -- only the message shown changes.
 *
 * **Removing a persona stays here, on the list.** Deleting from `PersonaDetail` instead (via its
 * own mounted `PersonaCard`) still works and navigates back to this page afterwards -- see that
 * file's own docstring -- but the row-level remove button below is this page's own, lighter-weight
 * action: no ingest state to tear down, just the one `DELETE` call and a `reload()`. It goes through
 * `ConfirmSheet` first (EXP-24): removal destroys a persona and everything ingested for it, and
 * `pages/data/UsersPanel.tsx` draws the line at exactly that -- confirm what spends or destroys,
 * never what merely recomputes. The row button opens the sheet; only the sheet calls `DELETE`.
 *
 * **Ingest lives entirely on the detail page now.** Starting an ingest is a per-persona,
 * job-registry-polled action (`PersonaDetail.tsx` owns it) -- this page's own digest row is
 * read-only, matching its "compact summary that links onward" role.
 */
import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { Link } from "react-router-dom";

import {
  describePersonaActionError,
  formatRelativeAge,
  personasApi,
  stanceLabel,
  type DigestCard,
  type Platform,
} from "@/api/personas";
import { Card, CardGrid } from "@/components/Card";
import Collapsible from "@/components/Collapsible";
import { ConfirmSheet } from "@/components/ConfirmSheet";
import PanelBoundary from "@/components/PanelBoundary";
import PersonaRegime, { type RegimeState } from "@/components/PersonaRegime";
import PersonaWatchlist, { type WatchlistState } from "@/components/PersonaWatchlist";
import { Skeleton } from "@/components/Skeleton";
import StatusPill from "@/components/StatusPill";
import { useUrlState } from "@/hooks/useUrlState";
import { usePersonas } from "@/hooks/usePersonas";
import { useT } from "@/i18n";
import { BackfillSection } from "@/pages/BackfillTasks";

import "./Personas.css";

interface AddPersonaDraft {
  handle: string;
  platform: Platform;
}

/** The `?panel=` values this page recognises. `""` is "no panel open" and, being the fallback,
 *  never appears in the URL -- see `useUrlState`'s module docstring. */
const PANELS = ["", "backfill"] as const;

export default function Personas() {
  const { t } = useT();
  const { cards, phase, message, reload } = usePersonas();

  // --- add-persona form ------------------------------------------------------------------------
  const [draft, setDraft] = useState<AddPersonaDraft>({ handle: "", platform: "youtube" });
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const handleAdd = useCallback(() => {
    const handle = draft.handle.trim();
    if (!handle) {
      setAddError(t("misc.personas.form.handleRequired"));
      return;
    }
    setAdding(true);
    setAddError(null);
    personasApi
      .create({ handle, platform: draft.platform })
      .then(() => {
        setDraft((prev) => ({ ...prev, handle: "" }));
        reload();
      })
      .catch((err: unknown) => {
        setAddError(describePersonaActionError(err, t("misc.personas.error.addFailed")));
      })
      .finally(() => {
        setAdding(false);
      });
  }, [draft, reload, t]);

  // --- per-persona removal, keyed by slug --------------------------------------------------------
  const [deleting, setDeleting] = useState<Record<string, boolean>>({});
  const [deleteErrors, setDeleteErrors] = useState<Record<string, string | null>>({});
  // EXP-24: which persona a `ConfirmSheet` is currently asking about. Removal destroys the persona
  // and its ingested notes, so it confirms first -- `pages/data/UsersPanel.tsx`'s rule, applied to
  // the one action on this page that cannot be undone by clicking again.
  const [confirmingRemove, setConfirmingRemove] = useState<{ slug: string; name: string } | null>(null);

  const handleDelete = useCallback(
    (slug: string) => {
      setDeleting((prev) => ({ ...prev, [slug]: true }));
      setDeleteErrors((prev) => ({ ...prev, [slug]: null }));
      personasApi
        .remove(slug)
        .then(() => {
          reload();
        })
        .catch((err: unknown) => {
          setDeleteErrors((prev) => ({
            ...prev,
            [slug]: describePersonaActionError(err, t("misc.personas.error.removeFailed")),
          }));
        })
        .finally(() => {
          setDeleting((prev) => ({ ...prev, [slug]: false }));
        });
    },
    [reload, t],
  );

  // EXP-08: the watchlist's `personas` are backing *handles* on the wire. This page already holds
  // the one list that maps a handle to a readable name (`cards`), so it hands that map down rather
  // than making the panel fetch it again; an unmapped handle still renders verbatim.
  const personaNames = useMemo(() => {
    const out: Record<string, string> = {};
    for (const card of cards) out[card.persona.slug] = card.persona.display_name;
    return out;
  }, [cards]);

  // --- page-level: cross-persona influencer watchlist (Phase 6/7) ---------------------------------
  const [watchlistState, setWatchlistState] = useState<WatchlistState>({ phase: "loading" });
  const [watchlistAsOf, setWatchlistAsOf] = useState<string | null>(null);

  useWatchlistFetch(watchlistAsOf, setWatchlistState);

  // --- page-level: cross-persona macro regime consensus (Phase 6/7) -------------------------------
  const [regimeState, setRegimeState] = useState<RegimeState>({ phase: "loading" });

  useRegimeFetch(setRegimeState);

  // --- the backfill queue, folded in from the former `/backfill` page ------------------------------
  // In the URL rather than a `useState` so `/backfill` can redirect to `?panel=backfill` and land
  // with the panel already open -- that redirect is the only thing keeping every existing link and
  // bookmark to the old page working, and it can only work if the panel is addressable. `valid`
  // means a hand-edited or stale `?panel=` closes the panel rather than reaching anything.
  const [panel, setPanel] = useUrlState("panel", "", { valid: PANELS });
  const backfillOpen = panel === "backfill";

  return (
    <>
      <div className="personas-title-row">
        <h1>{t("misc.personas.title")}</h1>
        {/* The backfill queue is an operator action on this page's own data (it produces the notes
            these rows summarise), not a destination of its own -- so it is a button here rather than
            a fifth nav entry under Agent Desk. `aria-expanded` because this button controls a
            disclosure below it, not a navigation. */}
        <button
          type="button"
          className="personas-backfill-toggle"
          aria-expanded={backfillOpen}
          onClick={() => setPanel(backfillOpen ? "" : "backfill")}
        >
          {t("backfill.personasToggle")}
        </button>
      </div>
      <p className="subtitle">{t("misc.personas.subtitle")}</p>
      {/* One prominent page-level "not advice" marker, in the pill form docs/COPY-STYLE.md
          prescribes. It does not replace the per-panel caveats on the detail page -- those are
          contractual guardrails each persona component's docstring requires to always render
          (watchlist/regime `caveat`, PersonaAsk/PersonaCritique/PersonaBacktest framing) -- it
          states the framing once, unmissably, at the top of the list. */}
      <div className="personas-caveat">
        <StatusPill tone="warn" label={t("ui.pill.notAdvice")} />
      </div>

      {backfillOpen && (
        <PanelBoundary label={t("backfill.personasToggle")}>
          <Collapsible
            className="personas-backfill-panel"
            data-testid="personas-backfill-panel"
            title={<h2 className="section-heading">{t("backfill.title")}</h2>}
          >
            <BackfillSection />
          </Collapsible>
        </PanelBoundary>
      )}

      <PanelBoundary label={t("misc.panel.addPersona")}>
        <section className="panel">
          <h2>{t("misc.panel.addPersona")}</h2>
          <form
            className="persona-add-form filter-bar"
            onSubmit={(e) => {
              e.preventDefault();
              handleAdd();
            }}
          >
            <label>
              <span>{t("misc.personas.form.handle")}</span>
              <input
                value={draft.handle}
                onChange={(e) => setDraft((prev) => ({ ...prev, handle: e.target.value }))}
                placeholder="@creator-a"
                required
              />
            </label>
            <label>
              <span>{t("misc.personas.form.platform")}</span>
              <select
                value={draft.platform}
                onChange={(e) =>
                  setDraft((prev) => ({ ...prev, platform: e.target.value as Platform }))
                }
              >
                <option value="youtube">{t("misc.personas.form.platformYoutube")}</option>
                <option value="manual">{t("misc.personas.form.platformManual")}</option>
              </select>
            </label>
            <button type="submit" disabled={adding}>
              {adding ? t("misc.personas.form.adding") : t("misc.personas.form.submit")}
            </button>
          </form>
          {addError && (
            <div className="callout callout-danger persona-add-error" role="alert">
              {addError}
            </div>
          )}
        </section>
      </PanelBoundary>

      {/* NOT a `CardGrid`: `PersonaWatchlist`/`PersonaRegime` are each a self-contained `.panel`
          (own head, own loading/error states, and the watchlist owns an inner `ScrollRegion` of its
          own) rather than a `title`/`status`/body split a `Card` could take over -- forcing either
          into `Card`'s slots means dropping its own panel wrapper and heading first, which is a
          change to those two components, not to this page. `PersonaRegime.tsx` is out of this
          change's file list entirely and `PersonaWatchlist.tsx` is in it for the `/ticker` link
          sweep only, so neither is restructured here; see this change's own report for the
          follow-up this leaves open. This row keeps its original ragged-bottom grid. */}
      <div className="persona-consensus-row">
        <PanelBoundary label={t("personasPage.watchlistPanel")}>
          <PersonaWatchlist
            state={watchlistState}
            asOf={watchlistAsOf}
            onAsOfChange={setWatchlistAsOf}
            personaNames={personaNames}
          />
        </PanelBoundary>
        <PanelBoundary label={t("personasPage.regimePanel")}>
          <PersonaRegime state={regimeState} />
        </PanelBoundary>
      </div>

      {/* UX-04: this fetch runs for seconds on a cold cache, and a one-line "Loading personas…"
          collapsed the page to a single row that then snapped open to a full card grid. The
          skeleton draws that grid's silhouette instead, so the swap is a content change rather than
          a reflow, and `Skeleton`'s own `role="status"` announces the same sentence the bare
          placeholder used to render. */}
      {phase === "loading" && (
        <div className="persona-grid-skeleton" data-testid="personas-loading-skeleton">
          <Skeleton rows={3} variant="tiles" what={t("personasPage.skeleton.what")} />
        </div>
      )}

      {phase === "error" && (
        <div className="panel">
          <div className="placeholder">{message}</div>
        </div>
      )}

      {phase === "loaded" && cards.length === 0 && (
        <div className="panel">
          <div className="placeholder">{t("misc.personas.empty")}</div>
        </div>
      )}

      {phase === "loaded" && cards.length > 0 && (
        <CardGrid height="md" className="persona-grid">
          {cards.map((card) => {
            const slug = card.persona.slug;
            return (
              <PanelBoundary key={slug} label={card.persona.display_name}>
                <PersonaListRow
                  card={card}
                  deletePending={deleting[slug] ?? false}
                  deleteError={deleteErrors[slug] ?? null}
                  onDelete={() =>
                    setConfirmingRemove({ slug, name: card.persona.display_name })
                  }
                />
              </PanelBoundary>
            );
          })}
        </CardGrid>
      )}

      <ConfirmSheet
        open={confirmingRemove !== null}
        question={t("personasPage.removeConfirm.title", { name: confirmingRemove?.name ?? "" })}
        preview={t("personasPage.removeConfirm.body")}
        confirmLabel={t("personasPage.removeConfirm.confirm")}
        busy={confirmingRemove !== null && (deleting[confirmingRemove.slug] ?? false)}
        tone="bad"
        onConfirm={() => {
          if (confirmingRemove === null) return;
          handleDelete(confirmingRemove.slug);
          setConfirmingRemove(null);
        }}
        onCancel={() => setConfirmingRemove(null)}
      />
    </>
  );
}

/**
 * One followed influencer's compact summary: name, platform/handle, note count, freshness,
 * headline, theme/stance chips, and a link onward to `/personas/{slug}` for the full panel stack.
 *
 * Presentational only, same "fetches nothing" rule `PersonaCard.tsx` follows -- every value renders
 * straight from `card` (a `DigestCard`) plus the removal pending/error props this page owns. It
 * intentionally does not link its ticker mentions to `/symbol/{symbol}` the way `PersonaCard.tsx`'s
 * full card does: this whole row already carries one outbound link (to the persona's own detail
 * page), and nesting a second interactive link inside it would be both invalid markup and a genuine
 * "which link did I just click" trap. Ticker mentions render here as inert chips; the clickable
 * per-ticker view lives on the detail page's `PersonaProfile`/`PersonaCard`.
 *
 * Keeps the same product guardrails `PersonaCard.tsx` enforces for this same data (see that file's
 * own docstring): "their view", never a signal; `unclear` reads as "no clear stance"; a persona with
 * no notes is a valid empty state, not an error; `grounding.degraded` is always visible; non-empty
 * `warnings` are always rendered.
 */
function PersonaListRow({
  card,
  deletePending,
  deleteError,
  onDelete,
}: {
  card: DigestCard;
  deletePending: boolean;
  deleteError: string | null;
  onDelete: () => void;
}) {
  const { t } = useT();
  const persona = card.persona;
  const slug = persona.slug;
  const displayName = persona.display_name;
  const primarySource = persona.sources[0];
  const hasNotes = card.note_count > 0;

  return (
    <Card
      id={`persona-${slug}`}
      height="md"
      label={displayName}
      panelClassName="persona-list-card"
      className="persona-list-card-body"
      expandable
      title={
        <div>
          <h2 className="persona-list-card-name">{displayName}</h2>
          <p className="muted persona-list-card-handle">
            {primarySource
              ? `${primarySource.platform} · ${primarySource.handle}`
              : t("misc.personas.card.noSourceConfigured")}
          </p>
        </div>
      }
      status={
        <>
          <span className="badge">
            {t(card.note_count === 1 ? "misc.personas.card.noteCount_one" : "misc.personas.card.noteCount_other", {
              count: card.note_count,
            })}
          </span>{" "}
          <span className="muted persona-list-card-asof">
            {card.as_of
              ? t("misc.personas.card.updatedAge", { age: formatRelativeAge(card.as_of) })
              : t("misc.personas.card.noNotesYet")}
          </span>
        </>
      }
      footer={
        <>
          {deleteError && (
            <div className="callout callout-danger persona-list-card-delete-error" role="alert">
              {deleteError}
            </div>
          )}

          <div className="persona-list-card-actions">
            <Link
              to={`/personas/${encodeURIComponent(slug)}`}
              className="persona-list-card-detail-link"
              aria-label={t("misc.personas.list.viewDetailAria", { name: displayName })}
            >
              {t("misc.personas.list.viewDetail")}
            </Link>
            <button
              type="button"
              className="persona-card-remove"
              onClick={onDelete}
              disabled={deletePending}
            >
              {deletePending ? t("misc.personas.card.removing") : t("misc.personas.card.removeButton")}
            </button>
          </div>
        </>
      }
    >
      {card.grounding.degraded && (
        <div className="callout callout-warn persona-list-card-degraded" role="alert">
          <StatusPill tone="warn" label={t("ui.pill.unverified")} />{" "}
          <strong>{t("misc.personas.card.factCheckFailed")}</strong>{" "}
          {t("misc.personas.card.factCheckDetail", { name: displayName })}
        </div>
      )}

      {!hasNotes && (
        <p className="placeholder persona-list-card-empty">
          {t("misc.personas.card.noNotesEmpty", { name: displayName })}
        </p>
      )}

      {hasNotes && (
        <>
          {card.headline && (
            <p className="persona-list-card-headline">
              <span className="muted persona-list-card-headline-label">
                {t("misc.personas.card.recentTakeLabel")}
              </span>{" "}
              {card.headline}
            </p>
          )}

          {card.themes.length > 0 && (
            <ul className="persona-list-card-themes">
              {card.themes.map((theme, i) => (
                <li key={i}>{theme}</li>
              ))}
            </ul>
          )}

          {card.mentions.length > 0 && (
            <ul className="persona-list-card-tickers">
              {card.mentions.map((mention) => (
                <li key={mention.symbol} className="persona-list-card-ticker-chip">
                  <span className="position-symbol">{mention.symbol}</span>
                  <span className={`persona-ticker-stance persona-ticker-stance-${mention.stance}`}>
                    {stanceLabel(mention.stance)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {card.warnings.length > 0 && (
        <ul className="warning-list persona-list-card-warnings">
          {card.warnings.map((w, i) => (
            <li key={`${w.source}-${i}`}>
              <span className="kind">{w.source}</span> {w.reason}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------------------------
// Page-level cross-persona fetches (Phase 6/7) -- unchanged from the old monolithic page, just
// pulled into their own hooks so the component body above stays readable.
// ---------------------------------------------------------------------------------------------

function useWatchlistFetch(asOf: string | null, setState: Dispatch<SetStateAction<WatchlistState>>) {
  useEffect(() => {
    const controller = new AbortController();
    setState({ phase: "loading" });
    personasApi
      // `as_of` is genuinely optional on the wire -- omit the key for "latest" rather than send it
      // as an explicit `undefined` (`exactOptionalPropertyTypes`).
      .watchlist(asOf !== null ? { as_of: asOf } : {}, controller.signal)
      .then((watchlist) => {
        setState({ phase: "loaded", watchlist });
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setState({
          phase: "error",
          message: describePersonaActionError(err, "Could not load the influencer watchlist."),
        });
      });
    return () => controller.abort();
  }, [asOf, setState]);
}

function useRegimeFetch(setState: Dispatch<SetStateAction<RegimeState>>) {
  useEffect(() => {
    const controller = new AbortController();
    personasApi
      .regime(controller.signal)
      .then((consensus) => {
        setState({ phase: "loaded", consensus });
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setState({
          phase: "error",
          message: describePersonaActionError(err, "Could not load the regime consensus."),
        });
      });
    return () => controller.abort();
  }, [setState]);
}
