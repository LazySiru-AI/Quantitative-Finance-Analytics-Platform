/**
 * The paper-desk review queue -- two human decisions, not one.
 *
 * **Why a person has to click here at all.** The loop used to seat a promoted card on the paper desk
 * itself, gated only by `LoopConfig.seat_on_paper_desk` -- which is a property of the whole run,
 * chosen before any candidate existed, and so was never a judgement about any particular card. Left
 * running, it seated 25 cards (18 roth, 7 trading) that nobody had looked at. Clearing the promotion
 * gate is a statistical fact, not an endorsement: it says a card's median excess beat a measured noise
 * floor twice on differing window sets, and `EVOLUTION-LOOP.md` section 5 predicts outright that a
 * searcher proposing without limit will produce cards that do exactly that by luck.
 *
 * **Why this is two decisions instead of one.** The old single "approve" button conflated "this is
 * worth keeping and naming" with "put real simulated dollars behind it." A card now moves
 * `pending` -&gt; `shelved` -&gt; `seated` (see `SeatStatus` in `api/evolution.ts`), and only the
 * second, separate `seat` decision ever touches `roster_overlay.json`. Rejecting or retiring a card
 * is exactly as final as seating one -- the loop will not re-file a rejected genome even if it clears
 * the gate again -- so the action labels below never say "approve": at stage 1 there is nothing to
 * approve of yet, only something worth keeping around to look at.
 *
 * **A card must be readable before it is decidable.** The old queue showed a hash
 * (`g1859-fd7c2c196f35`) and a bare "median excess 24.65" with nothing describing what the strategy
 * traded or what the number meant. Every row now leads with a server-composed `headline` and a
 * subordinate `short_id` chip and a one-line summary of the universe, with the full case -- what it
 * trades, why it exists, how its numbers compare to the field, and what could be wrong with it -- one
 * click away in `CandidateDossier`.
 *
 * **The headline is already composed by the server, from the parsed rule, never from a self-declared
 * label (settled 2026-08-26).** `PendingSeat.headline` and `Dossier.headline` (`api/evolution.ts`) are
 * both server-composed and guaranteed byte-identical for the same genome -- the backend has its own
 * test asserting exactly that -- so `CandidateRow` below renders them directly rather than recomposing
 * anything client-side. `candidateName.ts`'s `headline()`/`shortId()` are used only as the last-resort
 * fallback when neither is available (see that module's own docstring). An earlier version of this
 * component *did* recompose a headline client-side from a `rule_summary` field; that field never
 * existed on the wire, was this workstream's own guess made in parallel against a prose spec before
 * the backend contract settled, and has been removed along with the guess.
 *
 * **Decided rows stay on screen, greyed, rather than disappearing.** The question a reader has later
 * is not "what is pending now" but "was this card considered, and what was decided" -- a queue that
 * hides its own history cannot answer it. It also makes a rejection or a retirement visible as a
 * decision rather than as a card that silently never appeared.
 *
 * A `409` from any decision route means somebody (or something) already answered that request, or the
 * request is not in a state the transition is legal from -- the backend's own message names the
 * current state and what is legal from it, and that exact sentence is what gets rendered, followed by
 * a re-read, rather than a generic failure or a made-up explanation.
 *
 * **The dossier toggle is a plain `<button aria-expanded>`, not a native `<details>/<summary>`
 * (2026-08-26).** jsdom does not implement the browser's native click-to-toggle behaviour for
 * `<details>` (clicking a `<summary>` in a test does not open it or fire `toggle`), so the first
 * version of this row -- built on `<details>` -- was untestable by anything that drives it with a
 * plain `.click()`, which is exactly how a reviewer's mouse and `liveData.test.tsx` both operate. A
 * controlled button + `hidden` panel behaves identically for a person (click to open, click to close,
 * the dossier fetches once and stays mounted so re-opening never re-fetches) and needs no jsdom feature
 * that does not exist.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiRequestError } from "@/api/client";
import { formatSignedPctFraction } from "@/api/competition";
import { evolutionApi, purposeLabel, type Dossier, type PendingSeat, type SeatStatus } from "@/api/evolution";
import { ScrollRegion } from "@/components/ScrollPanel";
import Skeleton from "@/components/Skeleton";
import { useT, type MessageKey } from "@/i18n";
import CandidateDossier from "@/pages/competition/CandidateDossier";
import { headline, shortId } from "@/pages/competition/candidateName";

type DecisionAction = "shelve" | "reject" | "seat" | "retire";

interface RowAction {
  labelKey: MessageKey;
  action: DecisionAction;
  kind: "primary" | "secondary";
}

/** Display label for a raw `SeatStatus` wire value -- never render the enum value itself, per the
 * house rule on `origin_kind` in `CandidateDossier.tsx`'s module docstring. */
const SEAT_STATUS_LABEL_KEYS: Record<SeatStatus, MessageKey> = {
  pending: "competitionRounds.pendingSeats.status.pending",
  shelved: "competitionRounds.pendingSeats.status.shelved",
  seated: "competitionRounds.pendingSeats.status.seated",
  rejected: "competitionRounds.pendingSeats.status.rejected",
  retired: "competitionRounds.pendingSeats.status.retired",
};

/**
 * A `409` body is the raw sentence the backend wrote (`"g1859-... is 'seated'; only 'pending' may be
 * shelved or rejected"`), but FastAPI wraps it as `{"detail": "..."}` -- this unwraps that envelope
 * when present so the rendered notice is the sentence itself, not a JSON fragment. Falls back to the
 * raw body verbatim if it does not parse as `{"detail": string}`, so an unexpected shape still shows
 * *something* rather than nothing.
 */
function messageFor409(err: ApiRequestError): string {
  try {
    const parsed: unknown = JSON.parse(err.message);
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      "detail" in parsed &&
      typeof (parsed as { detail: unknown }).detail === "string"
    ) {
      return (parsed as { detail: string }).detail;
    }
  } catch {
    // Not JSON -- the raw body already is the sentence.
  }
  return err.message;
}

/**
 * One candidate row, reused for both the pending queue and the review shelf -- the two groups differ
 * only in which two actions they offer and what blurb sits above them, not in how a single card reads.
 * `dossier` is `undefined` until this row's `CandidateDossier` has loaded at least once; until then the
 * headline/short_id fall back to the list endpoint's own `seat.headline`/`seat.short_id`, and only then
 * to what `candidateName.ts` can compose from nothing at all.
 */
function CandidateRow({
  seat,
  dossier,
  expanded,
  busy,
  actions,
  onToggle,
  onDecide,
  onDossierLoaded,
}: {
  seat: PendingSeat;
  dossier: Dossier | undefined;
  expanded: boolean;
  busy: boolean;
  actions: RowAction[];
  onToggle: () => void;
  onDecide: (action: DecisionAction) => void;
  onDossierLoaded: (dossier: Dossier) => void;
}) {
  const { t } = useT();
  const [isOpen, setIsOpen] = useState(false);

  // Priority, most authoritative first -- see the module docstring on why this is no longer a
  // client-side recomposition:
  //  1. A loaded dossier's own `headline`/`short_id` (guaranteed byte-identical to the list row's).
  //  2. The list endpoint's server-composed `seat.headline`/`seat.short_id`.
  //  3. The honest, purpose-only placeholder -- only reachable if neither the list row nor the
  //     dossier ever supplies one.
  // `||`, not `??`: `headline`/`short_id` are typed as always-present strings now (see PendingSeat's
  // docstring in api/evolution.ts), so an absent value can only ever show up at runtime as `""` on a
  // degraded payload, not `null`/`undefined` -- `??` would let a blank string through as the row's
  // name instead of falling through to the placeholder.
  const headlineText =
    dossier?.headline || seat.headline || headline({ ruleSummary: null, tickers: [], purpose: seat.purpose });
  const shortIdText = dossier?.short_id || seat.short_id || shortId(seat.genome_id);
  const summaryText = dossier
    ? dossier.what_it_does.universe_note
    : t("competitionRounds.pendingSeats.summaryPlaceholder");

  const handleToggleClick = () => {
    const next = !isOpen;
    setIsOpen(next);
    if (next) onToggle();
  };

  return (
    <article className="comp-review-row" data-testid={`candidate-row-${seat.status}`}>
      <div className="comp-review-row-head">
        <div className="comp-review-row-name">
          <span className="comp-review-headline">{headlineText}</span>
          <span className="comp-review-short-id">{shortIdText}</span>
        </div>
        <span className="badge">{purposeLabel(seat.purpose)}</span>
      </div>
      <p className="comp-review-summary">{summaryText}</p>
      <div className="comp-review-actions">
        {actions.map((a) => (
          <button
            key={a.action}
            type="button"
            className={a.kind === "primary" ? "btn" : "btn btn-secondary"}
            disabled={busy}
            onClick={() => onDecide(a.action)}
          >
            {busy ? t("competitionRounds.pendingSeats.working") : t(a.labelKey)}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="comp-review-dossier-toggle"
        aria-expanded={isOpen}
        onClick={handleToggleClick}
      >
        {isOpen ? t("competitionRounds.pendingSeats.hideDossier") : t("competitionRounds.pendingSeats.fullDossier")}
      </button>
      {expanded && (
        <div className="comp-review-dossier-panel" hidden={!isOpen}>
          <CandidateDossier genomeId={seat.genome_id} onLoaded={onDossierLoaded} />
        </div>
      )}
    </article>
  );
}

export default function PendingSeatsPanel() {
  const { t } = useT();
  const [requests, setRequests] = useState<PendingSeat[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dossiers, setDossiers] = useState<Record<string, Dossier>>({});
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const load = useCallback((signal?: AbortSignal) => {
    return evolutionApi
      .pendingSeats(signal)
      .then((res) => {
        setRequests(res.requests);
        setError(null);
      })
      .catch((err: unknown) => {
        if (signal?.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const decide = useCallback(
    async (genomeId: string, action: DecisionAction) => {
      setBusy(genomeId);
      setNotice(null);
      try {
        if (action === "shelve") await evolutionApi.shelveSeat(genomeId);
        else if (action === "reject") await evolutionApi.rejectSeat(genomeId);
        else if (action === "seat") await evolutionApi.seatCandidate(genomeId);
        else await evolutionApi.retireSeat(genomeId);
        await load();
      } catch (err: unknown) {
        if (err instanceof ApiRequestError && err.status === 409) {
          // Somebody already answered this one, or it is not in a state this transition is legal
          // from -- the backend's own sentence names both. Re-read rather than leaving the screen
          // disagreeing with the server about this card's stage.
          setNotice(messageFor409(err));
          await load();
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        setBusy(null);
      }
    },
    [load],
  );

  const handleDossierLoaded = useCallback((dossier: Dossier) => {
    setDossiers((prev) => ({ ...prev, [dossier.genome_id]: dossier }));
  }, []);

  const handleToggle = useCallback((genomeId: string) => {
    setExpandedIds((prev) => {
      if (prev.has(genomeId)) return prev;
      const next = new Set(prev);
      next.add(genomeId);
      return next;
    });
  }, []);

  const pending = (requests ?? []).filter((r) => r.status === "pending");
  const shelved = (requests ?? []).filter((r) => r.status === "shelved");
  const decided = (requests ?? []).filter(
    (r) => r.status === "seated" || r.status === "rejected" || r.status === "retired",
  );

  return (
    <section className="comp-review" aria-labelledby="comp-review-heading">
      <h3 className="comp-loop-subheading" id="comp-review-heading">
        {t("competitionRounds.pendingSeats.heading")}
      </h3>

      {error && (
        <p className="callout callout-warn comp-review-error">
          {t("competitionRounds.pendingSeats.loadError", { error })}
        </p>
      )}
      {notice && <p className="callout callout-warn comp-review-notice">{notice}</p>}
      {/* The one bare "Loading…" line left on this page. It stood where three grouped candidate
          lists are about to render, so it collapsed the whole review queue to a single line and
          announced nothing to a screen reader; `Skeleton` draws the shape and says what is coming. */}
      {requests === null && !error && (
        <Skeleton variant="rows" rows={3} what={t("competition.pendingSeats.skeletonWhat")} />
      )}

      {/* --- Waiting for review ---------------------------------------------------------------- */}
      <div className="comp-review-group" data-testid="review-group-pending">
        <h4 className="comp-review-group-heading">{t("competitionRounds.pendingSeats.waitingHeading")}</h4>
        <p className="comp-review-group-blurb">{t("competitionRounds.pendingSeats.waitingBlurb")}</p>
        {requests !== null && pending.length === 0 && (
          <p className="comp-review-empty">{t("competitionRounds.pendingSeats.noneWaiting")}</p>
        )}
        {pending.length > 0 && (
          <ScrollRegion size="md" label={t("competitionRounds.pendingSeats.waitingHeading")}>
            {pending.map((r) => (
              <CandidateRow
                key={r.genome_id}
                seat={r}
                dossier={dossiers[r.genome_id]}
                expanded={expandedIds.has(r.genome_id)}
                busy={busy === r.genome_id}
                actions={[
                  {
                    labelKey: "competitionRounds.pendingSeats.action.keepForReview",
                    action: "shelve",
                    kind: "primary",
                  },
                  { labelKey: "competitionRounds.pendingSeats.action.decline", action: "reject", kind: "secondary" },
                ]}
                onToggle={() => handleToggle(r.genome_id)}
                onDecide={(action) => void decide(r.genome_id, action)}
                onDossierLoaded={handleDossierLoaded}
              />
            ))}
          </ScrollRegion>
        )}
      </div>

      {/* --- Review shelf ------------------------------------------------------------------------ */}
      <div className="comp-review-group" data-testid="review-group-shelved">
        <h4 className="comp-review-group-heading">{t("competitionRounds.pendingSeats.shelfHeading")}</h4>
        <p className="comp-review-group-blurb">{t("competitionRounds.pendingSeats.shelfBlurb")}</p>
        {requests !== null && shelved.length === 0 && (
          <p className="comp-review-empty">{t("competitionRounds.pendingSeats.shelfEmpty")}</p>
        )}
        {shelved.length > 0 && (
          <ScrollRegion size="md" label={t("competitionRounds.pendingSeats.shelfHeading")}>
            {shelved.map((r) => (
              <CandidateRow
                key={r.genome_id}
                seat={r}
                dossier={dossiers[r.genome_id]}
                expanded={expandedIds.has(r.genome_id)}
                busy={busy === r.genome_id}
                actions={[
                  { labelKey: "competitionRounds.action.seatOnPaperDesk", action: "seat", kind: "primary" },
                  { labelKey: "competitionRounds.action.retire", action: "retire", kind: "secondary" },
                ]}
                onToggle={() => handleToggle(r.genome_id)}
                onDecide={(action) => void decide(r.genome_id, action)}
                onDossierLoaded={handleDossierLoaded}
              />
            ))}
          </ScrollRegion>
        )}
      </div>

      {/* --- Decided -- greyed, collapsed, never removed ----------------------------------------- */}
      {decided.length > 0 && (
        <details className="comp-review-decided">
          <summary>{t("competitionRounds.pendingSeats.alreadyDecided", { count: decided.length })}</summary>
          <ScrollRegion
            size="md"
            label={t("competitionRounds.pendingSeats.alreadyDecided", { count: decided.length })}
          >
            <ul>
              {decided.map((r) => (
                <li key={r.genome_id} data-testid="decided-candidate">
                  <span className="comp-card-name">{shortId(r.genome_id)}</span>{" "}
                  <span className={`badge comp-review-status-${r.status}`}>
                    {t(SEAT_STATUS_LABEL_KEYS[r.status])}
                  </span>{" "}
                  <span className="comp-review-muted">
                    {purposeLabel(r.purpose)} &middot;{" "}
                    {t("competitionRounds.pendingSeats.selectionMedian", {
                      value: formatSignedPctFraction(r.median_excess),
                    })}
                    {r.decided_note ? ` · ${r.decided_note}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </ScrollRegion>
        </details>
      )}
    </section>
  );
}
