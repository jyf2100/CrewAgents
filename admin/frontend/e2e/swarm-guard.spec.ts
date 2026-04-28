/**
 * E2E tests for SwarmGuard behavior and sidebar navigation.
 *
 * SwarmGuard wraps all /swarm/* routes. It calls GET /swarm/capability:
 *   - If enabled=false or the request fails -> <Navigate to="/" /> (dashboard).
 *   - If enabled=true -> renders the child route normally.
 *
 * All API calls are intercepted via Playwright route interception.
 * No real backend is required.
 */
import { test, expect } from "@playwright/test";
import { loginAsAdmin, mockApi } from "./helpers";
import {
  mockSwarmEnabled,
  mockSwarmDisabled,
  mockSwarmAgents,
  mockSwarmMetrics,
  mockCrews,
  mockSseToken,
  mockAgentList,
  mockClusterStatus,
} from "./fixtures/mock-data";

/**
 * Helper: set up the baseline mocks required for the AdminLayout to render
 * (agents list + cluster status) and optionally the swarm capability endpoint.
 */
async function setupBaseMocks(
  page: import("@playwright/test").Page,
  options: {
    swarmCapability?: unknown;
    swarmAgents?: unknown;
    swarmMetrics?: unknown;
    capabilityStatus?: number;
  } = {}
) {
  const { swarmCapability, swarmAgents, swarmMetrics, capabilityStatus } =
    options;

  const routes: Record<string, unknown> = {
    "GET:/admin/api/agents": mockAgentList,
    "GET:/admin/api/cluster/status": mockClusterStatus,
  };

  // Swarm capability — can be overridden to return 500 etc.
  if (capabilityStatus !== undefined) {
    // Will be handled separately below with a dedicated route override
  } else if (swarmCapability !== undefined) {
    routes["GET:/admin/api/swarm/capability"] = swarmCapability;
  }

  if (swarmAgents !== undefined) {
    routes["GET:/admin/api/swarm/agents"] = swarmAgents;
  }
  if (swarmMetrics !== undefined) {
    routes["GET:/admin/api/swarm/metrics"] = swarmMetrics;
  }

  await mockApi(page, routes);

  // If we need a non-200 status for capability, override the mockApi route
  if (capabilityStatus !== undefined) {
    await page.route("**/admin/api/swarm/capability", async (route) => {
      return route.fulfill({
        status: capabilityStatus,
        body: JSON.stringify({ detail: "Internal Server Error" }),
      });
    });
  }
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe("SwarmGuard Redirects", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.evaluate(() => {
      localStorage.setItem("admin_lang", "en");
    });
  });

  test("redirects to dashboard when swarm is disabled", async ({ page }) => {
    await setupBaseMocks(page, {
      swarmCapability: mockSwarmDisabled,
      swarmAgents: mockSwarmAgents,
      swarmMetrics: mockSwarmMetrics,
    });

    await page.goto("/admin/swarm");

    // Should redirect to the dashboard
    await expect(page).toHaveURL(/\/admin\/?$/, { timeout: 10000 });

    // Swarm overview content should NOT be visible
    await expect(page.getByText("Supervisor")).not.toBeVisible();
  });

  test("redirects to dashboard when capability endpoint fails", async ({
    page,
  }) => {
    await setupBaseMocks(page, {
      capabilityStatus: 500,
    });

    await page.goto("/admin/swarm");

    // Should redirect to dashboard on error
    await expect(page).toHaveURL(/\/admin\/?$/, { timeout: 10000 });
  });

  test("redirects crew pages when swarm is disabled", async ({ page }) => {
    await setupBaseMocks(page, {
      swarmCapability: mockSwarmDisabled,
      swarmAgents: mockSwarmAgents,
      swarmMetrics: mockSwarmMetrics,
      swarmCrews: mockCrews,
    });

    await page.goto("/admin/swarm/crews");

    // Should redirect to dashboard
    await expect(page).toHaveURL(/\/admin\/?$/, { timeout: 10000 });

    // Crew content should NOT be visible
    await expect(page.getByText("Review Team")).not.toBeVisible();
  });

  test("allows access when swarm is enabled", async ({ page }) => {
    await setupBaseMocks(page, {
      swarmCapability: mockSwarmEnabled,
      swarmAgents: mockSwarmAgents,
      swarmMetrics: mockSwarmMetrics,
    });

    await page.goto("/admin/swarm");

    // Should stay on swarm page — no redirect
    await expect(page).toHaveURL(/\/admin\/swarm/, { timeout: 10000 });
    await expect(page).not.toHaveURL(/\/admin\/?$/);

    // Agent content should be visible
    await expect(page.getByText("Supervisor")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Code Reviewer")).toBeVisible();
  });
});

test.describe("Sidebar Navigation", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.evaluate(() => {
      localStorage.setItem("admin_lang", "en");
    });
  });

  test("swarm nav links visible when enabled", async ({ page }) => {
    await setupBaseMocks(page, {
      swarmCapability: mockSwarmEnabled,
      swarmAgents: mockSwarmAgents,
      swarmMetrics: mockSwarmMetrics,
    });

    await page.goto("/admin/");

    // Wait for the page to load
    await expect(page).toHaveURL(/\/admin\/?$/, { timeout: 10000 });

    // Sidebar should have "Swarm" section link
    const swarmLink = page
      .getByRole("link", { name: /Swarm/ })
      .first();
    await expect(swarmLink).toBeVisible({ timeout: 10000 });

    // Sidebar should have "Crews" link
    const crewsLink = page.getByRole("link", { name: /Crews/ });
    await expect(crewsLink).toBeVisible();
  });

  test("swarm nav links still visible when disabled", async ({ page }) => {
    await setupBaseMocks(page, {
      swarmCapability: mockSwarmDisabled,
    });

    await page.goto("/admin/");

    // Wait for dashboard to load
    await expect(page).toHaveURL(/\/admin\/?$/, { timeout: 10000 });

    // Swarm link is always rendered in the sidebar regardless of capability
    const swarmLink = page
      .getByRole("link", { name: /Swarm/ })
      .first();
    await expect(swarmLink).toBeVisible({ timeout: 10000 });
  });
});
