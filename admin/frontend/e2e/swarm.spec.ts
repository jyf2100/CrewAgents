import { test, expect } from "@playwright/test";

test.describe("Swarm Overview", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/admin/api/login", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ success: true }) });
    });
    await page.route("**/admin/api/swarm/capability", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ enabled: true }) });
    });
    await page.route("**/admin/api/swarm/agents", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify([
          { agent_id: 1, display_name: "Supervisor", capabilities: ["supervision"], status: "online", current_tasks: 0, max_concurrent_tasks: 5, last_heartbeat: Date.now() / 1000, model: "claude-sonnet" },
          { agent_id: 3, display_name: "Code Reviewer", capabilities: ["code-review", "refactoring"], status: "busy", current_tasks: 2, max_concurrent_tasks: 3, last_heartbeat: Date.now() / 1000, model: "claude-sonnet" },
        ]),
      });
    });
    await page.route("**/admin/api/swarm/metrics", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          timestamp: Date.now() / 1000, swarm_enabled: true,
          agents: [], agents_online: 1, agents_offline: 0, agents_busy: 1,
          queues: { streams: [], total_pending: 0 },
          redis_health: { connected: true, latency_ms: 1.2, memory_used_percent: 5.3, connected_clients: 3, uptime_seconds: 86400, aof_enabled: true, version: "7.2.0" },
          tasks_submitted_last_5m: 0, tasks_completed_last_5m: 0, tasks_failed_last_5m: 0,
        }),
      });
    });
    // Default mocks for cluster/agents needed by AdminLayout
    await page.route("**/admin/api/agents", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ agents: [], total: 0 }) });
    });
    await page.route("**/admin/api/cluster/status", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ nodes: [], namespace: "hermes-agent", total_agents: 0, running_agents: 0 }) });
    });
  });

  test("shows swarm overview with agent cards", async ({ page }) => {
    // Set auth key
    await page.goto("/admin/login");
    await page.evaluate(() => {
      localStorage.setItem("admin_api_key", "test-admin-key-1234");
    });

    await page.goto("/admin/swarm");
    await expect(page.getByText("Supervisor")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Code Reviewer")).toBeVisible();
  });

  test("shows Redis health card", async ({ page }) => {
    await page.goto("/admin/login");
    await page.evaluate(() => {
      localStorage.setItem("admin_api_key", "test-admin-key-1234");
    });

    await page.goto("/admin/swarm");
    await expect(page.getByText(/Connected|已连接/)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("7.2.0")).toBeVisible();
  });

  test("hides swarm when capability returns false", async ({ page }) => {
    await page.route("**/admin/api/swarm/capability", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ enabled: false }) });
    });

    await page.goto("/admin/login");
    await page.evaluate(() => {
      localStorage.setItem("admin_api_key", "test-admin-key-1234");
    });

    await page.goto("/admin/swarm");
    await expect(page).toHaveURL(/\/admin\/?$/, { timeout: 10000 });
  });
});
