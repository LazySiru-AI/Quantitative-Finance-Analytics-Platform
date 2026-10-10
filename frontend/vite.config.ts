import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Config is a function of `mode` so the dev server's port and proxy target can come from a mode
// file. `vite` (mode "development") behaves exactly as it always has -- 5173 proxying to 8000. The
// UAT harness runs `vite --mode uat`, which picks up `.env.uat` and points a second dev server at
// the sandbox backend, so a persona can be put in front of synthetic data while the normal instance
// keeps serving the real ledger untouched.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL(".", import.meta.url)), "VITE_");

  return {
    plugins: [react()],
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    server: {
      // `PORT` first, then the mode file, then 5173.
      //
      // `PORT` is what a supervisor sets when it has assigned this server a free port -- without
      // honouring it, an `autoPort` launch config is silently ignored: vite binds whatever
      // `VITE_PORT` says regardless, the supervisor watches the port it assigned, and the server
      // looks like it failed to start when it is in fact running somewhere else. Reading it here
      // rather than renaming `VITE_PORT` keeps every existing mode file working untouched, since
      // `PORT` is unset in normal use and the expression falls straight through to them.
      port: Number(process.env.PORT ?? env.VITE_PORT ?? 5173),
      // Proxy /api to the FastAPI backend so the browser sees one origin in development.
      // This keeps CORS out of the picture for normal use; the backend's allow-list is a backstop.
      proxy: {
        "/api": {
          target: env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
