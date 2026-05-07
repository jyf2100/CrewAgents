import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Orchestrator Smoke Tests", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("overview page renders orchestrator content", async ({ page }) => {
    await navigateTo(page, "/orchestrator");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/orchestrator-smoke-overview.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
    expect(body).not.toContain("输入管理员密钥");
  });

  test("submit page renders task form", async ({ page }) => {
    await navigateTo(page, "/orchestrator/tasks/new");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/orchestrator-smoke-submit.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
    expect(body).not.toContain("输入管理员密钥");
    expect(body).toMatch(/prompt|提示|任务/i);
  });
});
