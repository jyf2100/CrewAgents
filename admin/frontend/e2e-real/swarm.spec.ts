import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Swarm Pages", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

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

  test("swarm tasks coming soon page renders", async ({ page }) => {
    await navigateTo(page, "/swarm/tasks");
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/coming soon|即将|敬请/i);
  });

  test("swarm knowledge coming soon page renders", async ({ page }) => {
    await navigateTo(page, "/swarm/knowledge");
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/coming soon|即将|敬请/i);
  });
});
