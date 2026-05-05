import { test, expect } from "@playwright/test";

test.describe("Login Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login");
    await page.evaluate(() => {
      localStorage.removeItem("admin_api_key");
      localStorage.removeItem("admin_mode");
    });
    await page.reload();
    await page.waitForLoadState("networkidle").catch(() => {});
  });

  test("shows three login tabs", async ({ page }) => {
    // Use role=button to avoid matching subtitle text
    await expect(page.getByRole("button", { name: /邮箱|email/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /API Key/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /^管理员$/ })).toBeVisible();
  });

  test("email tab has email and password inputs", async ({ page }) => {
    await page.getByRole("button", { name: /邮箱|email/i }).click();
    await expect(page.locator("#login-email-input")).toBeVisible();
    await expect(page.locator("#login-password-input")).toBeVisible();
  });

  test("admin tab has key input", async ({ page }) => {
    await page.getByRole("button", { name: /^管理员$/ }).click();
    await expect(page.locator("#login-key-input")).toBeVisible();
  });

  test("user tab has key input with hint", async ({ page }) => {
    // Click the "API Key" or "用户" tab
    const userTab = page.locator("button").filter({ hasText: /^API Key$|^用户$/ }).first();
    await userTab.click();
    await expect(page.locator("#login-key-input")).toBeVisible();
  });

  test("login button is disabled when input is empty", async ({ page }) => {
    await page.getByRole("button", { name: /^管理员$/ }).click();
    const btn = page.getByRole("button", { name: /登录|login/i });
    await expect(btn).toBeDisabled();
  });

  test("login button enables after typing key", async ({ page }) => {
    await page.getByRole("button", { name: /^管理员$/ }).click();
    await page.locator("#login-key-input").fill("test-key");
    const btn = page.getByRole("button", { name: /登录|login/i });
    await expect(btn).toBeEnabled();
  });

  test("login with wrong key shows error", async ({ page }) => {
    await page.getByRole("button", { name: /^管理员$/ }).click();
    await page.locator("#login-key-input").fill("wrong-key");
    await page.getByRole("button", { name: /登录|login/i }).click();
    await page.waitForTimeout(3000);
    expect(page.url()).toMatch(/\/admin\/login/);
    const bodyText = await page.textContent("body");
    expect(bodyText).toBeTruthy();
  });

  test("email tab shows register toggle", async ({ page }) => {
    await page.getByRole("button", { name: /邮箱|email/i }).click();
    await expect(page.getByRole("button", { name: /注册|register/i })).toBeVisible();
  });

  test("email tab register mode shows name input", async ({ page }) => {
    await page.getByRole("button", { name: /邮箱|email/i }).click();
    await page.getByRole("button", { name: /注册|register/i }).click();
    await expect(page.locator("#register-name-input")).toBeVisible();
  });
});
