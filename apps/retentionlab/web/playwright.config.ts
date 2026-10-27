import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

// Offline sandboxes cannot download the pinned Chromium build; use a preinstalled one when present
// (override with PW_CHROMIUM). CI downloads the pinned browser and leaves executablePath unset.
const LOCAL = ["/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"];
const fromEnv = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env.PW_CHROMIUM;
const executablePath = fromEnv ?? LOCAL.find((p) => existsSync(p));

// PW_PORT picks the preview port (default 4173) so that two suites can run side by side.
const PORT = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env.PW_PORT ?? "4173";

// The e2e suite serves the production build under the same nested base path used on
// GitHub Pages, so route entry and reload are verified on the real prefix (master 21).
export const BASE = "/projects-site/labs/retentionlab/";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "evidence/playwright-report.json" }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}${BASE}`,
    headless: true,
    screenshot: "off",
  },
  webServer: {
    command: `npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort --base ${BASE}`,
    url: `http://127.0.0.1:${PORT}${BASE}`,
    reuseExistingServer: false,
    timeout: 90_000,
    stdout: "pipe",
    stderr: "pipe",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium", ...(executablePath ? { launchOptions: { executablePath } } : {}) } }],
});
