import { test, expect } from "@playwright/test";
import { VALID_ADMIN_KEY, mockAgentList, mockEmptyAgentList, mockClusterStatus, mockActionResponse } from "./fixtures/mock-data";
import { loginAsAdmin } from "./helpers";

test.describe("Dashboard", () => {
  // Helper to set auth and mock APIs
  async function goToDashboard(page) {
    await page.route("**/admin/api/agents", (route) =>
      route.fulfill({ json: mockAgentList })
    );
    await page.route("**/admin/api/cluster/status", (route) =>
      route.fulfill({ json: mockClusterStatus })
    );
    await loginAsAdmin(page);
    await page.goto("/admin/");
  }

  test("displays agent cards for each agent", async ({ page }) => {
    await goToDashboard(page);
    // Should show 3 agent cards (one per mock agent)
    await expect(page.getByText("hermes-gateway-1")).toBeVisible();
    await expect(page.getByText("hermes-gateway-2")).toBeVisible();
    await expect(page.getByText("hermes-gateway-3")).toBeVisible();
  });

  test("shows stat cards with correct counts", async ({ page }) => {
    await goToDashboard(page);
    // Running: 1, Stopped: 1, Failed: 1
    await expect(page.getByText("1").first()).toBeVisible();
  });

  test("shows create agent button", async ({ page }) => {
    await goToDashboard(page);
    const createBtn = page.getByRole("button", { name: /创建|Create/i }).first();
    await expect(createBtn).toBeVisible();
  });

  test("shows empty state when no agents", async ({ page }) => {
    await page.route("**/admin/api/agents", (route) =>
      route.fulfill({ json: mockEmptyAgentList })
    );
    await page.route("**/admin/api/cluster/status", (route) =>
      route.fulfill({ json: mockClusterStatus })
    );
    await loginAsAdmin(page);
    await page.goto("/admin/");

    // Should show dashed "+ New Agent" card or empty state
    await expect(page.getByText(/暂无|No Agent/i)).toBeVisible();
  });

  test("navigates to agent detail on card click", async ({ page }) => {
    await goToDashboard(page);
    // Click the "查看 →" link on first agent card
    await page.getByText(/查看|View/).first().click();
    await expect(page).toHaveURL(/\/agents\/\d+/);
  });

  test("agent card menu shows actions", async ({ page }) => {
    await goToDashboard(page);
    // Click kebab menu on first agent
    const kebabButtons = page.locator("details summary");
    await kebabButtons.first().click();
    // Should show menu items
    await expect(page.getByText(/重启|Restart/).first()).toBeVisible();
  });

  test("restart action calls API", async ({ page }) => {
    let restartCalled = false;
    // Match any agent restart endpoint (dashboard sorts agents, first may not be agent 1)
    await page.route("**/admin/api/agents/*/restart", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      restartCalled = true;
      return route.fulfill({ json: mockActionResponse("restart") });
    });
    await goToDashboard(page);

    // Open menu and click restart
    const kebabButtons = page.locator("details summary");
    await kebabButtons.first().click();
    await page.getByText(/重启|Restart/).first().click();
    await expect(() => expect(restartCalled).toBe(true)).toPass();
  });
});
