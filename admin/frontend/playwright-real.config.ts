import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e-real",
  timeout: 30000,
  use: {
    baseURL: "http://100.105.228.5:40080",
  },
});
