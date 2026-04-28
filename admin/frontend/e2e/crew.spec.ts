import { test, expect } from "@playwright/test";
import { loginAsAdmin, mockApi } from "./helpers";
import {
  mockCrews,
  mockEmptyCrews,
  mockCreatedCrew,
  mockDagCrew,
  mockSwarmEnabled,
  mockSwarmAgents,
} from "./fixtures/mock-data";

test.describe("Crew Management", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    // Force English locale so assertions match i18n keys
    await page.evaluate(() => {
      localStorage.setItem("admin_lang", "en");
    });

    // Base mocks for swarm pages
    await mockApi(page, {
      "GET:/admin/api/swarm/capability": mockSwarmEnabled,
      "GET:/admin/api/swarm/agents": mockSwarmAgents,
      "GET:/admin/api/swarm/crews": mockCrews,
    });
  });

  // ────────────────────────────────────────────────────────────────
  // List View
  // ────────────────────────────────────────────────────────────────

  test("renders crew list with cards", async ({ page }) => {
    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Sequential")).toBeVisible();
    await expect(page.getByText("1 agents")).toBeVisible();
    await expect(page.getByText("1 steps")).toBeVisible();
  });

  test("empty state shows CTA", async ({ page }) => {
    // Override crews mock with empty list
    await mockApi(page, {
      "GET:/admin/api/swarm/capability": mockSwarmEnabled,
      "GET:/admin/api/swarm/agents": mockSwarmAgents,
      "GET:/admin/api/swarm/crews": mockEmptyCrews,
    });
    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("No crews yet")).toBeVisible({ timeout: 10000 });
  });

  test("navigates to create crew form", async ({ page }) => {
    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });
    await page.getByText("Create Crew").first().click();
    await expect(page).toHaveURL(/\/swarm\/crews\/new/);
  });

  test("deletes crew after confirmation", async ({ page }) => {
    // Set up dialog handler to auto-accept confirm()
    page.on("dialog", (dialog) => dialog.accept());

    // Mock DELETE returning success, then GET returning empty list
    let deleteCalled = false;
    await page.route("**/admin/api/swarm/crews/crew-1", async (route) => {
      if (route.request().method() === "DELETE") {
        deleteCalled = true;
        return route.fulfill({ json: { message: "deleted" } });
      }
      // Fallback for other methods
      return route.fallback();
    });

    // After delete, the store re-fetches crews — return empty
    await page.route("**/admin/api/swarm/crews", async (route) => {
      if (route.request().method() === "GET" && deleteCalled) {
        return route.fulfill({ json: mockEmptyCrews });
      }
      return route.fallback();
    });

    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });

    // Click the Delete button on the crew card
    await page.getByText("Delete").click();

    // Verify crew list is now empty
    await expect(page.getByText("No crews yet")).toBeVisible({ timeout: 10000 });
  });

  test("shows error when load fails", async ({ page }) => {
    // Override crews mock to return a server error
    await page.route("**/admin/api/swarm/crews", async (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ status: 500, json: { detail: "Internal error" } });
      }
      return route.fallback();
    });

    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Failed to load crews")).toBeVisible({ timeout: 10000 });
  });

  // ────────────────────────────────────────────────────────────────
  // Create View
  // ────────────────────────────────────────────────────────────────

  test("creates a new crew", async ({ page }) => {
    // Override POST mock for crew creation
    await page.route("**/admin/api/swarm/crews", async (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ json: mockCreatedCrew });
      }
      return route.fulfill({ json: mockCrews });
    });

    await page.goto("/admin/swarm/crews/new");
    await expect(page.getByLabel("Name")).toBeVisible({ timeout: 10000 });

    await page.getByLabel("Name").fill("New Crew");
    await page.getByLabel("Description").fill("A new crew");

    // Fill step_1 capability
    const capInput = page.getByLabel(/step_1.*Capability/i);
    await capInput.fill("translation");

    await page.getByText("Save").click();

    // Should navigate to edit page after creation
    await expect(page).toHaveURL(/\/swarm\/crews\/crew-new\/edit/, { timeout: 10000 });
  });

  test("validates required name field", async ({ page }) => {
    await page.goto("/admin/swarm/crews/new");
    await expect(page.getByLabel("Name")).toBeVisible({ timeout: 10000 });

    // Leave name empty, fill step capability, then try to save
    const capInput = page.getByLabel(/step_1.*Capability/i);
    await capInput.fill("translation");

    await page.getByText("Save").click();

    // Should show validation error
    await expect(page.getByText("This field is required")).toBeVisible({ timeout: 10000 });
  });

  test("switches workflow type", async ({ page }) => {
    await page.goto("/admin/swarm/crews/new");
    await expect(page.getByLabel("Name")).toBeVisible({ timeout: 10000 });

    // Verify Sequential is the default
    const workflowSelect = page.locator("select").first();
    await expect(workflowSelect).toHaveValue("sequential");

    // Switch to Parallel
    await workflowSelect.selectOption("parallel");
    await expect(workflowSelect).toHaveValue("parallel");

    // Switch to DAG — should reveal Dependencies inputs
    await workflowSelect.selectOption("dag");
    await expect(workflowSelect).toHaveValue("dag");

    // DAG mode shows "Dependencies" input for each step
    await expect(page.getByLabel(/step_1.*Dependencies/i)).toBeVisible({ timeout: 10000 });
  });

  // ────────────────────────────────────────────────────────────────
  // Edit View
  // ────────────────────────────────────────────────────────────────

  test("loads existing crew for editing", async ({ page }) => {
    await page.goto("/admin/swarm/crews/crew-1/edit");

    // Wait for the form to populate from the crew data
    await expect(page.getByLabel("Name")).toBeVisible({ timeout: 10000 });
    await expect(page.getByLabel("Name")).toHaveValue("Review Team", { timeout: 10000 });

    // Verify workflow type shows Sequential — target the select with workflow options
    const workflowSelect = page.locator('select:has(option[value="sequential"])');
    await expect(workflowSelect).toHaveValue("sequential", { timeout: 10000 });
  });

  test("updates crew", async ({ page }) => {
    let putCalled = false;
    await page.route("**/admin/api/swarm/crews/crew-1", async (route) => {
      if (route.request().method() === "PUT") {
        putCalled = true;
        return route.fulfill({
          json: {
            ...mockCrews.results[0],
            name: "Updated Review Team",
          },
        });
      }
      return route.fallback();
    });

    // After update, re-fetch returns updated crew
    await page.route("**/admin/api/swarm/crews", async (route) => {
      if (route.request().method() === "GET" && putCalled) {
        return route.fulfill({
          json: {
            results: [{ ...mockCrews.results[0], name: "Updated Review Team" }],
            total: 1,
          },
        });
      }
      return route.fallback();
    });

    await page.goto("/admin/swarm/crews/crew-1/edit");
    await expect(page.getByLabel("Name")).toHaveValue("Review Team", { timeout: 10000 });

    // Change the name
    await page.getByLabel("Name").clear();
    await page.getByLabel("Name").fill("Updated Review Team");

    await page.getByText("Save").click();

    // The store should not show an error
    await expect(page.getByText("Failed to update crew")).not.toBeVisible();
  });

  // ────────────────────────────────────────────────────────────────
  // DAG Workflow
  // ────────────────────────────────────────────────────────────────

  test("creates DAG crew with dependencies", async ({ page }) => {
    // Mock POST to return the DAG crew
    await page.route("**/admin/api/swarm/crews", async (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ json: mockDagCrew });
      }
      return route.fulfill({ json: mockCrews });
    });

    await page.goto("/admin/swarm/crews/new");
    await expect(page.getByLabel("Name")).toBeVisible({ timeout: 10000 });

    // Fill name
    await page.getByLabel("Name").fill("Pipeline Team");

    // Switch to DAG workflow
    const workflowSelect = page.locator("select").first();
    await workflowSelect.selectOption("dag");

    // Fill step_1 capability
    await page.getByLabel(/step_1.*Capability/i).fill("analysis");

    // Add a second step
    await page.getByText("Add Step").click();

    // Fill step_2 capability and dependencies
    await page.getByLabel(/step_2.*Capability/i).fill("code-review");
    await page.getByLabel(/step_2.*Dependencies/i).fill("step_1");

    await page.getByText("Save").click();

    // Should navigate to edit page for the DAG crew
    await expect(page).toHaveURL(/\/swarm\/crews\/crew-dag\/edit/, { timeout: 10000 });
  });

  test("detects circular dependencies", async ({ page }) => {
    await page.goto("/admin/swarm/crews/new");
    await expect(page.getByLabel("Name")).toBeVisible({ timeout: 10000 });

    // Fill name to pass name validation
    await page.getByLabel("Name").fill("Circular Team");

    // Switch to DAG workflow
    const workflowSelect = page.locator("select").first();
    await workflowSelect.selectOption("dag");

    // Fill step_1 capability and make it depend on step_2
    await page.getByLabel(/step_1.*Capability/i).fill("analysis");
    await page.getByLabel(/step_1.*Dependencies/i).fill("step_2");

    // Add a second step
    await page.getByText("Add Step").click();

    // Fill step_2 capability and make it depend on step_1 — circular!
    await page.getByLabel(/step_2.*Capability/i).fill("code-review");
    await page.getByLabel(/step_2.*Dependencies/i).fill("step_1");

    await page.getByText("Save").click();

    // Should show circular dependencies validation error
    await expect(page.getByText("circular dependencies")).toBeVisible({ timeout: 10000 });
  });
});
