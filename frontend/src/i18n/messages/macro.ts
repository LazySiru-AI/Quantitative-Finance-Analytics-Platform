/**
 * Macro page, series charts, tiles and news panels.
 *
 * Keys are prefixed `macro.` -- see `catalog.ts` for the convention and for why the prefix
 * is load-bearing rather than cosmetic.
 *
 * Also covers `NewsPanel.tsx` / `useTickerNews.ts` (the ticker page's News & Sentiment panel) and
 * the API-error strings shared by every fetch hook in this shard's scope -- those files live outside
 * `pages/Macro.tsx` but are owned by the same extraction pass, and every key still has to start with
 * `macro.` per the shard convention, hence the `macro.tickerNews.*` / `macro.api.*` sub-namespaces
 * below rather than a same-named top-level key colliding with the Macro page's own News panel.
 */
import type { MessageShard } from "@/i18n/types";

export const macro = {
  // --- pages/Macro.tsx -------------------------------------------------------
  "macro.title": { en: "Macro", ko: "매크로" },
  "macro.subtitle": {
    en: "Sentiment and the four numbers you check daily, then rates, oil and mover detail below.",
    ko: "매일 확인하는 심리 지수와 네 가지 핵심 수치, 이어서 금리·원유·무버 상세 정보를 보여줍니다.",
  },
  "macro.refreshAriaLabel": { en: "Refresh macro snapshot", ko: "매크로 스냅샷 새로고침" },
  "macro.generatedAt": { en: "generated {date}", ko: "{date} 생성됨" },
  "macro.loading": { en: "Loading macro snapshot…", ko: "매크로 스냅샷을 불러오는 중…" },
  "macro.snapshotError": { en: "Could not load the macro snapshot.", ko: "매크로 스냅샷을 불러올 수 없습니다." },
  "macro.section.rates": { en: "Rates", ko: "금리" },
  "macro.section.oil": { en: "Oil", ko: "원유" },
  "macro.section.movers": { en: "Movers", ko: "주요 시황" },
  "macro.rates.emptyText": { en: "No rate data available.", ko: "금리 데이터가 없습니다." },
  "macro.oil.emptyText": { en: "No oil data available.", ko: "원유 데이터가 없습니다." },
  "macro.movers.emptyText": { en: "No mover data available.", ko: "주요 시황 데이터가 없습니다." },
  "macro.warnings.title": { en: "Warnings", ko: "경고" },

  // --- pages/Macro.tsx: FolderTabs rail ---------------------------------------
  // Short, tab-specific labels rather than reusing `macro.section.*` / `macro.news.title` directly --
  // `misc.fearGreed.title` and `misc.keyIndicators.title` already read as tab-length labels and are
  // reused as-is, but `macro.news.title` ("Global news & event markets") is too long for a tab, hence
  // its own short `macro.tabs.news` here. Matches the `tax.tabs.*` convention in `tax.ts`.
  "macro.tabs.label": { en: "Macro sections", ko: "매크로 섹션" },
  "macro.tabs.sentiment": { en: "Fear & Greed", ko: "공포·탐욕 지수" },
  "macro.tabs.indicators": { en: "Key indicators", ko: "핵심 지표" },
  "macro.tabs.rates": { en: "Rates", ko: "금리" },
  "macro.tabs.oil": { en: "Oil", ko: "원유" },
  "macro.tabs.movers": { en: "Movers", ko: "주요 시황" },
  "macro.tabs.news": { en: "News", ko: "뉴스" },

  // --- `MarketWarning.kind` pill labels (Macro.tsx's `WarningsStrip`) --------
  // `stale` reuses the shared `ui.pill.stale` label rather than a copy of the same word here.
  // Duplicated per page rather than shared, matching this codebase's existing convention for a
  // wire enum's display label (see `market.institutions.action.*` vs `market.consensus.action.*`,
  // and `warningKindLabel` in `api/tax.ts` vs `api/portfolio.ts`).
  "macro.warningKind.providerFallback": { en: "Provider fallback", ko: "대체 공급자 사용" },
  "macro.warningKind.clamped": { en: "Clamped", ko: "값 보정됨" },
  "macro.warningKind.shortHistory": { en: "Short history", ko: "짧은 이력" },
  "macro.warningKind.partialBar": { en: "Partial bar", ko: "미완성 봉" },
  "macro.warningKind.gap": { en: "Data gap", ko: "데이터 공백" },
  "macro.warningKind.other": { en: "Notice", ko: "알림" },

  // --- shared provenance labels (MacroSeriesChart.tsx + MacroTile.tsx) -------
  // `FRED` and `CNN` are the upstream's own initialisms and stay as-is, same as any other identifier
  // (rule 4). `yahoo` is flagged as a proxy standing in for an official series -- see both files'
  // `SOURCE_LABEL` docstrings -- so only the "(proxy)" gloss is translated.
  "macro.source.fred": { en: "FRED", ko: "FRED" },
  "macro.source.yahoo": { en: "Yahoo (proxy)", ko: "Yahoo (프록시)" },
  "macro.source.cnn": { en: "CNN", ko: "CNN" },
  "macro.source.computed": { en: "Computed", ko: "계산값" },
  "macro.source.store": { en: "Cached", ko: "캐시됨" },

  // --- shared "as of" fragments -----------------------------------------------
  // Two distinct catalog entries for what reads the same in English because the surrounding
  // whitespace/casing differs by call site and rule 1 requires byte-identical English:
  // `macro.series.asOf` keeps MacroSeriesChart's leading space (it sits mid-line, right after the
  // headline value); `macro.asOf` is the no-leading-space version MacroTile and the ticker
  // NewsPanel both use as a standalone line.
  "macro.asOf": { en: "as of {date}", ko: "{date} 기준" },

  // --- components/MacroSeriesChart.tsx ---------------------------------------
  "macro.series.noData": { en: "No data", ko: "데이터 없음" },
  "macro.series.observationCount_one": { en: "{count} observation", ko: "{count}개 관측치" },
  "macro.series.observationCount_other": { en: "{count} observations", ko: "{count}개 관측치" },
  "macro.series.spanSingleDate": { en: "{date} · {count}", ko: "{date} · {count}" },
  "macro.series.spanDateRange": { en: "{start} – {end} · {count}", ko: "{start} – {end} · {count}" },
  "macro.series.maxHistory": { en: "max history", ko: "전체 기간" },
  "macro.series.changeOverRange": { en: "{change} over {range}", ko: "{range} 동안 {change}" },
  "macro.series.rangeAriaLabel": { en: "{title} range", ko: "{title} 구간" },
  "macro.series.chartAriaLabel": { en: "{title} chart, {span}", ko: "{title} 차트, {span}" },
  "macro.series.loadingTitle": { en: "Loading {title}…", ko: "{title} 불러오는 중…" },
  "macro.series.notFound": {
    en: '"{id}" is not a series the server provides.',
    ko: '"{id}" 시계열은 서버에서 제공하지 않습니다.',
  },
  "macro.series.loadFailed": { en: "Failed to load series.", ko: "시계열을 불러오지 못했습니다." },
  "macro.series.loadError": {
    en: "Could not load {title}: {message}",
    ko: "{title} 정보를 불러오지 못했습니다: {message}",
  },
  "macro.series.noObservations": {
    en: "No observations available for {title}.",
    ko: "{title}에 대한 관측치가 없습니다.",
  },
  "macro.series.asOf": { en: " as of {date}", ko: " {date} 기준" },

  // --- components/MacroTile.tsx -----------------------------------------------
  "macro.tile.showChart": { en: "Show chart", ko: "차트 보기" },
  "macro.tile.hideChart": { en: "Hide chart", ko: "차트 숨기기" },
  "macro.tile.sparklineLabel": { en: "{label}, recent history", ko: "{label}, 최근 추이" },
  "macro.tile.sparkNoData": { en: "no data", ko: "데이터 없음" },
  "macro.tile.sparkDays_one": { en: "{count} day", ko: "{count}일" },
  "macro.tile.sparkDays_other": { en: "{count} days", ko: "{count}일" },
  "macro.tile.sparkSpan": { en: "{dayLabel} · {start} – {end}", ko: "{dayLabel} · {start} – {end}" },

  // --- components/MacroNewsPanel.tsx ------------------------------------------
  "macro.news.title": { en: "Global news & event markets", ko: "글로벌 뉴스 및 이벤트 마켓" },
  "macro.news.loading": { en: "Loading macro news…", ko: "매크로 뉴스를 불러오는 중…" },
  "macro.news.error": { en: "Could not load macro news.", ko: "매크로 뉴스를 불러올 수 없습니다." },
  "macro.news.generatedQuery": {
    en: "generated {age} · query: {query}",
    ko: "{age} 생성됨 · 검색어: {query}",
  },
  "macro.news.events.label": { en: "Event markets (Polymarket)", ko: "이벤트 마켓 (Polymarket)" },
  "macro.news.events.unreachable": {
    en: "Could not reach a prediction-market provider for today's query — this is not the same as saying no markets matched.",
    ko: "오늘의 조회에 대해 예측 시장 제공처에 연결할 수 없습니다 — 이는 일치하는 마켓이 없다는 의미와는 다릅니다.",
  },
  "macro.news.events.empty": {
    en: "The provider answered with no event markets matching today's query.",
    ko: "제공처가 응답했지만 오늘의 조회와 일치하는 이벤트 마켓이 없습니다.",
  },
  "macro.news.events.matched": {
    en: "{count} of up to {limit} requested event markets matched.",
    ko: "요청한 최대 {limit}건 중 {count}건의 이벤트 마켓이 일치했습니다.",
  },
  "macro.news.events.tileHint": {
    en: "{source} · as of {asOf} · resolves {resolves} · volume {volume}",
    ko: "{source} · {asOf} 기준 · 만기 {resolves} · 거래량 {volume}",
  },
  "macro.news.headlines.label": { en: "Global headlines", ko: "글로벌 헤드라인" },
  "macro.news.headlines.labelWithSource": {
    en: "Global headlines ({source})",
    ko: "글로벌 헤드라인 ({source})",
  },
  "macro.news.headlines.unreachable": {
    en: "Could not reach a global-news provider for today's query — this is not the same as saying nothing happened.",
    ko: "오늘의 조회에 대해 글로벌 뉴스 제공처에 연결할 수 없습니다 — 이는 아무 일도 없었다는 의미와는 다릅니다.",
  },
  "macro.news.headlines.empty": {
    en: "No headlines matched today's query.",
    ko: "오늘의 조회와 일치하는 헤드라인이 없습니다.",
  },
  "macro.news.headlines.matched": {
    en: "{count} of up to {limit} requested headlines from {source}.",
    ko: "{source}에서 요청한 최대 {limit}건 중 {count}건의 헤드라인을 가져왔습니다.",
  },

  // --- api/news.ts: formatRelativeAge -----------------------------------------
  // Shared by MacroNewsPanel.tsx, NewsPanel.tsx, and (outside this shard's scope) PersonaCard.tsx --
  // English output is byte-identical to before, so that out-of-scope caller keeps rendering
  // correctly; see the report for the live-retranslation caveat that applies to it.
  "macro.news.age.justNow": { en: "just now", ko: "방금 전" },
  "macro.news.age.minutes": { en: "{count}m ago", ko: "{count}분 전" },
  "macro.news.age.hours": { en: "{count}h ago", ko: "{count}시간 전" },
  "macro.news.age.days": { en: "{count}d ago", ko: "{count}일 전" },

  // --- components/NewsPanel.tsx (ticker page's News & Sentiment panel) --------
  "macro.tickerNews.title": { en: "News & sentiment", ko: "뉴스 및 심리" },
  "macro.tickerNews.loading": { en: "Loading news…", ko: "뉴스를 불러오는 중…" },
  "macro.tickerNews.error": { en: "Could not load news.", ko: "뉴스를 불러올 수 없습니다." },
  "macro.tickerNews.social.label": { en: "Social sentiment", ko: "소셜 심리" },
  "macro.tickerNews.social.labelWithSource": {
    en: "Social sentiment ({source})",
    ko: "소셜 심리 ({source})",
  },
  "macro.tickerNews.social.unreachable": {
    en: "Could not reach a social sentiment provider for this ticker — this is not the same as saying nobody is posting.",
    ko: "이 종목의 소셜 심리 제공처에 연결할 수 없습니다 — 이는 아무도 게시하지 않았다는 의미와는 다릅니다.",
  },
  "macro.tickerNews.social.emptyWindow": {
    en: "No messages were posted in the sampled window, so there is nothing yet to measure sentiment from.",
    ko: "표본 기간 동안 게시된 메시지가 없어 아직 심리를 측정할 수 없습니다.",
  },
  "macro.tickerNews.social.ratioLine": {
    en: "{ratio} bullish · {labelled} of {total} messages labelled",
    ko: "{labelled}/{total}건 라벨링됨 · 강세 {ratio}",
  },
  "macro.tickerNews.headlines.empty": {
    en: "No recent headlines found for {symbol}.",
    ko: "{symbol}에 대한 최근 헤드라인이 없습니다.",
  },

  // --- shared fetch-error strings (useMacroNews.ts, useMacroSnapshot.ts, useTickerNews.ts) --------
  "macro.api.errorStatus": { en: "API returned {status}: {message}", ko: "API 오류 {status}: {message}" },
  "macro.api.unreachable": {
    en: "Cannot reach the API. Is uvicorn running on port 8000?",
    ko: "API에 연결할 수 없습니다. 포트 8000에서 uvicorn이 실행 중인가요?",
  },
} as const satisfies MessageShard;
