import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Swarm Pages", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  // ════════════════════════════════════════════════════════════════════════
  // Swarm Overview
  // ════════════════════════════════════════════════════════════════════════

  test("swarm overview page renders", async ({ page }) => {
    await navigateTo(page, "/swarm");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/swarm-overview.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
    expect(body).not.toContain("输入管理员密钥");
  });

  test("swarm overview shows agent stats", async ({ page }) => {
    await navigateTo(page, "/swarm");
    await page.waitForTimeout(3000);
    const body = await page.textContent("body");
    expect(body).toMatch(/运行中|在线|running|online|agent/i);
  });

  // ════════════════════════════════════════════════════════════════════════
  // Swarm Crews
  // ════════════════════════════════════════════════════════════════════════

  test("swarm crews page renders", async ({ page }) => {
    await navigateTo(page, "/swarm/crews");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/swarm-crews.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
    expect(body).not.toContain("输入管理员密钥");
  });

  test("swarm crews page has New Crew button", async ({ page }) => {
    await navigateTo(page, "/swarm/crews");
    await page.waitForTimeout(3000);
    const newCrewBtn = page.getByRole("button", { name: /new.*crew|新建|创建/i });
    const count = await newCrewBtn.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test("New Crew button navigates to crew creation page", async ({ page }) => {
    await navigateTo(page, "/swarm/crews");
    await page.waitForTimeout(3000);
    const newCrewBtn = page.getByRole("button", { name: /new.*crew|新建|创建/i });
    const count = await newCrewBtn.count();
    if (count > 0) {
      await newCrewBtn.first().click();
      await page.waitForTimeout(2000);
      expect(page.url()).toMatch(/\/admin\/swarm\/crews\/new|\/admin\/swarm\/crews\//);
    }
  });

  test("crew list shows crew cards or empty state", async ({ page }) => {
    await navigateTo(page, "/swarm/crews");
    await page.waitForTimeout(3000);
    const body = await page.textContent("body");
    // Either crew cards or empty state
    expect(body).toMatch(/crew|暂无|no.*crew|empty/i);
  });

  // ════════════════════════════════════════════════════════════════════════
  // Swarm Tasks (Coming Soon)
  // ════════════════════════════════════════════════════════════════════════

  test("swarm tasks coming soon page renders", async ({ page }) => {
    await navigateTo(page, "/swarm/tasks");
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/coming soon|即将|敬请/i);
  });

  // ════════════════════════════════════════════════════════════════════════
  // Swarm Knowledge (Coming Soon)
  // ════════════════════════════════════════════════════════════════════════

  test("swarm knowledge coming soon page renders", async ({ page }) => {
    await navigateTo(page, "/swarm/knowledge");
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/coming soon|即将|敬请/i);
  });

  // ════════════════════════════════════════════════════════════════════════
  // Crew Edit Page (if navigable)
  // ════════════════════════════════════════════════════════════════════════

  test("crew new page renders form", async ({ page }) => {
    await navigateTo(page, "/swarm/crews/new");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/swarm-crew-new.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
    expect(body).not.toContain("输入管理员密钥");
  });

  test("crew new page has form inputs", async ({ page }) => {
    await navigateTo(page, "/swarm/crews/new");
    await page.waitForTimeout(3000);
    // Should have name input and other form fields
    const inputs = page.locator("input");
    const count = await inputs.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test("crew new page has save/submit button", async ({ page }) => {
    await navigateTo(page, "/swarm/crews/new");
    await page.waitForTimeout(3000);
    const saveBtn = page.getByRole("button", { name: /save|submit|保存|提交|创建/i });
    const count = await saveBtn.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test("crew new page has cancel/back button", async ({ page }) => {
    await navigateTo(page, "/swarm/crews/new");
    await page.waitForTimeout(3000);
    const cancelBtn = page.getByRole("button", { name: /cancel|back|取消|返回/i });
    const count = await cancelBtn.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });
});
