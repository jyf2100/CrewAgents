import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e-real",
  fullyParallel: false,
  timeout: 60000,
  retries: 0,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://172.32.153.183:32570/admin",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
