import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e-real",
  fullyParallel: false,
  forbidOnly: false,
  retries: 0,
  workers: 1,
  reporter: "list",
  timeout: 60000,
  use: {
    baseURL: "http://172.32.153.184:40080/admin",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
