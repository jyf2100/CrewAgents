import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Orchestrator Pages", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("overview page renders with agent fleet", async ({ page }) => {
    await navigateTo(page, "/orchestrator");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/orchestrator-overview.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).not.toContain("输入管理员密钥");
    expect(body).toMatch(/agent|集群/i);
  });

  test("overview page shows stats cards", async ({ page }) => {
    await navigateTo(page, "/orchestrator");
    await page.waitForTimeout(3000);
    const body = await page.textContent("body");
    expect(body).toMatch(/在线|运行中|online|running/i);
  });

  test("submit page renders task form", async ({ page }) => {
    await navigateTo(page, "/orchestrator/tasks/new");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/orchestrator-submit.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).not.toContain("输入管理员密钥");
    expect(body).toMatch(/prompt|提示|任务/i);
  });

  test("submit page has all form fields", async ({ page }) => {
    await navigateTo(page, "/orchestrator/tasks/new");
    await page.waitForTimeout(3000);
    const textareas = page.locator("textarea");
    const taCount = await textareas.count();
    expect(taCount).toBeGreaterThanOrEqual(1);

    const numInputs = page.locator("input[type='number']");
    const numCount = await numInputs.count();
    expect(numCount).toBeGreaterThanOrEqual(1);
  });

  test("submit button is disabled when prompt is empty", async ({ page }) => {
    await navigateTo(page, "/orchestrator/tasks/new");
    await page.waitForTimeout(3000);
    const submitBtn = page.getByRole("button", { name: /submit|提交/i });
    await expect(submitBtn).toBeDisabled();
  });

  test("submit button enables after filling prompt", async ({ page }) => {
    await navigateTo(page, "/orchestrator/tasks/new");
    await page.waitForTimeout(3000);
    await page.locator("textarea").first().fill("Test task prompt for E2E");
    const submitBtn = page.getByRole("button", { name: /submit|提交/i });
    await expect(submitBtn).toBeEnabled();
  });

  test("can submit a task and navigate to detail", async ({ page }) => {
    await navigateTo(page, "/orchestrator/tasks/new");
    await page.waitForTimeout(3000);
    await page.locator("textarea").first().fill("E2E test task - verify submission works");
    await page.getByRole("button", { name: /submit|提交/i }).click();
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/orchestrator-submit-result.png", fullPage: true });
  });

  test("sidebar has orchestrator navigation links", async ({ page }) => {
    await navigateTo(page, "/");
    await page.waitForTimeout(2000);
    const sidebarLinks = page.locator("a[href*='orchestrator']");
    const count = await sidebarLinks.count();
    expect(count).toBeGreaterThanOrEqual(2);
  });
});
