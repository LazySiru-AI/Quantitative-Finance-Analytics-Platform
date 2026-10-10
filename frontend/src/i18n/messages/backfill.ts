/**
 * Backfill Tasks page (`BackfillTasks.tsx`) and its `api/backfill.ts` client.
 *
 * Keys are prefixed `backfill.` -- see `catalog.ts` for the convention.
 *
 * Left untranslated by design, per this repo's "don't translate identifiers/model text" rule (see
 * `agentWorkflow.ts`'s own docstring for the precedent): `task.persona_slug`/`task.filename`,
 * `task.published` (a bare `YYYY-MM-DD`), the packet `markdown` itself, the pasted-reply text, and
 * every server-supplied `reasons`/`dropped_symbols`/`ungrounded_numbers` entry -- all free text or
 * identifiers rendered as-is, never switched on.
 */
import type { MessageShard } from "@/i18n/types";

export const backfill = {
  // --- page header -----------------------------------------------------------
  "backfill.title": { en: "Backfill Tasks", ko: "백필 작업" },
  "backfill.subtitle": {
    en: "Copy a task packet to an external agent, paste its reply back, and ingest it.",
    ko: "작업 패킷을 외부 에이전트에 복사하고, 그 응답을 붙여넣어 반영합니다.",
  },

  /** The button beside the Personas heading that opens this queue as a panel on that page (see
   *  `Personas.tsx`). Named for where it renders, not for what it opens, because `backfill.title`
   *  above is already the panel's own heading and the two must not be the same string in one view. */
  "backfill.personasToggle": { en: "Backfill tasks", ko: "백필 작업" },

  // --- toolbar -----------------------------------------------------------------
  // "videos per persona", not a bare "Limit": the field is `GenerateRequest.limit`, which the
  // backend passes on as `limit_per_persona` -- so 5 with five personas seated generates 25 packets,
  // not 5. A reader who reads it as a total gets five times the work they asked for.
  "backfill.toolbar.limitLabel": {
    en: "Limit (videos per persona)",
    ko: "제한 (인물당 영상 수)",
  },
  "backfill.toolbar.generate": { en: "Generate new tasks", ko: "새 작업 생성" },
  "backfill.toolbar.generating": { en: "Generating…", ko: "생성 중…" },
  "backfill.toolbar.generatedCount": {
    en: "Generated {written} task(s).",
    ko: "{written}개의 작업을 생성했습니다.",
  },

  // --- task list -----------------------------------------------------------------
  "backfill.list.heading": { en: "Pending tasks", ko: "대기 중인 작업" },
  "backfill.list.countLabel": { en: "{count} pending", ko: "{count}개 대기 중" },
  "backfill.list.loading": { en: "Loading tasks…", ko: "작업 불러오는 중…" },
  "backfill.list.empty": { en: "No pending tasks — generate some.", ko: "대기 중인 작업이 없습니다 — 생성해 보세요." },
  "backfill.list.untitled": { en: "(untitled)", ko: "(제목 없음)" },
  "backfill.list.noDate": { en: "—", ko: "—" },

  // --- per-task actions --------------------------------------------------------
  "backfill.task.copyButton": { en: "Copy packet", ko: "패킷 복사" },
  "backfill.task.copying": { en: "Copying…", ko: "복사 중…" },
  "backfill.task.copied": { en: "Copied", ko: "복사됨" },
  "backfill.task.copyFallbackNote": {
    en: "Clipboard unavailable — select and copy the text below.",
    ko: "클립보드를 사용할 수 없습니다 — 아래 텍스트를 선택해 복사하세요.",
  },
  "backfill.task.pasteLabel": { en: "Agent reply", ko: "에이전트 응답" },
  "backfill.task.pastePlaceholder": {
    en: "Paste the agent's reply here",
    ko: "에이전트의 응답을 여기에 붙여넣으세요",
  },
  "backfill.task.validateButton": { en: "Validate", ko: "검증" },
  "backfill.task.validating": { en: "Validating…", ko: "검증 중…" },
  "backfill.task.ingestButton": { en: "Ingest", ko: "반영" },
  "backfill.task.ingesting": { en: "Ingesting…", ko: "반영 중…" },

  // --- validate result -----------------------------------------------------------
  "backfill.validate.ok": { en: "Looks good.", ko: "이상 없습니다." },
  "backfill.validate.failed": { en: "Validation failed.", ko: "검증에 실패했습니다." },
  "backfill.validate.reasonsHeading": { en: "Reasons", ko: "사유" },
  "backfill.validate.droppedSymbolsHeading": { en: "Dropped symbols", ko: "누락된 종목" },
  "backfill.validate.ungroundedNumbersHeading": { en: "Ungrounded numbers", ko: "근거 없는 수치" },

  // --- ingest result / errors -----------------------------------------------------
  "backfill.ingest.success": { en: "Ingested: {count} ticker(s).", ko: "반영 완료: 종목 {count}개." },
  "backfill.ingest.reasonsHeading": { en: "Reasons", ko: "사유" },

  // --- errors --------------------------------------------------------------------
  "backfill.errors.list": { en: "Could not load tasks.", ko: "작업 목록을 불러오지 못했습니다." },
  "backfill.errors.generate": { en: "Could not generate tasks.", ko: "작업을 생성하지 못했습니다." },
  "backfill.errors.copy": { en: "Could not copy the packet.", ko: "패킷을 복사하지 못했습니다." },
  "backfill.errors.validate": { en: "Could not validate the reply.", ko: "응답을 검증하지 못했습니다." },
  "backfill.errors.ingest": { en: "Could not ingest the reply.", ko: "응답을 반영하지 못했습니다." },
} as const satisfies MessageShard;
