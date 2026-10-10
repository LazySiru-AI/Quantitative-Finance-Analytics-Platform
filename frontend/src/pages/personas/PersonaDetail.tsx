/**
 * /personas/:slug -- the full per-persona panel stack for ONE followed influencer.
 *
 * Split out of the old monolithic `Personas.tsx`, which mounted this same nine-panel stack
 * (`PersonaCard`, `PersonaProfile`, `PersonaScorecard`, `PersonaTimeline`, `PersonaBacktest`,
 * `PersonaAsk`, `PersonaStrategyCard`, `PersonaCritique`, `PersonaProfileDiff`) once *per persona*,
 * all at once, on a single page. With every followed persona's panels stacked together that page ran
 * roughly thirteen screens tall per persona and fired every persona's fetches on load. This route
 * renders exactly one persona's stack, fetched on demand when its own page is opened.
 *
 * **State shape.** Every `Record<slug, X>` map the old page kept collapses to a single `X` here --
 * there is only ever one slug in play on this route. The old page's per-card loop over `cards`
 * collapses to one fetch keyed on the route's own `slug` param. See `Personas.tsx`'s own docstring
 * for the fetch/poll rationale that still applies unchanged (job-registry ingest polling, the
 * Phase 2 profile/theses guard, `scorecard`'s 404 meaning "unknown persona" rather than an empty
 * state) -- only the keying changed, not the behaviour.
 *
 * **Finding the persona.** `usePersonas()` still owns the one canonical fetch of `GET
 * /api/personas/cards` (it always answers `200`); this page reads that same list and picks out the
 * `DigestCard` whose `persona.slug` matches the route param, rather than adding a second endpoint
 * for "one card by slug" that does not exist in `docs/AGENT-DESK-CONTRACT.md`. A slug with no
 * matching card -- a stale link, a typo, a persona removed since the link was shared -- renders the
 * not-found state below instead of indexing into `undefined`.
 *
 * **Deleting from here.** `PersonaCard`'s own remove button still works on this page (`onDelete`
 * below) -- unlike the list page's own separate, lighter-weight remove action, a successful delete
 * here navigates back to `/personas` afterwards, since there is nothing left on this page to show.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiRequestError } from "@/api/client";
import {
  describePersonaActionError,
  isIngestActive,
  personasApi,
  type ChatContext,
  type ChatLang,
  type ChatThread,
  type IngestJob,
  type IngestRequest,
  type PersonaProfile as Profile,
  type SavedStrategyDraft,
  type TickerThesis,
} from "@/api/personas";
import PanelBoundary from "@/components/PanelBoundary";
import PersonaBacktest, { type BacktestFetchState } from "@/components/PersonaBacktest";
import PersonaCard from "@/components/PersonaCard";
import PersonaChat, { type ChatViewState } from "@/components/PersonaChat";
import PersonaCritique, { type CritiqueState } from "@/components/PersonaCritique";
import PersonaProfile, { type ProfileFetchState } from "@/components/PersonaProfile";
import PersonaProfileDiff, { type ProfileDiffState } from "@/components/PersonaProfileDiff";
import PersonaScorecard, { type ScorecardFetchState } from "@/components/PersonaScorecard";
import PersonaStrategyCard, {
  type PromoteState,
  type StrategyCardState,
} from "@/components/PersonaStrategyCard";
import PersonaTimeline, { type TimelineFetchState } from "@/components/PersonaTimeline";
import StatusPill from "@/components/StatusPill";
import { usePersonas } from "@/hooks/usePersonas";
import { useT } from "@/i18n";

// Shared with `../Personas.tsx` -- every panel mounted below (`.persona-card`, `.persona-profile`,
// `.persona-scorecard`, the ingest panel, etc.) is styled from this one sheet, and this route is the
// only other place any of them render.
import "../Personas.css";

/** Matches the job-registry poll cadence `Personas.tsx` established for this app -- not tied to
 * anything server-side. */
const POLL_INTERVAL_MS = 2000;

/** The "← back to personas" link, reused in both the loaded header and the not-found state. */
function BackToPersonasLink() {
  const { t } = useT();
  return (
    <Link to="/personas" className="persona-detail-back-link">
      {t("misc.personas.detail.backLink")}
    </Link>
  );
}

export default function PersonaDetail() {
  const { t } = useT();
  const navigate = useNavigate();
  const { slug: rawSlug } = useParams<{ slug: string }>();
  const slug = rawSlug ?? "";

  const { cards, phase, message, reload } = usePersonas();
  const card = cards.find((c) => c.persona.slug === slug) ?? null;

  // --- ingest, for this slug only ----------------------------------------------------------------
  const [ingestJob, setIngestJob] = useState<IngestJob | null>(null);
  const [ingestStarting, setIngestStarting] = useState(false);
  const [ingestError, setIngestError] = useState<string | null>(null);

  // Read inside the poll interval so it always sees the latest job without needing to be a
  // dependency of the effect that owns the interval (which would tear it down on every tick).
  const ingestJobRef = useRef(ingestJob);
  useEffect(() => {
    ingestJobRef.current = ingestJob;
  }, [ingestJob]);

  const handleIngest = useCallback(
    (body: IngestRequest) => {
      setIngestStarting(true);
      setIngestError(null);
      personasApi
        .startIngest(slug, body)
        .then((job) => {
          setIngestJob(job);
        })
        .catch((err: unknown) => {
          setIngestError(describePersonaActionError(err, t("misc.personas.error.ingestFailed")));
        })
        .finally(() => {
          setIngestStarting(false);
        });
    },
    [slug, t],
  );

  const jobActive = ingestJob !== null && isIngestActive(ingestJob.state);

  useEffect(() => {
    if (!jobActive) return;
    const id = setInterval(() => {
      const job = ingestJobRef.current;
      if (!job || !isIngestActive(job.state)) return;
      personasApi
        .getIngestJob(slug, job.job_id)
        .then((updated) => {
          setIngestJob(updated);
          if (!isIngestActive(updated.state)) {
            // The job just settled -- refresh the card once so note_count/headline/themes stop
            // reading stale, without polling on its own timer.
            reload();
          }
        })
        .catch(() => {
          // A transient poll failure is not fatal -- the card keeps its last known job state and
          // the next tick tries again, rather than this page erroring out mid-ingest.
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
    // `jobActive` (not `ingestJob` itself) keys this effect so a job's own progress ticking upward
    // does not itself tear down and rebuild the interval -- only a new job starting or an existing
    // one settling changes it. Matches `Personas.tsx`'s own `activeKey` reasoning, collapsed to one
    // slug.
  }, [jobActive, slug, reload]);

  // --- consolidated profile + theses (Phase 2) ----------------------------------------------------
  const [profileState, setProfileState] = useState<ProfileFetchState>({ phase: "loading" });
  const [theses, setTheses] = useState<TickerThesis[]>([]);
  const [scorecardState, setScorecardState] = useState<ScorecardFetchState>({ phase: "loading" });
  const [consolidating, setConsolidating] = useState(false);
  const [consolidateError, setConsolidateError] = useState<string | null>(null);

  // --- timeline / backtest / strategy-card history (Phase 6/7) ------------------------------------
  const [timelineState, setTimelineState] = useState<TimelineFetchState>({ phase: "loading" });
  const [backtestState, setBacktestState] = useState<BacktestFetchState>({ phase: "loading" });
  const [strategyCardHistory, setStrategyCardHistory] = useState<SavedStrategyDraft[]>([]);

  // --- persona chat (Phase 9) -- the multi-turn successor to the old single-shot "ask" panel -------
  const [chatThreads, setChatThreads] = useState<ChatThread[]>([]);
  const [activeChatThread, setActiveChatThread] = useState<ChatThread | null>(null);
  const [chatContext, setChatContext] = useState<ChatContext | null>(null);
  const [chatTurnState, setChatTurnState] = useState<ChatViewState>({ phase: "idle" });

  // Read inside `handleSendChatTurn` below so that callback can stay memoized on `slug` alone
  // (matching `ingestJobRef`'s own reasoning above) rather than being rebuilt every time the active
  // thread changes.
  const activeChatThreadRef = useRef(activeChatThread);
  useEffect(() => {
    activeChatThreadRef.current = activeChatThread;
  }, [activeChatThread]);

  // Guards the initial profile/theses/scorecard/timeline/backtest/history fetch below so it fires
  // exactly once per slug this route mounts with -- not once per `reload()`. Reset when `slug`
  // itself changes (navigating from one persona's detail page straight to another's, e.g. via
  // browser back/forward) so the new slug's fetch is not skipped as "already fetched".
  const fetchedForSlugRef = useRef<string | null>(null);

  useEffect(() => {
    if (phase !== "loaded" || !card) return;
    if (fetchedForSlugRef.current === slug) return;
    fetchedForSlugRef.current = slug;

    setProfileState({ phase: "loading" });
    personasApi
      .getProfile(slug)
      .then((profile) => {
        setProfileState({ phase: "loaded", profile });
      })
      .catch((err: unknown) => {
        if (err instanceof ApiRequestError && err.status === 404) {
          setProfileState({ phase: "not_found" });
          return;
        }
        setProfileState({
          phase: "error",
          message: describePersonaActionError(err, t("personaProfile.detail.error.profileLoadFailed")),
        });
      });

    personasApi
      .theses(slug)
      .then((list) => {
        setTheses(list);
      })
      .catch(() => {
        // A transient failure here is not fatal -- the profile itself (fetched above) still
        // renders; theses simply stay empty until the next full page load retries them.
      });

    setScorecardState({ phase: "loading" });
    personasApi
      .scorecard(slug)
      .then((scorecard) => {
        setScorecardState({ phase: "loaded", scorecard });
      })
      .catch((err: unknown) => {
        // Unlike getProfile's 404 ("never consolidated"), scorecard's 404 means "unknown persona
        // slug" per the contract -- a genuine error here, not an empty state. See
        // @/components/PersonaScorecard's docstring.
        const errMessage =
          err instanceof ApiRequestError && err.status === 404
            ? t("personaProfile.detail.error.unknownPersona")
            : describePersonaActionError(err, t("personaProfile.detail.error.scorecardLoadFailed"));
        setScorecardState({ phase: "error", message: errMessage });
      });

    setTimelineState({ phase: "loading" });
    personasApi
      .timeline(slug)
      .then((timeline) => {
        setTimelineState({ phase: "loaded", timeline });
      })
      .catch((err: unknown) => {
        setTimelineState({
          phase: "error",
          message: describePersonaActionError(err, t("personaProfile.detail.error.timelineLoadFailed")),
        });
      });

    setBacktestState({ phase: "loading" });
    personasApi
      .backtest(slug)
      .then((backtest) => {
        setBacktestState({ phase: "loaded", backtest });
      })
      .catch((err: unknown) => {
        setBacktestState({
          phase: "error",
          message: describePersonaActionError(err, t("personaProfile.detail.error.backtestLoadFailed")),
        });
      });

    personasApi
      .strategyCards(slug)
      .then((list) => {
        setStrategyCardHistory(list);
      })
      .catch(() => {
        // A transient failure here is not fatal -- the strategy-card panel itself still lets the
        // persona draft a fresh card; prior history simply stays empty until the next full page
        // load retries it, matching how `theses` above handles its own transient fetch failure.
      });

    // Phase 9 -- persona chat's own thread list and stale-profile context, for this same slug.
    personasApi
      .chats(slug)
      .then((list) => {
        setChatThreads(list);
      })
      .catch(() => {
        // A transient failure here is not fatal -- the chat panel simply starts with an empty thread
        // list until the next full page load retries it, same tolerance `theses`/`strategyCards` above
        // apply to their own transient failures.
      });

    personasApi
      .chatContext(slug)
      .then((ctx) => {
        setChatContext(ctx);
      })
      .catch((err: unknown) => {
        // An unknown persona's chat-context 404 is already handled elsewhere on this route (the
        // digest-card lookup above renders the not-found state) -- here a 404 is tolerated the same
        // as any other transient failure: `context` stays `null`, which `PersonaChat` treats as "no
        // stale-profile note to show" rather than an error.
        if (err instanceof ApiRequestError) {
          setChatContext(null);
        }
      });
  }, [slug, phase, card, t]);

  const handleConsolidate = useCallback(() => {
    setConsolidating(true);
    setConsolidateError(null);
    personasApi
      .consolidate(slug)
      .then((profile: Profile) => {
        setProfileState({ phase: "loaded", profile });
        // A fresh consolidation can flip the persona's chat context from stale to current --
        // re-fetch it so `PersonaChat`'s stale-profile note clears without a full page reload.
        personasApi
          .chatContext(slug)
          .then((ctx) => setChatContext(ctx))
          .catch(() => {});
        return personasApi
          .theses(slug)
          .then((list) => setTheses(list))
          .catch(() => {});
      })
      .catch((err: unknown) => {
        setConsolidateError(
          describePersonaActionError(err, t("personaProfile.detail.error.consolidateFailed")),
        );
      })
      .finally(() => {
        setConsolidating(false);
      });
  }, [slug, t]);

  const handleSelectChatThread = useCallback(
    (threadId: string) => {
      personasApi
        .chat(slug, threadId)
        .then((full) => setActiveChatThread(full))
        .catch(() => {
          // A transient failure here is not fatal -- the previously active thread (if any) stays on
          // screen rather than being cleared on a blip.
        });
    },
    [slug],
  );

  const handleNewChatThread = useCallback(() => {
    personasApi
      .createChat(slug)
      .then((created) => {
        setChatThreads((prev) => [created, ...prev]);
        setActiveChatThread(created);
        setChatTurnState({ phase: "idle" });
      })
      .catch((err: unknown) => {
        setChatTurnState({
          phase: "error",
          message: describePersonaActionError(err, t("personaProfile.detail.error.newChatFailed")),
        });
      });
  }, [slug, t]);

  const handleDeleteChatThread = useCallback(
    (threadId: string) => {
      personasApi
        .deleteChat(slug, threadId)
        .then(() => {
          setChatThreads((prev) => prev.filter((thread) => thread.thread_id !== threadId));
          setActiveChatThread((prev) => (prev?.thread_id === threadId ? null : prev));
        })
        .catch((err: unknown) => {
          setChatTurnState({
            phase: "error",
            message: describePersonaActionError(err, t("personaProfile.detail.error.deleteChatFailed")),
          });
        });
    },
    [slug, t],
  );

  const handleSendChatTurn = useCallback(
    (question: string, symbol: string | undefined, chatLang: ChatLang) => {
      setChatTurnState({ phase: "pending" });

      // Needs an active thread -- start one first when the reader sends before ever picking/creating
      // one (e.g. straight from a suggested-question chip on a brand-new persona).
      const ensureThread: Promise<ChatThread> =
        activeChatThreadRef.current !== null
          ? Promise.resolve(activeChatThreadRef.current)
          : personasApi.createChat(slug).then((created) => {
              setChatThreads((prev) => [created, ...prev]);
              setActiveChatThread(created);
              return created;
            });

      ensureThread
        .then((thread) =>
          personasApi
            // `symbol` is genuinely optional on the wire (`exactOptionalPropertyTypes` forbids sending
            // it as an explicit `undefined`) -- omit the key entirely rather than pass one, same rule
            // the old `handleAsk` followed.
            .sendTurn(slug, thread.thread_id, {
              question,
              ...(symbol ? { symbol } : {}),
              lang: chatLang,
            })
            .then((newTurn) => {
              setActiveChatThread((prev) => {
                const base = prev && prev.thread_id === thread.thread_id ? prev : thread;
                return { ...base, turns: [...base.turns, newTurn], turn_count: base.turn_count + 1 };
              });
              setChatThreads((prev) =>
                prev.map((t) =>
                  t.thread_id === thread.thread_id
                    ? { ...t, turn_count: t.turn_count + 1, updated_at: newTurn.asked_at }
                    : t,
                ),
              );
              setChatTurnState({ phase: "idle" });
            }),
        )
        .catch((err: unknown) => {
          setChatTurnState({
            phase: "error",
            message: describePersonaActionError(err, t("personaProfile.detail.error.chatTurnFailed")),
          });
        });
    },
    [slug, t],
  );

  // --- strategy-card drafting (Phase 7c) ------------------------------------------------------------
  const [strategyCardState, setStrategyCardState] = useState<StrategyCardState>({ phase: "idle" });

  const handleDraftStrategy = useCallback(() => {
    setStrategyCardState({ phase: "pending" });
    personasApi
      .strategyCard(slug)
      .then((draft) => {
        // `mapped: false` is still a successful draft (see `PersonaStrategyCard.tsx`'s own
        // docstring, rule 1) -- only a thrown error below is `{ phase: "error" }`.
        setStrategyCardState({ phase: "drafted", draft });
      })
      .catch((err: unknown) => {
        setStrategyCardState({
          phase: "error",
          message: describePersonaActionError(
            err,
            t("personaProfile.detail.error.draftStrategyFailed"),
          ),
        });
      });
  }, [slug, t]);

  // --- promote a drafted card onto the competition library shelf (Phase 3.4) ------------------------
  const [promoteState, setPromoteState] = useState<PromoteState>({ phase: "idle" });

  const handlePromoteStrategy = useCallback(
    (version: number) => {
      setPromoteState({ phase: "pending" });
      personasApi
        .promoteStrategyCard(slug, version)
        .then((card) => setPromoteState({ phase: "done", agentId: card.agent_id }))
        .catch((err: unknown) => {
          // A 409 is idempotent -- the card is already on the shelf -- not a failure to shout about.
          if (err instanceof ApiRequestError && err.status === 409) {
            setPromoteState({ phase: "exists" });
            return;
          }
          setPromoteState({
            phase: "error",
            message: describePersonaActionError(err, t("personaProfile.detail.error.promoteFailed")),
          });
        });
    },
    [slug, t],
  );

  // --- critique of the persona's own currently-drafted strategy card --------------------------------
  const [critiqueState, setCritiqueState] = useState<CritiqueState>({ phase: "idle" });

  /** Whether this persona currently has a drafted, mapped card available to critique -- gates both
   * the button (`PersonaCritique`'s own `canCritique` prop) and `handleCritique` below, which reads
   * the exact same drafted card rather than trusting the caller. */
  const canCritique =
    strategyCardState.phase === "drafted" && strategyCardState.draft.card != null;

  const handleCritique = useCallback(() => {
    if (strategyCardState.phase !== "drafted" || strategyCardState.draft.card == null) return;
    const cardDraft = strategyCardState.draft.card;
    setCritiqueState({ phase: "pending" });
    personasApi
      .critique(slug, { card: cardDraft })
      .then((critique) => {
        setCritiqueState({ phase: "done", critique });
      })
      .catch((err: unknown) => {
        setCritiqueState({
          phase: "error",
          message: describePersonaActionError(err, t("personaProfile.detail.error.critiqueFailed")),
        });
      });
  }, [slug, strategyCardState, t]);

  // --- profile-version diff (Phase 6/7) -------------------------------------------------------------
  const [diffState, setDiffState] = useState<ProfileDiffState>({ phase: "idle" });
  const [diffFrom, setDiffFrom] = useState<number | null>(null);
  const [diffTo, setDiffTo] = useState<number | null>(null);

  /** `[1..version]` once this persona's profile has loaded, `[]` otherwise -- `PersonaProfileDiff`
   * has nothing to compare before the persona has even been consolidated once. */
  const versions: number[] =
    profileState.phase === "loaded"
      ? Array.from({ length: profileState.profile.version }, (_, i) => i + 1)
      : [];

  const handleCompareDiff = useCallback(() => {
    if (diffFrom === null || diffTo === null) return;
    setDiffState({ phase: "loading" });
    personasApi
      .profileDiff(slug, { from: diffFrom, to: diffTo })
      .then((diff) => {
        setDiffState({ phase: "loaded", diff });
      })
      .catch((err: unknown) => {
        setDiffState({
          phase: "error",
          message: describePersonaActionError(err, t("personaProfile.detail.error.profileDiffFailed")),
        });
      });
  }, [slug, diffFrom, diffTo, t]);

  // --- removal -- deleting from this page navigates back, since nothing is left to show -----------
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDelete = useCallback(() => {
    setDeleting(true);
    setDeleteError(null);
    personasApi
      .remove(slug)
      .then(() => {
        navigate("/personas");
      })
      .catch((err: unknown) => {
        setDeleteError(describePersonaActionError(err, t("misc.personas.error.removeFailed")));
      })
      .finally(() => {
        setDeleting(false);
      });
  }, [slug, navigate, t]);

  if (phase === "loading") {
    return (
      <>
        <BackToPersonasLink />
        <div className="panel">
          <div className="placeholder">{t("misc.personas.loading")}</div>
        </div>
      </>
    );
  }

  if (phase === "error") {
    return (
      <>
        <BackToPersonasLink />
        <div className="panel">
          <div className="placeholder">{message}</div>
        </div>
      </>
    );
  }

  if (!card) {
    return (
      <div className="panel persona-detail-not-found">
        <h1>{t("misc.personas.detail.notFoundTitle")}</h1>
        <p className="placeholder">{t("misc.personas.detail.notFoundBody", { slug })}</p>
        <BackToPersonasLink />
      </div>
    );
  }

  const displayName = card.persona.display_name;

  return (
    <>
      <BackToPersonasLink />
      {/* A11Y-02. This route used to render no `<h1>` at all -- the reasoning was that `PersonaCard`
          below already renders the persona's name as its own `<h2>`, so a second element with the
          same text was redundant. It is not: a page with no level-1 heading gives a screen-reader
          user no "what page am I on" landmark to jump to, and every heading below it hangs off
          nothing. The name is the page, so the name is the `<h1>`; the card's `<h2>` stays as that
          panel's own heading, one level below, which is the correct outline rather than a duplicate.

          UX-14: the panels below state BULLISH/BEARISH per ticker. The pill sits beside the name,
          above every one of them, in the form docs/COPY-STYLE.md rule 6 prescribes for a framing a
          reader is worse off for not seeing -- the same marker `/personas` renders over its list. */}
      <div className="persona-detail-head">
        <h1 className="persona-detail-title">{displayName}</h1>
        <StatusPill tone="warn" label={t("ui.pill.notAdvice")} />
      </div>
      <PanelBoundary label={displayName}>
        <>
          <PersonaCard
            card={card}
            ingestJob={ingestJob}
            ingestPending={ingestStarting}
            ingestError={ingestError}
            onIngest={handleIngest}
            deletePending={deleting}
            deleteError={deleteError}
            onDelete={handleDelete}
          />
          <PersonaProfile
            displayName={displayName}
            currentNoteCount={card.note_count}
            state={profileState}
            theses={theses}
            consolidatePending={consolidating}
            consolidateError={consolidateError}
            onConsolidate={handleConsolidate}
          />
          <PersonaScorecard displayName={displayName} state={scorecardState} />
          <PersonaTimeline displayName={displayName} state={timelineState} />
          <PersonaBacktest displayName={displayName} state={backtestState} />
          <PersonaChat
            displayName={displayName}
            threads={chatThreads}
            activeThread={activeChatThread}
            context={chatContext}
            turnState={chatTurnState}
            consolidating={consolidating}
            onSelectThread={handleSelectChatThread}
            onNewThread={handleNewChatThread}
            onDeleteThread={handleDeleteChatThread}
            onSend={handleSendChatTurn}
            onConsolidate={handleConsolidate}
          />
          <PersonaStrategyCard
            displayName={displayName}
            state={strategyCardState}
            history={strategyCardHistory}
            onDraft={handleDraftStrategy}
            onPromote={handlePromoteStrategy}
            promoteState={promoteState}
          />
          <PersonaCritique
            displayName={displayName}
            state={critiqueState}
            canCritique={canCritique}
            onCritique={handleCritique}
          />
          <PersonaProfileDiff
            state={diffState}
            versions={versions}
            from={diffFrom}
            to={diffTo}
            onFromChange={setDiffFrom}
            onToChange={setDiffTo}
            onCompare={handleCompareDiff}
          />
        </>
      </PanelBoundary>
    </>
  );
}
