/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const frontendDir = import.meta.dirname;
const projectRoot = path.resolve(frontendDir, "..");
const appVersion: string = JSON.parse(readFileSync(path.join(frontendDir, "package.json"), "utf8")).version;

export default defineConfig(({ mode }) => {
  // Read the backend's host and port from the shared root .env, so there is one place to change them.
  // Only MEDUSA_* keys are read, and they are used here in the dev server, never shipped to the browser.
  const env = loadEnv(mode, projectRoot, "MEDUSA_");
  const host = !env.MEDUSA_API_HOST || env.MEDUSA_API_HOST === "0.0.0.0" ? "127.0.0.1" : env.MEDUSA_API_HOST;
  const target = `http://${host}:${env.MEDUSA_API_PORT || "8000"}`;
  const proxy = { "/api": { target, changeOrigin: false } };

  return {
    plugins: [react(), tailwindcss()],
    // the UI version, compared with the backend version from /api/health to catch a stale server
    define: { __APP_VERSION__: JSON.stringify(appVersion) },
    resolve: { alias: { "@": path.resolve(frontendDir, "src") } },
    server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy },
    preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: false,
      restoreMocks: true,
    },
  };
});
