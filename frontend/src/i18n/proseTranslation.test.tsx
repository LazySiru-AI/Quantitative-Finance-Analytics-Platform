/**
 * `useProseTranslation` / `TranslatedProse` -- the on-display Korean translation path for
 * model-written prose (i18n rollout, Phase 4).
 *
 * Every test stubs `fetch` itself, per `@/test/setup.ts`'s rule against a real network call. The
 * module-level translation cache is reset before and after each test: it is intentionally shared
 * for the whole lifetime of the module (that is the point -- two components rendering the same
 * sentence must share one fetch), so left alone it would leak a translation cached by one test into
 * the next.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LANGUAGE_STORAGE_KEY, refreshLanguageFromStorage, setLanguage } from "@/i18n/store";
import TranslatedProse from "@/i18n/TranslatedProse";
import { __resetProseTranslationCacheForTests } from "@/i18n/useProseTranslation";

interface TranslateBody {
  results: (string | null)[];
}

function fetchOk(body: TranslateBody) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

/** Stubs `fetch` to answer `/api/i18n/translate` with `results` on every call. */
function stubTranslate(results: (string | null)[]) {
  const fetchMock = vi.fn(async () => fetchOk({ results }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function resetLanguage(): void {
  window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  refreshLanguageFromStorage();
}

beforeEach(() => {
  __resetProseTranslationCacheForTests();
  resetLanguage();
});

afterEach(() => {
  __resetProseTranslationCacheForTests();
  resetLanguage();
});

describe("TranslatedProse in English mode", () => {
  it("renders the original text, fetches nothing, and shows no badge", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<TranslatedProse text="The fund added to its position." />);

    expect(screen.getByText("The fund added to its position.")).toBeTruthy();
    expect(screen.queryByTitle(/./)).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("TranslatedProse in Korean mode", () => {
  it("shows the Korean translation and the machine-translated badge when the server supplies one", async () => {
    stubTranslate(["펀드가 포지션을 추가했다."]);
    setLanguage("ko");

    render(<TranslatedProse text="The fund added to its position." />);

    await waitFor(() => expect(screen.getByText("펀드가 포지션을 추가했다.")).toBeTruthy());
    expect(screen.getByText("기계 번역")).toBeTruthy();
    expect(screen.queryByText("원문 (영어)")).toBeNull();
    expect(screen.queryByText("The fund added to its position.")).toBeNull();
  });

  it("falls back to the English original with the English-origin badge when the server returns null", async () => {
    stubTranslate([null]);
    setLanguage("ko");

    render(<TranslatedProse text="The fund added to its position." />);

    await waitFor(() => expect(screen.getByText("원문 (영어)")).toBeTruthy());
    expect(screen.getByText("The fund added to its position.")).toBeTruthy();
    expect(screen.queryByText("기계 번역")).toBeNull();
  });

  it("returns the English original, badged, while a translation is still in flight", async () => {
    let resolveFetch: (body: TranslateBody) => void = () => {};
    const fetchMock = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveFetch = (body: TranslateBody) => resolve(fetchOk(body));
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    setLanguage("ko");

    render(<TranslatedProse text="Pending sentence." />);

    // Still pending: the reader sees the English original immediately, never a blank paragraph.
    expect(screen.getByText("Pending sentence.")).toBeTruthy();
    expect(screen.getByText("원문 (영어)")).toBeTruthy();

    await act(async () => {
      resolveFetch({ results: ["대기 문장."] });
      await Promise.resolve();
    });

    await waitFor(() => expect(screen.getByText("대기 문장.")).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renders nothing extra for empty or null text -- no fetch, no badge", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setLanguage("ko");

    const { container } = render(<TranslatedProse text={null} />);

    expect(container.querySelector("p")?.textContent).toBe("");
    expect(screen.queryByTitle(/./)).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("the module translation cache", () => {
  it("de-dupes: two components rendering identical text trigger exactly one fetch", async () => {
    const fetchMock = stubTranslate(["번역됨."]);
    setLanguage("ko");

    render(
      <>
        <TranslatedProse text="Same sentence." />
        <TranslatedProse text="Same sentence." />
      </>,
    );

    await waitFor(() => expect(screen.getAllByText("번역됨.")).toHaveLength(2));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // Both instances get the shared badge, not just the one that happened to start the fetch.
    expect(screen.getAllByText("기계 번역")).toHaveLength(2);
  });

  it("does not retry a text whose translation already resolved to null", async () => {
    const fetchMock = stubTranslate([null]);
    setLanguage("ko");

    const { unmount } = render(<TranslatedProse text="Never translates." />);
    await waitFor(() => expect(screen.getByText("원문 (영어)")).toBeTruthy());
    unmount();

    render(<TranslatedProse text="Never translates." />);
    expect(screen.getByText("원문 (영어)")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("toggling the language", () => {
  it("drops the machine-translated badge and shows the original immediately when switching back to English", async () => {
    stubTranslate(["번역됨."]);
    setLanguage("ko");

    render(<TranslatedProse text="Same sentence." />);
    await waitFor(() => expect(screen.getByText("번역됨.")).toBeTruthy());

    act(() => setLanguage("en"));

    expect(screen.getByText("Same sentence.")).toBeTruthy();
    expect(screen.queryByText("번역됨.")).toBeNull();
    expect(screen.queryByText("기계 번역")).toBeNull();
    expect(screen.queryByText("원문 (영어)")).toBeNull();
  });
});
