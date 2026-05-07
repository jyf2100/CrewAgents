import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e-real",
  fullyParallel: false,
  workers: 1,
  retries: 1,
  timeout: 30000,
  reporter: [["list"], ["html", { outputFolder: "playwright-report-183" }]],
  use: {
    baseURL: "http://172.32.153.183:32570/admin",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    actionTimeout: 10000,
    navigationTimeout: 30000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
