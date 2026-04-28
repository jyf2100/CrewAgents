import { test, expect } from "@playwright/test";
import { loginAsAdmin, mockApi } from "./helpers";
import {
  mockSwarmAgents,
  mockSwarmMetrics,
  mockSwarmMetricsNoQueue,
  mockSwarmEnabled,
  mockSwarmDisabled,
} from "./fixtures/mock-data";

test.describe("Swarm Overview", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    // Force English locale so assertions match i18n keys
    await page.evaluate(() => {
      localStorage.setItem("admin_lang", "en");
    });

    await mockApi(page, {
      "GET:/admin/api/swarm/capability": mockSwarmEnabled,
      "GET:/admin/api/swarm/agents": mockSwarmAgents,
      "GET:/admin/api/swarm/metrics": mockSwarmMetrics,
      "GET:/admin/api/agents": { agents: [], total: 0 },
      "GET:/admin/api/cluster/status": {
        nodes: [],
        namespace: "hermes-agent",
        total_agents: 0,
        running_agents: 0,
      },
    });
  });

  // Helper: navigate to swarm page and wait for content to settle
  async function goToSwarm(page: import("@playwright/test").Page) {
    await page.goto("/admin/swarm");
    // Wait for the heading to confirm the page has rendered
    await expect(
      page.getByRole("heading", { name: "Swarm Overview" })
    ).toBeVisible({ timeout: 10000 });
  }

  // -----------------------------------------------------------------------
  // 1. Agent cards with names and capability tags
  // -----------------------------------------------------------------------
  test("shows swarm overview with agent cards", async ({ page }) => {
    await goToSwarm(page);

    // All 3 agent names
    await expect(page.getByText("Supervisor")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Code Reviewer")).toBeVisible();
    await expect(page.getByText("Translator")).toBeVisible();

    // Capability tags
    await expect(page.getByText("supervision")).toBeVisible();
    await expect(page.getByText("code-review")).toBeVisible();
    await expect(page.getByText("translation")).toBeVisible();
  });

  // -----------------------------------------------------------------------
  // 2. Status labels on each agent card
  // -----------------------------------------------------------------------
  test("shows correct status for each agent", async ({ page }) => {
    await goToSwarm(page);

    // Each agent card is a div.border-border that contains an h4 with the name.
    // Scope to the card by finding the h4 heading and then locating the parent card.
    const supervisorCard = page
      .getByRole("heading", { name: "Supervisor", level: 4 })
      .locator("xpath=ancestor::div[contains(@class,'border-border')][1]");
    await expect(supervisorCard.getByText("Running")).toBeVisible({
      timeout: 10000,
    });

    const reviewerCard = page
      .getByRole("heading", { name: "Code Reviewer", level: 4 })
      .locator("xpath=ancestor::div[contains(@class,'border-border')][1]");
    await expect(reviewerCard.getByText("Updating")).toBeVisible();

    const translatorCard = page
      .getByRole("heading", { name: "Translator", level: 4 })
      .locator("xpath=ancestor::div[contains(@class,'border-border')][1]");
    await expect(translatorCard.getByText("Stopped")).toBeVisible();
  });

  // -----------------------------------------------------------------------
  // 3. Stats row
  // -----------------------------------------------------------------------
  test("displays stats row with correct counts", async ({ page }) => {
    await goToSwarm(page);

    // The stats row uses small labels + big numbers.
    // "Running" (online): 1, "Updating" (busy): 1, "Stopped" (offline): 1, "Total Agents": 3
    // We verify by checking each label is visible and the corresponding count
    // appears near it.
    const statsRow = page.locator(".grid.grid-cols-2.md\\:grid-cols-4").first();

    // Running → 1
    await expect(statsRow.getByText("Running")).toBeVisible({ timeout: 10000 });
    await expect(statsRow.getByText("1").first()).toBeVisible();

    // Updating → 1
    await expect(statsRow.getByText("Updating")).toBeVisible();

    // Stopped → 1
    await expect(statsRow.getByText("Stopped")).toBeVisible();

    // Total Agents → 3
    await expect(statsRow.getByText("Total Agents")).toBeVisible();
    await expect(statsRow.getByText("3")).toBeVisible();
  });

  // -----------------------------------------------------------------------
  // 4. Redis health card
  // -----------------------------------------------------------------------
  test("shows Redis health card with details", async ({ page }) => {
    await goToSwarm(page);

    // "Connected" is the swarmConnected i18n key
    await expect(page.getByText("Connected")).toBeVisible({ timeout: 10000 });

    // Redis version from mock data
    await expect(page.getByText("7.2.0")).toBeVisible();

    // Latency value (1.2 ms from mock)
    await expect(page.getByText("1.2 ms")).toBeVisible();
  });

  // -----------------------------------------------------------------------
  // 5. Task throughput metrics
  // -----------------------------------------------------------------------
  test("shows task throughput metrics", async ({ page }) => {
    await goToSwarm(page);

    // "Last 5 min" heading
    await expect(page.getByText("Last 5 min")).toBeVisible({ timeout: 10000 });

    // Submitted → 12
    await expect(page.getByText("Submitted")).toBeVisible();
    await expect(page.getByText("12")).toBeVisible();

    // Completed → 10
    await expect(page.getByText("Completed")).toBeVisible();
    await expect(page.getByText("10")).toBeVisible();

    // Failed → 1
    await expect(page.getByText("Failed")).toBeVisible();

    // Queued → 3 (total_pending is 3)
    await expect(page.getByText("Queued")).toBeVisible();
    // The queued value sits in the same row; use the text near "Queued"
    const queuedRow = page.getByText("Queued").locator("..");
    await expect(queuedRow.getByText("3")).toBeVisible();
  });

  // -----------------------------------------------------------------------
  // 6. Queued count hidden when no pending tasks
  // -----------------------------------------------------------------------
  test("hides queued count when no pending tasks", async ({ page }) => {
    // Override the metrics mock with no-queue variant
    await mockApi(page, {
      "GET:/admin/api/swarm/capability": mockSwarmEnabled,
      "GET:/admin/api/swarm/agents": mockSwarmAgents,
      "GET:/admin/api/swarm/metrics": mockSwarmMetricsNoQueue,
      "GET:/admin/api/agents": { agents: [], total: 0 },
      "GET:/admin/api/cluster/status": {
        nodes: [],
        namespace: "hermes-agent",
        total_agents: 0,
        running_agents: 0,
      },
    });

    await goToSwarm(page);

    // The "Queued" text should NOT be present when total_pending is 0
    await expect(page.getByText("Queued")).not.toBeVisible();
  });

  // -----------------------------------------------------------------------
  // 7. Empty state when no agents
  // -----------------------------------------------------------------------
  test("shows empty state when no agents", async ({ page }) => {
    await mockApi(page, {
      "GET:/admin/api/swarm/capability": mockSwarmEnabled,
      "GET:/admin/api/swarm/agents": [],
      "GET:/admin/api/swarm/metrics": mockSwarmMetrics,
      "GET:/admin/api/agents": { agents: [], total: 0 },
      "GET:/admin/api/cluster/status": {
        nodes: [],
        namespace: "hermes-agent",
        total_agents: 0,
        running_agents: 0,
      },
    });

    await page.goto("/admin/swarm");
    await expect(
      page.getByText("No swarm agents registered")
    ).toBeVisible({ timeout: 10000 });
  });

  // -----------------------------------------------------------------------
  // 8. Redirect when capability returns false
  // -----------------------------------------------------------------------
  test("hides swarm when capability returns false", async ({ page }) => {
    await mockApi(page, {
      "GET:/admin/api/swarm/capability": mockSwarmDisabled,
      "GET:/admin/api/swarm/agents": mockSwarmAgents,
      "GET:/admin/api/swarm/metrics": mockSwarmMetrics,
      "GET:/admin/api/agents": { agents: [], total: 0 },
      "GET:/admin/api/cluster/status": {
        nodes: [],
        namespace: "hermes-agent",
        total_agents: 0,
        running_agents: 0,
      },
    });

    await page.goto("/admin/swarm");
    // SwarmGuard redirects to "/" (which is "/admin/" in the browser)
    await expect(page).toHaveURL(/\/admin\/?$/, { timeout: 10000 });
  });

  // -----------------------------------------------------------------------
  // 9. Load bar percentages
  // -----------------------------------------------------------------------
  test("shows load bar percentages", async ({ page }) => {
    await goToSwarm(page);

    // Code Reviewer card: 2/3 tasks → 67%
    const reviewerCard = page
      .getByRole("heading", { name: "Code Reviewer", level: 4 })
      .locator("xpath=ancestor::div[contains(@class,'border-border')][1]");
    await expect(reviewerCard.getByText(/Load:\s*2\/3/)).toBeVisible({
      timeout: 10000,
    });
    await expect(reviewerCard.getByText("67%")).toBeVisible();

    // Supervisor card: 0/5 tasks → 0%
    const supervisorCard = page
      .getByRole("heading", { name: "Supervisor", level: 4 })
      .locator("xpath=ancestor::div[contains(@class,'border-border')][1]");
    await expect(supervisorCard.getByText(/Load:\s*0\/5/)).toBeVisible();
    await expect(supervisorCard.getByText("0%")).toBeVisible();
  });

  // -----------------------------------------------------------------------
  // 10. Model info for each agent
  // -----------------------------------------------------------------------
  test("shows model info for each agent", async ({ page }) => {
    await goToSwarm(page);

    // Supervisor card shows "claude-sonnet"
    const supervisorCard = page
      .getByRole("heading", { name: "Supervisor", level: 4 })
      .locator("xpath=ancestor::div[contains(@class,'border-border')][1]");
    await expect(supervisorCard.getByText("claude-sonnet")).toBeVisible({
      timeout: 10000,
    });

    // Translator card shows "gpt-4o"
    const translatorCard = page
      .getByRole("heading", { name: "Translator", level: 4 })
      .locator("xpath=ancestor::div[contains(@class,'border-border')][1]");
    await expect(translatorCard.getByText("gpt-4o")).toBeVisible();
  });
});
