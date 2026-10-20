import { defineConfig } from "@playwright/test";

const baseURL = `http://127.0.0.1:${process.env.LODEX_TEST_PORT || "18765"}`;

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  use: { baseURL, headless: true },
  webServer: {
    command: "../../.venv/bin/python ../tests/browser_fixture.py",
    url: baseURL,
    reuseExistingServer: false,
    gracefulShutdown: { signal: "SIGTERM", timeout: 10000 },
    timeout: 30000,
  },
});
