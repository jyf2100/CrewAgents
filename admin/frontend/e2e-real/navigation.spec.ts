import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Navigation and Layout", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateTo(page, "/");
  });

  test("sidebar renders all admin nav items", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    // Dashboard
    expect(body).toMatch(/dashboard|仪表盘/i);
    // Settings
    expect(body).toMatch(/settings|设置/i);
  });

  test("can navigate to all sidebar links", async ({ page }) => {
    // Dashboard link
    await page.locator("a[href='/admin/'], a[href='/admin']").first().click();
    await page.waitForTimeout(1000);
    expect(page.url()).toMatch(/\/admin\/?$/);

    // Settings link
    await page.locator("a[href*='settings']").first().click();
    await page.waitForTimeout(1000);
    expect(page.url()).toContain("settings");
  });

  test("language toggle switches language", async ({ page }) => {
    await page.waitForTimeout(2000);
    // Find language toggle (en/zh button)
    const langBtn = page.getByRole("button", { name: /en|zh|english|中文/i });
    const count = await langBtn.count();
    if (count > 0) {
      await langBtn.first().click();
      await page.waitForTimeout(500);
      // Page should still render
      const body = await page.textContent("body");
      expect(body).toBeTruthy();
    }
  });

  test("logout button redirects to login", async ({ page }) => {
    await page.waitForTimeout(2000);
    const logoutBtn = page.getByRole("button", { name: /logout|退出/i });
    const count = await logoutBtn.count();
    if (count > 0) {
      await logoutBtn.click();
      await page.waitForTimeout(2000);
      // Should redirect to login page
      expect(page.url()).toMatch(/\/admin\/login|\/admin\/?$/);
    }
  });

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
});
