import { defineConfig, devices } from "@playwright/test";

/**
 * Hermetic E2E config. Builds and starts the real Next app with MSW enabled
 * (NEXT_PUBLIC_API_MOCKING), so the BFF/session code runs against an in-process
 * fake backend — no live API. Single origin (the upstream is mocked in-process),
 * single worker so the accumulating mock store is deterministic.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run build && npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 180 * 1000,
    stdout: "pipe",
    stderr: "pipe",
    env: {
      NEXT_PUBLIC_API_MOCKING: "enabled",
      NEXT_PUBLIC_API_URL: "http://localhost:8000",
      NEXT_PUBLIC_RAGENT_URL: "http://localhost:8001",
      WEB_SESSION_SECRET: "e2e-test-session-secret",
    },
  },
});
