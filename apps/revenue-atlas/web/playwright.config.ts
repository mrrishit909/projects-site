import { defineConfig } from "@playwright/test";

// The e2e suite serves the production build under the same nested base path used on
// GitHub Pages, so route entry and reload are verified on the real prefix (master 21).
export const BASE = "/projects-site/labs/revenue-atlas/";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "evidence/playwright-report.json" }]],
  use: {
    baseURL: `http://127.0.0.1:4173${BASE}`,
    headless: true,
    screenshot: "off",
  },
  webServer: {
    command: `npx vite preview --port 4173 --strictPort --base ${BASE}`,
    url: `http://127.0.0.1:4173${BASE}`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
