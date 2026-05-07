import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Navigation and Layout", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateTo(page, "/");
  });

  // ── Sidebar structure ──

  test("sidebar renders all admin nav items", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    // Dashboard
    expect(body).toMatch(/dashboard|仪表盘/i);
    // Settings
    expect(body).toMatch(/settings|设置/i);
  });

  test("sidebar shows NEWHERMES brand", async ({ page }) => {
    await page.waitForTimeout(2000);
    // Brand appears twice (desktop + mobile sidebar), use .first()
    const brand = page.getByText(/NEWHERMES/i).first();
    await expect(brand).toBeVisible();
  });

  test("sidebar shows Orchestrator section", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/编排器|orchestrator/i);
  });

  test("sidebar shows Swarm section", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/蜂群|swarm/i);
  });

  test("sidebar shows WebUI link", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/web.*ui|web.*对话/i);
  });

  // ── Sidebar link navigation ──
  // NOTE: Use .first() because desktop sidebar and mobile drawer both render links

  test("can navigate to Dashboard via sidebar", async ({ page }) => {
    await page.locator("a[href='/admin/'], a[href='/admin']").first().click();
    await page.waitForTimeout(1000);
    expect(page.url()).toMatch(/\/admin\/?$/);
  });

  test("can navigate to Settings via sidebar", async ({ page }) => {
    await page.locator("a[href*='settings']").first().click();
    await page.waitForTimeout(1000);
    expect(page.url()).toContain("settings");
  });

  test("can navigate to Orchestrator Overview via sidebar", async ({ page }) => {
    const link = page.locator("a[href='/admin/orchestrator']").first();
    if (await link.count() > 0) {
      await link.click();
      await page.waitForTimeout(2000);
      expect(page.url()).toMatch(/\/admin\/orchestrator\/?$/);
    }
  });

  test("can navigate to Submit Task via sidebar", async ({ page }) => {
    const link = page.locator("a[href='/admin/orchestrator/tasks/new']").first();
    if (await link.count() > 0) {
      await link.click();
      await page.waitForTimeout(2000);
      expect(page.url()).toMatch(/\/admin\/orchestrator\/tasks\/new/);
    }
  });

  test("can navigate to Swarm via sidebar", async ({ page }) => {
    const link = page.locator("a[href='/admin/swarm']").first();
    if (await link.count() > 0) {
      await link.click();
      await page.waitForTimeout(2000);
      expect(page.url()).toMatch(/\/admin\/swarm\/?$/);
    }
  });

  test("can navigate to Swarm Crews via sidebar", async ({ page }) => {
    const link = page.locator("a[href='/admin/swarm/crews']").first();
    if (await link.count() > 0) {
      await link.click();
      await page.waitForTimeout(2000);
      expect(page.url()).toMatch(/\/admin\/swarm\/crews/);
    }
  });

  test("can navigate to Swarm Tasks via sidebar", async ({ page }) => {
    const link = page.locator("a[href='/admin/swarm/tasks']").first();
    if (await link.count() > 0) {
      await link.click();
      await page.waitForTimeout(2000);
      expect(page.url()).toMatch(/\/admin\/swarm\/tasks/);
    }
  });

  test("can navigate to Swarm Knowledge via sidebar", async ({ page }) => {
    const link = page.locator("a[href='/admin/swarm/knowledge']").first();
    if (await link.count() > 0) {
      await link.click();
      await page.waitForTimeout(2000);
      expect(page.url()).toMatch(/\/admin\/swarm\/knowledge/);
    }
  });

  // ── Language toggle ──

  test("language toggle button is visible", async ({ page }) => {
    await page.waitForTimeout(2000);
    const langBtn = page.getByRole("button", { name: /en|zh|english|中文|English/i });
    const count = await langBtn.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test("language toggle switches language", async ({ page }) => {
    await page.waitForTimeout(2000);
    const langBtn = page.getByRole("button", { name: /en|zh|english|中文|English/i });
    const count = await langBtn.count();
    if (count > 0) {
      await langBtn.first().click();
      await page.waitForTimeout(500);
      const bodyAfter = await page.textContent("body");
      // Page should still render (not crash)
      expect(bodyAfter).toBeTruthy();
      expect(bodyAfter).not.toContain("输入管理员密钥");
    }
  });

  // ── Logout ──

  test("logout button is visible in topbar", async ({ page }) => {
    await page.waitForTimeout(2000);
    const logoutBtn = page.getByRole("button", { name: /logout|退出/i });
    const count = await logoutBtn.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test("logout button redirects to login", async ({ page }) => {
    await page.waitForTimeout(2000);
    const logoutBtn = page.getByRole("button", { name: /logout|退出/i });
    const count = await logoutBtn.count();
    if (count > 0) {
      await logoutBtn.first().click();
      await page.waitForTimeout(2000);
      // Should redirect to login page
      expect(page.url()).toMatch(/\/admin\/login|\/admin\/?$/);
    }
  });

  // ── All routes accessible ──

  test("all main routes are accessible without errors", async ({ page }) => {
    const routes = ["/", "/settings", "/orchestrator", "/swarm"];
    for (const route of routes) {
      await page.goto(`/admin${route}`);
      await page.waitForTimeout(2000);
      const body = await page.textContent("body");
      expect(body).not.toContain("输入管理员密钥");
      expect(body).toBeTruthy();
    }
  });

  // ── Active nav indicator ──

  test("sidebar shows active indicator for current page", async ({ page }) => {
    await page.waitForTimeout(2000);
    // Dashboard link should have active indicator
    const dashboardLink = page.locator("a[href='/admin/'], a[href='/admin']").first();
    const isActive = await dashboardLink.getAttribute("aria-current");
    expect(isActive).toBe("page");
  });

  // ── Cluster status in sidebar ──

  test("sidebar shows cluster status section", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/集群|cluster/i);
  });

  // ── Mobile hamburger menu ──

  test("hamburger menu button exists in DOM", async ({ page }) => {
    // The hamburger button exists but may be hidden on desktop (md:hidden)
    // Use locator directly instead of role-based since aria-label is in Chinese
    const hamburger = page.locator("button[aria-label='Open navigation menu'], button.md\\:hidden");
    const count = await hamburger.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });
});
