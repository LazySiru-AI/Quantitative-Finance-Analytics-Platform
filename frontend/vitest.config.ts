/**
 * Vitest configuration, separate from `vite.config.ts` on purpose.
 *
 * That file is a function of `mode` and carries a dev-server block with a port and an `/api` proxy
 * — none of which a test run has any use for, and the proxy in particular would make it possible to
 * write a "unit" test that quietly reached a live backend on port 8000. Tests here never talk to a
 * server: anything that would fetch is stubbed at the module boundary.
 *
 * The `@` alias is duplicated rather than imported from the other config, because importing it
 * would pull the server block back in with it.
 */
import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    // No `globals: true`. Every test imports `describe`/`it`/`expect` explicitly, which keeps them
    // resolvable by `tsc` without adding a `vitest/globals` types entry, and keeps a test file
    // readable as an ordinary module rather than one relying on ambient names.
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    // Shared CI runners are several times slower than a dev machine; the default 5s per test
    // turned slow-but-correct renders into failures there. See also `asyncUtilTimeout` in setup.ts.
    testTimeout: 30_000,
  },
});
