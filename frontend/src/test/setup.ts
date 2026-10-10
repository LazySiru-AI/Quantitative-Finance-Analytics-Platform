/**
 * Test setup.
 *
 * One rule, enforced rather than trusted: **no test in this suite makes a network request.** The
 * dev server proxies `/api` to a live backend, and a component that fetches on mount would happily
 * hit a real ledger from a test run if jsdom's `fetch` were left in place. So the global
 * is replaced with one that throws, naming the URL — a test that needs a response stubs `fetch`
 * itself, and a test that did not mean to fetch fails loudly instead of silently depending on
 * whatever happened to be running on port 8000.
 */
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup, configure } from "@testing-library/react";

// `findBy*`/`waitFor` give up after 1s by default. On a loaded CI runner a lazy page plus several
// stubbed fetches can take longer than that, which reads as "element not found" rather than "slow".
configure({ asyncUtilTimeout: 5000 });

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      throw new Error(
        `unstubbed fetch to ${String(input)} — stub it in the test, or render a component that does not fetch`,
      );
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
