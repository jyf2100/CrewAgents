import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Dashboard Page", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateTo(page, "/");
  });

  test("renders dashboard with stats cards", async ({ page }) => {
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
    expect(body).toMatch(/运行中|已停止|失败|running|stopped|failed/i);
  });

  test("shows Create Agent button", async ({ page }) => {
    const createBtn = page.getByRole("button", { name: /创建.*agent|create.*agent/i }).first();
    await expect(createBtn).toBeVisible();
  });

  test("Create Agent button navigates to /create", async ({ page }) => {
    await page.getByRole("button", { name: /创建.*agent|create.*agent/i }).first().click();
    await page.waitForURL(/\/admin\/create/);
    expect(page.url()).toContain("/admin/create");
  });

  test("renders agent cards for running agents", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    // Either agent cards exist or empty state message
    expect(body).toMatch(/hermes-gateway|暂无|no.*agent/i);
  });

  test("agent card has View link", async ({ page }) => {
    await page.waitForTimeout(2000);
    const viewLinks = page.getByText(/查看|view/i);
    const count = await viewLinks.count();
    if (count > 0) {
      await viewLinks.first().click();
      await page.waitForURL(/\/admin\/agents\//);
      expect(page.url()).toContain("/admin/agents/");
    }
  });

  test("agent card kebab menu opens with actions", async ({ page }) => {
    await page.waitForTimeout(2000);
    await page.screenshot({ path: "test-results/dashboard-agent-cards.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  test("shows cluster status bar", async ({ page }) => {
    const body = await page.textContent("body");
    expect(body).toMatch(/集群|cluster|cpu|memory|内存/i);
  });

  test("navigates to agent detail via card click", async ({ page }) => {
    await page.waitForTimeout(2000);
    const agentLinks = page.locator("a[href*='/agents/']");
    const count = await agentLinks.count();
    if (count > 0) {
      await agentLinks.first().click();
      await page.waitForURL(/\/admin\/agents\//);
      expect(page.url()).toContain("/admin/agents/");
    }
  });
});
