/**
 * Every message in the application, assembled from one shard per area.
 *
 * **The folder split is the point.** Extracting ~1,500 strings out of 120 files is work that fans
 * out cleanly by page -- but only if no two people editing different pages have to edit the same
 * module. One `en.ts` would be a merge conflict on every commit; a folder of shards is not.
 *
 * **Key convention:** `<area>.<thing>.<detail>`, lower camel within a segment, where `area` is the
 * page or component file stem (`portfolio.holdings.header.symbol`, `paperDesk.book.empty`). Strings
 * used by more than one page go in `common`. The prefix is what keeps shards from colliding, and
 * `catalog.test.ts` fails the build if two ever do -- a spread would otherwise let the later shard
 * silently win and take the earlier one's translation with it.
 *
 * Adding an area: create `messages/<area>.ts`, export a shard `as const satisfies MessageShard`,
 * and add it to the spread and the `SHARDS` list below. Both, or the duplicate check goes blind.
 */
import { activity } from "@/i18n/messages/activity";
import { agentDesk } from "@/i18n/messages/agentDesk";
import { agentWorkflow } from "@/i18n/messages/agentWorkflow";
import { auth } from "@/i18n/messages/auth";
import { backfill } from "@/i18n/messages/backfill";
import { common } from "@/i18n/messages/common";
import { competition } from "@/i18n/messages/competition";
import { competitionRounds } from "@/i18n/messages/competitionRounds";
import { data } from "@/i18n/messages/data";
import { designer } from "@/i18n/messages/designer";
import { desk } from "@/i18n/messages/desk";
import { glossary } from "@/i18n/messages/glossary";
import { interaction } from "@/i18n/messages/interaction";
import { landing } from "@/i18n/messages/landing";
import { macro } from "@/i18n/messages/macro";
import { manager } from "@/i18n/messages/manager";
import { market } from "@/i18n/messages/market";
import { misc } from "@/i18n/messages/misc";
import { nav } from "@/i18n/messages/nav";
import { paperDesk } from "@/i18n/messages/paperDesk";
import { personaAsk } from "@/i18n/messages/personaAsk";
import { personaChat } from "@/i18n/messages/personaChat";
import { personaAtoms } from "@/i18n/messages/personaAtoms";
import { personaBook } from "@/i18n/messages/personaBook";
import { personaConsensus } from "@/i18n/messages/personaConsensus";
import { personaProfile } from "@/i18n/messages/personaProfile";
import { personaScorecard } from "@/i18n/messages/personaScorecard";
import { personaTimeline } from "@/i18n/messages/personaTimeline";
import { personaTrader } from "@/i18n/messages/personaTrader";
import { personasPage } from "@/i18n/messages/personasPage";
import { portfolio } from "@/i18n/messages/portfolio";
import { serverVocab } from "@/i18n/messages/serverVocab";
import { shell } from "@/i18n/messages/shell";
import { strategy } from "@/i18n/messages/strategy";
import { symbol } from "@/i18n/messages/symbol";
import { tax } from "@/i18n/messages/tax";
import { ticker } from "@/i18n/messages/ticker";
import { ui } from "@/i18n/messages/ui";
import type { MessageShard } from "@/i18n/types";

export const CATALOG = {
  ...common,
  ...ui,
  ...glossary,
  ...interaction,
  ...shell,
  ...auth,
  ...backfill,
  ...nav,
  ...portfolio,
  ...ticker,
  ...activity,
  ...macro,
  ...desk,
  ...tax,
  ...symbol,
  ...data,
  ...designer,
  ...competition,
  ...competitionRounds,
  ...agentWorkflow,
  ...agentDesk,
  ...paperDesk,
  ...manager,
  ...market,
  ...strategy,
  ...landing,
  ...personaAtoms,
  ...personaScorecard,
  ...personaTimeline,
  ...personaAsk,
  ...personaChat,
  ...personaConsensus,
  ...personaBook,
  ...personaTrader,
  ...personaProfile,
  ...personasPage,
  ...serverVocab,
  ...misc,
} as const;

/** Every key in the catalog. `t()` accepts nothing else, so a typo is a compile error. */
export type MessageKey = keyof typeof CATALOG;

/** The shards, unmerged, for the duplicate-key check in `catalog.test.ts`. */
export const SHARDS: Readonly<Record<string, MessageShard>> = {
  common,
  ui,
  glossary,
  interaction,
  shell,
  auth,
  backfill,
  nav,
  portfolio,
  ticker,
  activity,
  macro,
  desk,
  tax,
  symbol,
  data,
  designer,
  competition,
  competitionRounds,
  agentWorkflow,
  agentDesk,
  paperDesk,
  manager,
  market,
  strategy,
  landing,
  personaAtoms,
  personaScorecard,
  personaTimeline,
  personaAsk,
  personaChat,
  personaConsensus,
  personaBook,
  personaTrader,
  personaProfile,
  personasPage,
  serverVocab,
  misc,
};
