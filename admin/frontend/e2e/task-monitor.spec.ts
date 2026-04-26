import { test, expect } from "@playwright/test";

// ---------------------------------------------------------------------------
// Shared mock data
// ---------------------------------------------------------------------------

const AGENTS = [
  {
    agent_id: 1,
    display_name: "Supervisor",
    capabilities: ["supervision"],
    status: "online",
    current_tasks: 0,
    max_concurrent_tasks: 5,
    last_heartbeat: Math.floor(Date.now() / 1000),
    model: "claude-sonnet",
  },
  {
    agent_id: 3,
    display_name: "Reviewer",
    capabilities: ["code-review"],
    status: "busy",
    current_tasks: 2,
    max_concurrent_tasks: 3,
    last_heartbeat: Math.floor(Date.now() / 1000),
    model: "claude-sonnet",
  },
];

const TASK_COMPLETED = {
  task_id: "task_abc0000000000001",
  task_type: "code-review",
  goal: "Review agent_manager.py",
  status: "completed",
  sender_id: 1,
  assigned_agent_id: 3,
  duration_ms: 4500,
  error: "",
  timestamp: Math.floor(Date.now() / 1000) - 300,
};

const TASK_FAILED = {
  task_id: "task_abc0000000000002",
  task_type: "code-review",
  goal: "Review models.py",
  status: "failed",
  sender_id: 1,
  assigned_agent_id: 3,
  duration_ms: 1200,
  error: "LLM timeout",
  timestamp: Math.floor(Date.now() / 1000) - 200,
};

const TASK_RUNNING = {
  task_id: "task_abc0000000000003",
  task_type: "code-gen",
  goal: "Write unit tests",
  status: "running",
  sender_id: 1,
  assigned_agent_id: 3,
  duration_ms: null,
  error: "",
  timestamp: Math.floor(Date.now() / 1000) - 60,
};

const ALL_TASKS = [TASK_COMPLETED, TASK_FAILED, TASK_RUNNING];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Task Monitor", () => {
  test.beforeEach(async ({ page }) => {
    // Auth
    await page.route("**/admin/api/login", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ success: true }),
      });
    });

    // Swarm capability flag
    await page.route("**/admin/api/swarm/capability", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ enabled: true }),
      });
    });

    // Swarm agents list
    await page.route("**/admin/api/swarm/agents", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(AGENTS),
      });
    });

    // Swarm tasks list
    await page.route("**/admin/api/swarm/tasks", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(ALL_TASKS),
      });
    });

    // SSE token endpoint
    await page.route("**/admin/api/swarm/events/token", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ token: "sse_test_token", expires_in: 1800 }),
      });
    });

    // SSE stream — send a heartbeat and keep open
    await page.route("**/admin/api/swarm/events/stream**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "event: heartbeat\ndata: {}\n\n",
      });
    });

    // AdminLayout dependencies
    await page.route("**/admin/api/agents", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ agents: [], total: 0 }),
      });
    });
    await page.route("**/admin/api/cluster/status", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          nodes: [],
          namespace: "hermes-agent",
          total_agents: 0,
          running_agents: 0,
        }),
      });
    });

    // Set auth key in localStorage
    await page.goto("/admin/login");
    await page.evaluate(() => {
      localStorage.setItem("admin_api_key", "test-admin-key-1234");
    });
  });

  test("shows task list with correct rows", async ({ page }) => {
    await page.goto("/admin/swarm/tasks");

    await expect(page.getByText("Review agent_manager.py")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText("Review models.py")).toBeVisible();
    await expect(page.getByText("Write unit tests")).toBeVisible();
  });

  test("filter buttons work", async ({ page }) => {
    await page.goto("/admin/swarm/tasks");

    // Wait for tasks to render
    await expect(page.getByText("Review agent_manager.py")).toBeVisible({
      timeout: 10000,
    });

    // Click the "Failed" filter button (i18n-aware)
    await page.getByRole("tab", { name: /Failed|已失败/ }).click();

    // Only the failed task should be visible
    await expect(page.getByText("Review models.py")).toBeVisible();
    await expect(page.getByText("Review agent_manager.py")).not.toBeVisible();
  });

  test("navigates to task detail on row click", async ({ page }) => {
    // Mock the individual task detail endpoint
    await page.route(
      "**/admin/api/swarm/tasks/task_abc0000000000001",
      async (route) => {
        await route.fulfill({
          status: 200,
          body: JSON.stringify(TASK_COMPLETED),
        });
      },
    );

    await page.goto("/admin/swarm/tasks");

    // Wait for tasks to render
    await expect(page.getByText("Review agent_manager.py")).toBeVisible({
      timeout: 10000,
    });

    // Click on the completed task row
    await page.getByText("Review agent_manager.py").click();

    // Should navigate to task detail page
    await expect(page).toHaveURL(/\/admin\/swarm\/tasks\//, {
      timeout: 10000,
    });

    // Duration: 4500ms → formatted as "4s" by formatDuration
    await expect(page.getByText("4s")).toBeVisible();
  });

  test("task detail shows error for failed tasks", async ({ page }) => {
    // Mock the individual task detail endpoint for the failed task
    await page.route(
      "**/admin/api/swarm/tasks/task_abc0000000000002",
      async (route) => {
        await route.fulfill({
          status: 200,
          body: JSON.stringify(TASK_FAILED),
        });
      },
    );

    // Navigate directly to the failed task detail page
    await page.goto("/admin/swarm/tasks/task_abc0000000000002");

    // The error message should be visible
    await expect(page.getByText("LLM timeout")).toBeVisible({
      timeout: 10000,
    });
  });
});
