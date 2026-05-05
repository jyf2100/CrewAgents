import { test, expect } from "@playwright/test";

const ADMIN_KEY = process.env.ADMIN_KEY || "037a1b32e4b6a9131f565e2f24e7c864de765e64bc3b166bf2b41872347a7206";

test.describe("Orchestrator Real", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login");
    await page.evaluate((key) => {
      localStorage.setItem("admin_api_key", key);
      localStorage.setItem("admin_mode", "admin");
    }, ADMIN_KEY);
  });

  test("overview page renders orchestrator content", async ({ page }) => {
    await page.goto("/admin/orchestrator");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/orchestrator-overview.png", fullPage: true });
    const bodyText = await page.textContent("body");
    console.log("Overview body:", bodyText?.slice(0, 500));
    expect(bodyText).toBeTruthy();
    expect(bodyText).not.toContain("输入管理员密钥");
  });

  test("submit page renders task form", async ({ page }) => {
    await page.goto("/admin/orchestrator/tasks/new");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/orchestrator-submit.png", fullPage: true });
    const bodyText = await page.textContent("body");
    console.log("Submit body:", bodyText?.slice(0, 500));
    expect(bodyText).toBeTruthy();
    expect(bodyText).not.toContain("输入管理员密钥");
  });
});
