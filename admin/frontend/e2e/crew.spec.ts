import { test, expect } from "@playwright/test";
import { loginAsAdmin, mockApi } from "./helpers";
import { mockCrews, mockCreatedCrew } from "./fixtures/mock-data";

test.describe("Crew Management", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    // Force English locale so assertions match i18n keys
    await page.evaluate(() => {
      localStorage.setItem("admin_lang", "en");
    });

    // Mock swarm capability and agents
    await mockApi(page, {
      "GET:/admin/api/swarm/capability": { enabled: true },
      "GET:/admin/api/swarm/agents": [],
      "GET:/admin/api/swarm/crews": mockCrews,
    });
  });

  test("renders crew list with cards", async ({ page }) => {
    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Sequential")).toBeVisible();
    await expect(page.getByText("1 agents")).toBeVisible();
    await expect(page.getByText("1 steps")).toBeVisible();
  });

  test("navigates to create crew form", async ({ page }) => {
    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });
    await page.click("text=Create Crew");
    await expect(page).toHaveURL(/\/swarm\/crews\/new/);
    await expect(page.getByLabel(/Name/)).toBeVisible();
  });

  test("creates a new crew", async ({ page }) => {
    // Override POST mock for crew creation
    await page.route("**/admin/api/swarm/crews", async (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ json: mockCreatedCrew });
      }
      // GET
      return route.fulfill({ json: mockCrews });
    });

    await page.goto("/admin/swarm/crews/new");
    await expect(page.getByLabel(/Name/)).toBeVisible({ timeout: 10000 });
    await page.getByLabel(/Name/).fill("New Crew");
    await page.getByLabel(/Description/).fill("A new crew");

    // Fill step capability
    const capInput = page.getByLabel(/step_1.*Capability/i);
    await capInput.fill("translation");

    await page.click("text=Save");

    // Should navigate to edit page after creation
    await expect(page).toHaveURL(/\/swarm\/crews\/crew-new\/edit/, { timeout: 10000 });
  });

  test("empty state shows CTA", async ({ page }) => {
    await mockApi(page, {
      "GET:/admin/api/swarm/capability": { enabled: true },
      "GET:/admin/api/swarm/agents": [],
      "GET:/admin/api/swarm/crews": { results: [], total: 0 },
    });
    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("No crews yet")).toBeVisible({ timeout: 10000 });
  });
});
