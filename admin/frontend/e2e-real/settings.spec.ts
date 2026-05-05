import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Settings Page", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateTo(page, "/settings");
  });

  test("renders settings page with sections", async ({ page }) => {
    await page.waitForTimeout(2000);
    await page.screenshot({ path: "test-results/settings-overview.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
    // Should NOT show login prompt
    expect(body).not.toContain("输入管理员密钥");
  });

  test("shows cluster status section", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/集群|cluster|节点|node/i);
  });

  test("shows admin key section", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/管理员.*密钥|admin.*key|修改.*密钥|change.*key/i);
  });

  test("shows resource limits section", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/资源|限制|resource|limit|cpu|内存|memory/i);
  });

  test("shows template editor section", async ({ page }) => {
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toMatch(/模板|template/i);
  });

  test("admin key change inputs exist", async ({ page }) => {
    await page.waitForTimeout(2000);
    const inputs = page.locator("input[type='password']");
    const count = await inputs.count();
    expect(count).toBeGreaterThanOrEqual(2);
  });

  test("change key button is disabled without matching passwords", async ({ page }) => {
    await page.waitForTimeout(2000);
    const changeBtn = page.getByRole("button", { name: /change|修改|更新/i });
    const count = await changeBtn.count();
    if (count > 0) {
      await expect(changeBtn.first()).toBeDisabled();
    }
  });
});
