import { test, expect } from "@playwright/test";
import { VALID_ADMIN_KEY, mockEmptyAgentList, mockClusterStatus } from "./fixtures/mock-data";

test.describe("Login", () => {
  test("shows login form on /login", async ({ page }) => {
    await page.goto("/admin/login");
    await expect(page.locator('input[type="password"]')).toBeVisible();
  });

  test("redirects to login when not authenticated", async ({ page }) => {
    await page.goto("/admin/");
    // Should end up on login page
    await expect(page).toHaveURL(/\/login/);
  });

  test("rejects invalid API key", async ({ page }) => {
    // Mock health endpoint to return 401
    await page.route("**/admin/api/health", (route) =>
      route.fulfill({ status: 401, json: { detail: "Unauthorized" } })
    );

    await page.goto("/admin/login");
    await page.fill('input[type="password"]', "wrong-key");
    await page.click('button[type="submit"]');

    // Should show error and stay on login page
    await expect(page).toHaveURL(/\/login/);
  });

  test("accepts valid API key and redirects to dashboard", async ({ page }) => {
    // Mock health and dashboard endpoints
    await page.route("**/admin/api/health", (route) =>
      route.fulfill({ json: { status: "ok" } })
    );
    await page.route("**/admin/api/agents", (route) =>
      route.fulfill({ json: mockEmptyAgentList })
    );
    await page.route("**/admin/api/cluster/status", (route) =>
      route.fulfill({ json: mockClusterStatus })
    );

    await page.goto("/admin/login");
    await page.fill('input[type="password"]', VALID_ADMIN_KEY);
    await page.click('button[type="submit"]');

    // Should redirect to dashboard
    await expect(page).toHaveURL(/\/admin/);
  });
});
