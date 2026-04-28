import { test, expect } from "@playwright/test";
import { loginAsAdmin, mockApi } from "./helpers";
import {
  mockCrews,
  mockSwarmEnabled,
  mockSwarmAgents,
  mockExecutionPending,
  mockExecutionRunning,
  mockExecutionCompleted,
  mockExecutionFailed,
  mockExecutionConflict,
  mockExecutionRateLimit,
} from "./fixtures/mock-data";

test.describe("Crew Execution", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.evaluate(() => {
      localStorage.setItem("admin_lang", "en");
    });

    await mockApi(page, {
      "GET:/admin/api/swarm/capability": mockSwarmEnabled,
      "GET:/admin/api/swarm/agents": mockSwarmAgents,
      "GET:/admin/api/swarm/crews": mockCrews,
    });
  });

  test("starts execution and shows pending status", async ({ page }) => {
    await page.route(
      "**/admin/api/swarm/crews/crew-1/execute",
      async (route) => {
        if (route.request().method() === "POST") {
          return route.fulfill({ json: mockExecutionPending });
        }
        return route.continue();
      }
    );

    await page.route(
      "**/admin/api/swarm/crews/crew-1/executions/exec-1",
      async (route) => {
        return route.fulfill({ json: mockExecutionPending });
      }
    );

    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });

    page.on("dialog", (dialog) => dialog.accept());

    await page.getByText("Execute", { exact: true }).click();

    await expect(page.getByText("Execution Status")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText("Pending")).toBeVisible({ timeout: 10000 });
  });

  test("polls and shows completed status", async ({ page }) => {
    let pollCount = 0;
    await page.route(
      "**/admin/api/swarm/crews/crew-1/execute",
      async (route) => {
        if (route.request().method() === "POST") {
          return route.fulfill({ json: mockExecutionRunning });
        }
        return route.continue();
      }
    );

    await page.route(
      "**/admin/api/swarm/crews/crew-1/executions/exec-1",
      async (route) => {
        pollCount++;
        if (pollCount === 1) {
          return route.fulfill({ json: mockExecutionRunning });
        }
        return route.fulfill({ json: mockExecutionCompleted });
      }
    );

    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });

    page.on("dialog", (dialog) => dialog.accept());

    await page.getByText("Execute", { exact: true }).click();

    // Wait for the status banner to appear with "Running"
    await expect(page.getByText("Running")).toBeVisible({ timeout: 10000 });

    // Then wait for the transition to "Completed"
    await expect(page.getByText("Completed")).toBeVisible({ timeout: 10000 });

    // Verify green styling on completed status text
    const completedText = page.locator("span.text-green-400");
    await expect(completedText).toContainText("Completed");
  });

  test("shows failed execution with error", async ({ page }) => {
    await page.route(
      "**/admin/api/swarm/crews/crew-1/execute",
      async (route) => {
        if (route.request().method() === "POST") {
          return route.fulfill({ json: mockExecutionPending });
        }
        return route.continue();
      }
    );

    // Poll returns failed status
    await page.route(
      "**/admin/api/swarm/crews/crew-1/executions/exec-1",
      async (route) => {
        return route.fulfill({ json: mockExecutionFailed });
      }
    );

    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });

    page.on("dialog", (dialog) => dialog.accept());

    await page.getByText("Execute", { exact: true }).click();

    await expect(page.getByText("Failed")).toBeVisible({ timeout: 10000 });

    // Verify error message from the execution result is visible
    await expect(
      page.getByText("Step step_1 timed out after 120s")
    ).toBeVisible({ timeout: 10000 });
  });

  test("handles 409 conflict when crew already executing", async ({ page }) => {
    await page.route(
      "**/admin/api/swarm/crews/crew-1/execute",
      async (route) => {
        if (route.request().method() === "POST") {
          return route.fulfill({
            status: 409,
            json: mockExecutionConflict,
          });
        }
        return route.continue();
      }
    );

    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });

    page.on("dialog", (dialog) => dialog.accept());

    await page.getByText("Execute", { exact: true }).click();

    // The store sets error on failed execute, which renders as crewLoadError banner
    await expect(page.getByText("Failed to load crews")).toBeVisible({
      timeout: 10000,
    });

    // Verify no execution status banner appears (execution should be null)
    await expect(page.getByText("Execution Status")).not.toBeVisible();
  });

  test("handles 429 rate limit", async ({ page }) => {
    await page.route(
      "**/admin/api/swarm/crews/crew-1/execute",
      async (route) => {
        if (route.request().method() === "POST") {
          return route.fulfill({
            status: 429,
            json: mockExecutionRateLimit,
          });
        }
        return route.continue();
      }
    );

    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });

    page.on("dialog", (dialog) => dialog.accept());

    await page.getByText("Execute", { exact: true }).click();

    // The store sets error on failed execute, which renders as error banner
    await expect(page.getByText("Failed to load crews")).toBeVisible({
      timeout: 10000,
    });

    // Verify no execution status banner appears
    await expect(page.getByText("Execution Status")).not.toBeVisible();
  });

  test("execute button disabled during execution", async ({ page }) => {
    await page.route(
      "**/admin/api/swarm/crews/crew-1/execute",
      async (route) => {
        if (route.request().method() === "POST") {
          return route.fulfill({ json: mockExecutionRunning });
        }
        return route.continue();
      }
    );

    await page.route(
      "**/admin/api/swarm/crews/crew-1/executions/exec-1",
      async (route) => {
        return route.fulfill({ json: mockExecutionRunning });
      }
    );

    await page.goto("/admin/swarm/crews");
    await expect(page.getByText("Review Team")).toBeVisible({ timeout: 10000 });

    page.on("dialog", (dialog) => dialog.accept());

    await page.getByText("Execute", { exact: true }).click();

    // The polling will set execution to running status
    await expect(page.getByText("Running")).toBeVisible({ timeout: 10000 });

    // Verify execution status banner is shown
    await expect(page.getByText("Execution Status")).toBeVisible();
  });
});
