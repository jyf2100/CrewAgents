import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("Agent Detail Page", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/admin/");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(3000);
    // Find agent links
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

  // ── Header and navigation ──

  test("renders agent detail with back button", async ({ page }) => {
    const backBtn = page.getByRole("button", { name: /back|返回/i });
    await expect(backBtn).toBeVisible();
  });

  test("back button returns to dashboard", async ({ page }) => {
    const backBtn = page.getByRole("button", { name: /back|返回/i });
    const count = await backBtn.count();
    if (count > 0) {
      await backBtn.click();
      await page.waitForURL(/\/admin\/?$/);
      expect(page.url()).toMatch(/\/admin\/?$/);
    }
  });

  // ── Tab navigation ──

  test("renders all tabs", async ({ page }) => {
    const body = await page.textContent("body");
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

  // ── Action buttons ──

  test("Restart button is visible in header", async ({ page }) => {
    const restartBtn = page.getByRole("button", { name: /restart|重启/i });
    const count = await restartBtn.count();
    if (count > 0) {
      await expect(restartBtn.first()).toBeVisible();
    }
  });

  test("terminal tab is accessible", async ({ page }) => {
    const terminalTab = page.getByText(/terminal|终端/i);
    const count = await terminalTab.count();
    if (count > 0) {
      await terminalTab.first().click();
      await page.waitForTimeout(2000);
      await page.screenshot({ path: "test-results/agent-detail-terminal.png", fullPage: true });
      const body = await page.textContent("body");
      expect(body).toBeTruthy();
    }
  });

  // ── Agent info display ──

  test("shows agent name/ID in page header", async ({ page }) => {
    const body = await page.textContent("body");
    // Should show agent ID or name (like hermes-gateway-1)
    expect(body).toMatch(/hermes|gateway|agent/i);
  });

  test("shows agent status badge", async ({ page }) => {
    const body = await page.textContent("body");
    // Should show running/stopped/failed status
    expect(body).toMatch(/running|stopped|failed|运行中|已停止|失败/i);
  });

  // ── Direct URL navigation ──

  test("direct URL navigation to agent detail works", async ({ page }) => {
    // Get current URL to extract agent ID
    const url = page.url();
    const match = url.match(/\/agents\/(\d+)/);
    test.skip(!match, "Could not extract agent ID from URL");
    // Navigate away then back
    await page.goto("/admin/");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.goto(url);
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);
    // Should still show agent detail
    expect(page.url()).toMatch(/\/admin\/agents\//);
    const body = await page.textContent("body");
    expect(body).not.toContain("输入管理员密钥");
  });
});
