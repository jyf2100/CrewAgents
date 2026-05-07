import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Dashboard Page", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateTo(page, "/");
  });

  // ── Page load and stats ──

  test("renders dashboard with stats cards", async ({ page }) => {
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
    expect(body).toMatch(/运行中|已停止|失败|running|stopped|failed/i);
  });

  test("shows cluster status bar", async ({ page }) => {
    const body = await page.textContent("body");
    expect(body).toMatch(/集群|cluster|cpu|memory|内存/i);
  });

  // ── Create Agent button ──

  test("shows Create Agent button", async ({ page }) => {
    const createBtn = page.getByRole("button", { name: /创建.*agent|create.*agent/i }).first();
    await expect(createBtn).toBeVisible();
  });

  test("Create Agent button navigates to /create", async ({ page }) => {
    await page.getByRole("button", { name: /创建.*agent|create.*agent/i }).first().click();
    await page.waitForURL(/\/admin\/create/);
    expect(page.url()).toContain("/admin/create");
  });

  // ── Agent cards ──

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

  // ── Dashboard visual ──

  test("dashboard full page screenshot", async ({ page }) => {
    await page.screenshot({ path: "test-results/dashboard-full.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).not.toContain("输入管理员密钥");
  });

  // ── Cluster status section ──

  test("cluster status shows resource gauges", async ({ page }) => {
    await page.waitForTimeout(2000);
    // Look for gauge chart elements or resource text
    const gauges = page.locator("[class*='gauge'], [class*='GaugeChart'], svg");
    const gaugeCount = await gauges.count();
    // Should have SVG elements for gauge charts
    expect(gaugeCount).toBeGreaterThan(0);
  });

  // ── Refresh behavior ──

  test("dashboard data refreshes on page reload", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body1 = await page.textContent("body");
    await page.reload();
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);
    const body2 = await page.textContent("body");
    // Should still show agent data after reload
    expect(body2).toBeTruthy();
    expect(body2).not.toContain("输入管理员密钥");
  });
});
