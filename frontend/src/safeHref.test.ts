/**
 * `safeHref`'s scheme allowlist -- the one gate every server-supplied URL passes through before
 * reaching a real `href` (see the module docstring in `safeHref.ts` for why: feeds are untrusted,
 * and React escapes text content but not a URL's own scheme).
 */
import { describe, expect, it } from "vitest";

import { isSafeHref, safeHref } from "@/safeHref";

describe("safeHref", () => {
  it("passes an http URL through unchanged", () => {
    expect(safeHref("http://example.com/a")).toBe("http://example.com/a");
  });

  it("passes an https URL through unchanged", () => {
    expect(safeHref("https://example.com/a?b=1")).toBe("https://example.com/a?b=1");
  });

  it("rejects a javascript: URL", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
  });

  it("rejects a data: URL", () => {
    expect(safeHref("data:text/html,<script>alert(1)</script>")).toBeNull();
  });

  it("rejects a vbscript: URL", () => {
    expect(safeHref("vbscript:msgbox(1)")).toBeNull();
  });

  it("rejects a relative path (no scheme to check)", () => {
    expect(safeHref("/ticker/AAPL")).toBeNull();
  });

  it("rejects an unparseable string", () => {
    expect(safeHref("not a url at all")).toBeNull();
  });

  it("rejects null and undefined", () => {
    expect(safeHref(null)).toBeNull();
    expect(safeHref(undefined)).toBeNull();
  });

  it("rejects an empty or whitespace-only string", () => {
    expect(safeHref("")).toBeNull();
    expect(safeHref("   ")).toBeNull();
  });

  it("trims surrounding whitespace before parsing", () => {
    expect(safeHref("  https://example.com/a  ")).toBe("https://example.com/a");
  });

  it("accepts an uppercase scheme", () => {
    expect(safeHref("HTTPS://example.com/a")).toBe("HTTPS://example.com/a");
  });

  it("rejects an uppercase javascript: scheme", () => {
    expect(safeHref("JAVASCRIPT:alert(1)")).toBeNull();
  });

  describe("isSafeHref", () => {
    it("mirrors safeHref's pass/fail as a boolean", () => {
      expect(isSafeHref("https://example.com")).toBe(true);
      expect(isSafeHref("javascript:alert(1)")).toBe(false);
      expect(isSafeHref(null)).toBe(false);
    });
  });
});
