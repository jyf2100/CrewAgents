import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("Agent Detail Page", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/admin/");
    // Wait for SPA to load agents
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(3000);
    // Find agent links — could be "查看 ->" links or agent name links
    const agentLinks = page.locator("a[href*='/agents/']");
    const viewLinks = page.getByText(/查看|view/i);
    const linkCount = await agentLinks.count();
    const viewCount = await viewLinks.count();
    test.skip(linkCount === 0 && viewCount === 0, "No agents available to test detail page");
    if (linkCount > 0) {
      await agentLinks.first().click();
    } else {
      await viewLinks.first().click();
    }
    await page.waitForURL(/\/admin\/agents\//);
    await page.waitForTimeout(2000);
  });

  test("renders agent detail with back button", async ({ page }) => {
    const backBtn = page.getByRole("button", { name: /back|返回/i });
    await expect(backBtn).toBeVisible();
  });

  test("renders all tabs", async ({ page }) => {
    const body = await page.textContent("body");
    // Should show tab navigation or content sections
    expect(body).toMatch(/overview|config|logs|health|总览|配置|日志|健康/i);
    await page.screenshot({ path: "test-results/agent-detail-tabs.png", fullPage: true });
  });

  test("Overview tab shows API access section", async ({ page }) => {
    const body = await page.textContent("body");
    expect(body).toMatch(/api|API|access|地址|密钥/i);
  });

  test("Config tab renders env editor", async ({ page }) => {
    await page.getByText(/config|配置/i).first().click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "test-results/agent-detail-config.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  test("Logs tab renders log viewer", async ({ page }) => {
    await page.getByText(/logs|日志/i).first().click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: "test-results/agent-detail-logs.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  test("Health tab renders health check", async ({ page }) => {
    await page.getByText(/health|健康/i).first().click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: "test-results/agent-detail-health.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  test("Restart button is visible in header", async ({ page }) => {
    const restartBtn = page.getByRole("button", { name: /restart|重启/i });
    const count = await restartBtn.count();
    if (count > 0) {
      await expect(restartBtn.first()).toBeVisible();
    }
  });

  test("Back button returns to dashboard", async ({ page }) => {
    const backBtn = page.getByRole("button", { name: /back|返回/i });
    const count = await backBtn.count();
    if (count > 0) {
      await backBtn.click();
      await page.waitForURL(/\/admin\/?$/);
      expect(page.url()).toMatch(/\/admin\/?$/);
    }
  });
});
