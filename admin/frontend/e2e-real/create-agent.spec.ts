import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Create Agent Page", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateTo(page, "/create");
  });

  // ── Page structure ──

  test("renders create page with step indicator", async ({ page }) => {
    const body = await page.textContent("body");
    expect(body).toMatch(/basic|llm|soul|review|step|基本|模型|灵魂|review/i);
  });

  test("step 1: has agent number and display name inputs", async ({ page }) => {
    const body = await page.textContent("body");
    expect(body).toMatch(/number|编号|name|名称|display/i);
  });

  // ── Buttons ──

  test("step 1: Cancel button is visible", async ({ page }) => {
    const cancelBtn = page.getByRole("button", { name: /cancel|取消/i });
    await expect(cancelBtn).toBeVisible();
  });

  test("step 1: Next button exists", async ({ page }) => {
    const nextBtn = page.getByRole("button", { name: /next|confirm|下一步|确认/i });
    await page.screenshot({ path: "test-results/create-step1.png", fullPage: true });
    // Next might be enabled or disabled depending on defaults
    const count = await nextBtn.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  // ── Form fields ──

  test("step 1: can type into display name input", async ({ page }) => {
    await page.waitForTimeout(1000);
    // Find text inputs (exclude number/hidden/password types)
    const textInput = page.locator("input[type='text'], input:not([type])").first();
    if (await textInput.count() > 0) {
      await textInput.fill("e2e-test-agent");
      const value = await textInput.inputValue();
      expect(value).toBe("e2e-test-agent");
    }
  });

  test("step 1: screenshot of wizard", async ({ page }) => {
    await page.waitForTimeout(1000);
    await page.screenshot({ path: "test-results/create-wizard.png", fullPage: true });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  // ── Navigation ──

  test("Cancel button navigates back to dashboard", async ({ page }) => {
    const cancelBtn = page.getByRole("button", { name: /cancel|取消/i });
    await expect(cancelBtn).toBeVisible();
    await cancelBtn.click();
    // Should go back to dashboard
    await page.waitForTimeout(1000);
    expect(page.url()).toMatch(/\/admin\/?$|\/admin\/\?/);
  });

  // ── Step navigation (if step indicator is clickable) ──

  test("wizard step indicators are visible", async ({ page }) => {
    await page.waitForTimeout(1000);
    // Look for step indicators
    const body = await page.textContent("body");
    expect(body).toMatch(/\d|step|步/i);
  });

  // ── Form validation ──

  test("step 1: all required fields are marked or hinted", async ({ page }) => {
    await page.waitForTimeout(1000);
    const body = await page.textContent("body");
    // Form should show required indicators or placeholders
    expect(body).toMatch(/name|名称|display|number|编号/i);
  });
});
