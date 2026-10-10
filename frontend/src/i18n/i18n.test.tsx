/**
 * The foundation's own tests: the store, the substitution rules, the catalog's structural
 * invariants, and the toggle.
 *
 * The catalog checks are the interesting ones. `tsc` already guarantees that every key has both
 * languages, because `MessagePair` makes them one entry -- so what is left to prove is what the
 * type cannot see: that no two shards claim the same key (a spread would let the later one silently
 * win, taking the earlier one's translation with it), that no Korean string was left empty, and
 * that no placeholder appears in one language but not the other.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import LanguageToggle from "@/components/LanguageToggle";
import Trans from "@/i18n/Trans";
import { CATALOG, SHARDS, type MessageKey } from "@/i18n/catalog";
import {
  DEFAULT_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  getLanguage,
  refreshLanguageFromStorage,
  setLanguage,
} from "@/i18n/store";
import { format, t, translate } from "@/i18n/t";
import { isLanguage } from "@/i18n/types";

function resetLanguage(): void {
  window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  refreshLanguageFromStorage();
}

beforeEach(resetLanguage);
afterEach(resetLanguage);

describe("catalog", () => {
  it("has no key claimed by two shards", () => {
    const seen = new Map<string, string>();
    const collisions: string[] = [];
    for (const [area, shard] of Object.entries(SHARDS)) {
      for (const key of Object.keys(shard)) {
        const owner = seen.get(key);
        if (owner) collisions.push(`${key}: ${owner} and ${area}`);
        else seen.set(key, area);
      }
    }
    expect(collisions).toEqual([]);
    // The spread in `catalog.ts` would hide a collision by producing a smaller object; comparing
    // the merged size against the summed shard sizes catches a shard left out of `SHARDS` too.
    expect(Object.keys(CATALOG)).toHaveLength(seen.size);
  });

  it("has a non-empty Korean string for every key", () => {
    const missing = Object.entries(CATALOG)
      .filter(([, pair]) => pair.ko.trim() === "")
      .map(([key]) => key);
    expect(missing).toEqual([]);
  });

  it("uses the same placeholders in both languages", () => {
    const slots = (value: string) => [...value.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    const mismatched = Object.entries(CATALOG)
      .filter(([, pair]) => slots(pair.en).join() !== slots(pair.ko).join())
      .map(([key]) => key);
    // A slot dropped in translation renders an empty gap where a number should be, and a slot
    // invented in translation renders the literal `{count}` to the user. Neither is visible to tsc.
    expect(mismatched).toEqual([]);
  });

  it("prefixes every key with its shard's area, or with a shared vocabulary", () => {
    const shared = new Set(["common", "status"]);
    const wrong: string[] = [];
    for (const [area, shard] of Object.entries(SHARDS)) {
      for (const key of Object.keys(shard)) {
        const prefix = key.split(".")[0] ?? "";
        if (prefix !== area && !(area === "common" && shared.has(prefix))) {
          wrong.push(`${key} (in ${area})`);
        }
      }
    }
    expect(wrong).toEqual([]);
  });
});

describe("format", () => {
  it("substitutes named slots", () => {
    expect(format("{a} and {b}", { a: "one", b: 2 })).toBe("one and 2");
  });

  it("leaves an unmatched slot verbatim rather than blanking it", () => {
    expect(format("{a} and {b}", { a: "one" })).toBe("one and {b}");
  });

  it("leaves prose braces alone", () => {
    expect(format("a { b } c", { b: "x" })).toBe("a { b } c");
  });
});

describe("store", () => {
  it("defaults to English", () => {
    expect(getLanguage()).toBe(DEFAULT_LANGUAGE);
    expect(DEFAULT_LANGUAGE).toBe("en");
  });

  it("persists a choice and mirrors it onto the document", () => {
    setLanguage("ko");
    expect(getLanguage()).toBe("ko");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("ko");
    expect(document.documentElement.lang).toBe("ko");
  });

  it("ignores a malformed stored value", () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "klingon");
    refreshLanguageFromStorage();
    expect(getLanguage()).toBe("en");
  });

  it("picks up a write from another tab", () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "ko");
    refreshLanguageFromStorage();
    expect(getLanguage()).toBe("ko");
  });

  it("recognises only the two shipped languages", () => {
    expect(isLanguage("en")).toBe(true);
    expect(isLanguage("ko")).toBe(true);
    expect(isLanguage("jp")).toBe(false);
    expect(isLanguage(null)).toBe(false);
  });
});

describe("t", () => {
  it("follows the active language", () => {
    expect(t("common.loading")).toBe("Loading…");
    setLanguage("ko");
    expect(t("common.loading")).toBe("불러오는 중…");
  });

  it("interpolates in either language", () => {
    const key: MessageKey = "shell.favorites.add";
    expect(translate("en", key, { label: "Macro" })).toBe("Add Macro to favorites");
    expect(translate("ko", key, { label: "Macro" })).toContain("Macro");
  });
});

describe("Trans", () => {
  it("substitutes a node into a slot and keeps the surrounding text", () => {
    render(<Trans k="common.asOf" values={{ date: <strong>2026-09-01</strong> }} />);
    expect(screen.getByText("2026-09-01").tagName).toBe("STRONG");
  });

  it("reorders with the translation rather than with the call site", () => {
    // English puts the date first, Korean puts it before a trailing particle. The call site says
    // nothing about order -- which is the whole reason this component exists.
    setLanguage("ko");
    const { container } = render(<Trans k="common.asOf" values={{ date: <b>2026-09-01</b> }} />);
    expect(container.textContent).toBe("2026-09-01 기준");
  });
});

describe("LanguageToggle", () => {
  it("shows both options with the active one pressed", () => {
    render(<LanguageToggle />);
    const en = screen.getByRole("button", { name: "Display in English" });
    const ko = screen.getByRole("button", { name: "Display in Korean" });
    expect(en.getAttribute("aria-pressed")).toBe("true");
    expect(ko.getAttribute("aria-pressed")).toBe("false");
  });

  it("switches the language on click and stays labelled in Korean afterwards", async () => {
    const user = userEvent.setup();
    render(<LanguageToggle />);

    await user.click(screen.getByRole("button", { name: "Display in Korean" }));

    expect(getLanguage()).toBe("ko");
    // The toggle's own labels are translated too, so after the switch it must be findable by its
    // Korean name -- a control that stays English is the first thing a Korean reader would see.
    const ko = screen.getByRole("button", { name: "한국어로 표시" });
    expect(ko.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("group", { name: "언어" })).toBeTruthy();
  });

  it("marks the Korean label with its own lang attribute", () => {
    render(<LanguageToggle />);
    expect(screen.getByRole("button", { name: "Display in Korean" }).getAttribute("lang")).toBe("ko");
  });
});
