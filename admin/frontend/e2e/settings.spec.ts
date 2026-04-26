import { test, expect } from "@playwright/test";
import {
  VALID_ADMIN_KEY,
  mockSettings,
  mockClusterStatus,
  mockTemplate,
  mockMessageResponse,
} from "./fixtures/mock-data";
import { loginAsAdmin } from "./helpers";

test.describe("Settings", () => {
  async function goToSettings(page) {
    await page.route("**/admin/api/settings", (route) =>
      route.fulfill({ json: mockSettings })
    );
    await page.route("**/admin/api/cluster/status", (route) =>
      route.fulfill({ json: mockClusterStatus })
    );
    await page.route("**/admin/api/templates/deployment", (route) =>
      route.fulfill({ json: mockTemplate("deployment") })
    );
    await page.route("**/admin/api/templates/env", (route) =>
      route.fulfill({ json: mockTemplate("env") })
    );
    await page.route("**/admin/api/templates/config", (route) =>
      route.fulfill({ json: mockTemplate("config") })
    );
    await page.route("**/admin/api/templates/soul", (route) =>
      route.fulfill({ json: mockTemplate("soul") })
    );
    await loginAsAdmin(page);
    await page.goto("/admin/settings");
  }

  test("displays cluster status table", async ({ page }) => {
    await goToSettings(page);
    await expect(page.getByText("k8s-node-1")).toBeVisible();
    await expect(page.getByText("35.2%")).toBeVisible();
  });

  test("displays admin key section", async ({ page }) => {
    await goToSettings(page);
    // The masked key is shown in a read-only input
    await expect(page.locator('input[value="tes****1234"]')).toBeVisible();
  });

  test("displays resource limits", async ({ page }) => {
    await goToSettings(page);
    await expect(page.locator('input[value="1000m"]')).toBeVisible();
  });

  test("saves resource limits", async ({ page }) => {
    await goToSettings(page);
    let settingsSaved = false;
    // Register PUT handler AFTER goToSettings so it takes priority
    await page.route("**/admin/api/settings", async (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      settingsSaved = true;
      return route.fulfill({ json: mockMessageResponse("Settings saved") });
    });
    // Click save button in resources section
    const saveButtons = page.getByText(/保存|Save/i);
    // There are multiple save buttons, click one in the resources section
    await saveButtons.first().click();
    await expect(() => expect(settingsSaved).toBe(true)).toPass();
  });

  test("template editor shows sub-tabs", async ({ page }) => {
    await goToSettings(page);
    await expect(page.getByRole("button", { name: /Deployment/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Config/i })).toBeVisible();
  });

  test("template editor shows textarea content", async ({ page }) => {
    await goToSettings(page);
    // Click Config sub-tab (label is "Config 模板")
    await page.getByText(/Config 模板/).click();
    await expect(page.getByText("# config template content")).toBeVisible();
  });
});
