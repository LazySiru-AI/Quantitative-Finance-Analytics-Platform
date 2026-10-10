/**
 * Strategy Lab landing -- the section rail's first stop now, not `/competition`.
 *
 * `nav.ts` puts this route first in the `strategy` section's `items`, which is what the sidebar
 * links a click on "Strategy Lab" to (see `App.tsx`'s `Sidebar`, which always links to
 * `section.items[0].to`). Before this page existed, that click landed cold on the Competition
 * leaderboard with no framing at all -- a reader had to already know the lab's five pages fit
 * together as one pipeline, and had to already know the programme's headline result, before either
 * page made sense.
 *
 * Two independent, cheap fetches back this page (`rulesApi.catalog`, `competitionApi.rounds`), each
 * with its own phase -- one failing must never blank the other, and both degrade to an em dash
 * rather than a spinner that never resolves or a `0` that reads as a real count of zero.
 *
 * The verdict line is quoted, not summarised, from `docs/reports/EVERYTHING-INVESTIGATED-2026-09-01.md`
 * (see `MEMORY.md`'s "Complete research report" entry) -- the one finding a reader must not be able
 * to miss on the way into five pages that could otherwise read as "here is an edge, go find it".
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { competitionApi } from "@/api/competition";
import { rulesApi } from "@/api/rules";
import { useT } from "@/i18n";
import { sectionLabelKey } from "@/nav";
import StatusPill from "@/components/StatusPill";
import Term from "@/components/Term";

import "./StrategyLanding.css";

type Phase = "loading" | "loaded" | "error";

/** `rulesApi.catalog()` takes no `AbortSignal` (see `api/rules.ts`) -- the `cancelled` flag is what
 *  actually guards a state update after unmount, mirroring `pages/Rules.tsx`'s own fetch. */
function useRuleCount(): { count: number | null; phase: Phase } {
  const [count, setCount] = useState<number | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");

  useEffect(() => {
    let cancelled = false;
    rulesApi
      .catalog()
      .then((rules) => {
        if (cancelled) return;
        setCount(rules.length);
        setPhase("loaded");
      })
      .catch((_e: unknown) => {
        if (cancelled) return;
        setCount(null);
        setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { count, phase };
}

function useRoundCount(): { count: number | null; phase: Phase } {
  const [count, setCount] = useState<number | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");

  useEffect(() => {
    const controller = new AbortController();
    competitionApi
      .rounds(controller.signal)
      .then((response) => {
        setCount(response.rounds.length);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setCount(null);
        setPhase("error");
      });
    return () => controller.abort();
  }, []);

  return { count, phase };
}

/** A count tile that degrades to an em dash while loading or on failure, never to a bare `0` that
 *  would read as a measured zero. */
function CountTile({ label, count, phase }: { label: string; count: number | null; phase: Phase }) {
  return (
    <div className="tile sl-count-tile">
      <span className="label">{label}</span>
      <span className="value value-emphasize">{phase === "loaded" ? count : "—"}</span>
    </div>
  );
}

const FUNNEL_KEYS = [
  "landing.strategy.funnel.rules",
  "landing.strategy.funnel.evidence",
  "landing.strategy.funnel.competition",
  "landing.strategy.funnel.paperDesk",
] as const;

export default function StrategyLanding() {
  const { t: translate } = useT();
  const rules = useRuleCount();
  const rounds = useRoundCount();

  return (
    <div className="sl-page">
      <h1>{translate(sectionLabelKey("strategy"))}</h1>
      <p className="subtitle">{translate("landing.strategy.subtitle")}</p>

      {/* The verdict sentence turns entirely on "out-of-sample", and this page is the first place a
          reader meets the phrase -- it is the standard everything downstream is judged against. The
          term rides beside the pill rather than inside the sentence: `landing.strategy.verdict` is a
          single catalog string with no slot to hang a node on, and splitting a translated sentence
          around a `<Term>` at the call site is exactly the word-order decision `Trans` exists to
          keep out of English's hands. */}
      <section className="panel sl-verdict">
        <StatusPill tone="bad" label={translate("landing.strategy.verdictPill")} />
        <Term k="outOfSample" data-testid="sl-verdict-term" />
        <p className="sl-verdict-text">{translate("landing.strategy.verdict")}</p>
      </section>

      <section className="panel">
        <h2>{translate("landing.strategy.funnel.heading")}</h2>
        <div className="sl-funnel" role="list">
          {FUNNEL_KEYS.map((key, i) => (
            <span className="sl-funnel-step" role="listitem" key={key}>
              {i > 0 && (
                <span className="sl-funnel-arrow" aria-hidden="true">
                  →
                </span>
              )}
              {translate(key)}
            </span>
          ))}
        </div>

        <div className="tile-grid sl-counts">
          <CountTile label={translate("landing.strategy.counts.rules")} count={rules.count} phase={rules.phase} />
          <CountTile
            label={translate("landing.strategy.counts.rounds")}
            count={rounds.count}
            phase={rounds.phase}
          />
        </div>
      </section>

      <section className="panel">
        <h2>{translate("landing.strategy.tryThis.heading")}</h2>
        <div className="sl-cards">
          <Link to="/evidence" className="sl-card">
            <span className="sl-card-title">{translate("landing.strategy.card.testRule.title")}</span>
            <span className="sl-card-blurb">{translate("landing.strategy.card.testRule.blurb")}</span>
          </Link>
          <Link to="/competition" className="sl-card">
            <span className="sl-card-title">{translate("landing.strategy.card.lastRound.title")}</span>
            <span className="sl-card-blurb">{translate("landing.strategy.card.lastRound.blurb")}</span>
          </Link>
          <Link to="/competition" className="sl-card">
            <span className="sl-card-title">{translate("landing.strategy.card.promotedCard.title")}</span>
            <span className="sl-card-blurb">{translate("landing.strategy.card.promotedCard.blurb")}</span>
          </Link>
        </div>
      </section>
    </div>
  );
}

// Re-exported for the page's own test, which asserts the funnel renders every step in order
// without duplicating the key list.
export { FUNNEL_KEYS as STRATEGY_FUNNEL_KEYS };
