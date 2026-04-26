import { test, expect } from "@playwright/test";
import {
  VALID_ADMIN_KEY,
  mockAgentDetail,
  mockClusterStatus,
  mockEnvVars,
  mockConfigYaml,
  mockSoul,
  mockHealth,
  mockEvents,
  mockWeixinStatusConnected,
  mockWeixinStatusNotConnected,
  mockActionResponse,
  mockMessageResponse,
} from "./fixtures/mock-data";
import { loginAsAdmin } from "./helpers";

test.describe("Agent Detail", () => {
  async function goToDetail(page, tab = "overview") {
    await page.route("**/admin/api/agents/1", (route) =>
      route.fulfill({ json: mockAgentDetail })
    );
    await page.route("**/admin/api/agents/1/env", (route) =>
      route.fulfill({ json: mockEnvVars })
    );
    await page.route("**/admin/api/agents/1/config", (route) =>
      route.fulfill({ json: mockConfigYaml })
    );
    await page.route("**/admin/api/agents/1/soul", (route) =>
      route.fulfill({ json: mockSoul })
    );
    await page.route("**/admin/api/agents/1/health", (route) =>
      route.fulfill({ json: mockHealth })
    );
    await page.route("**/admin/api/agents/1/events", (route) =>
      route.fulfill({ json: mockEvents })
    );
    await page.route("**/admin/api/agents/1/weixin/status", (route) =>
      route.fulfill({ json: mockWeixinStatusConnected })
    );
    await loginAsAdmin(page);
    await page.goto(`/admin/agents/1?tab=${tab}`);
  }

  test("shows agent name and status in header", async ({ page }) => {
    await goToDetail(page);
    await expect(page.getByRole("heading", { name: /hermes-gateway-1/ })).toBeVisible();
  });

  test("shows tab bar with all tabs", async ({ page }) => {
    await goToDetail(page);
    await expect(page.getByText("概览")).toBeVisible();
    await expect(page.getByText("K8s Events")).toBeVisible();
  });

  test("overview tab shows resource usage", async ({ page }) => {
    await goToDetail(page, "overview");
    await expect(page.getByText(/CPU|cpu/i).first()).toBeVisible();
    await expect(page.getByText(/内存|Memory/i).first()).toBeVisible();
  });

  test("overview tab shows WeChat card when connected", async ({ page }) => {
    await goToDetail(page, "overview");
    await expect(page.getByText(/微信|WeChat/i)).toBeVisible();
    await expect(page.getByText(/wx_abc/)).toBeVisible();
  });

  test("overview tab shows Register button when not connected", async ({ page }) => {
    await page.route("**/admin/api/agents/1", (route) =>
      route.fulfill({ json: mockAgentDetail })
    );
    await page.route("**/admin/api/agents/1/weixin/status", (route) =>
      route.fulfill({ json: mockWeixinStatusNotConnected })
    );
    await loginAsAdmin(page);
    await page.goto("/admin/agents/1?tab=overview");
    await expect(page.getByText(/注册|Register/i)).toBeVisible();
  });

  test("config tab shows env form editor", async ({ page }) => {
    await goToDetail(page, "config");
    // Config tab should show sub-tabs: .env, config.yaml, SOUL.md
    await expect(page.getByText(".env")).toBeVisible();
    await expect(page.getByText("config.yaml")).toBeVisible();
    await expect(page.getByText("SOUL.md")).toBeVisible();
  });

  test("restart button calls API", async ({ page }) => {
    let restartCalled = false;
    await page.route("**/admin/api/agents/1/restart", (route) => {
      restartCalled = true;
      return route.fulfill({ json: mockActionResponse("restart") });
    });
    await goToDetail(page);
    await page.getByText(/重启|Restart/).first().click();
    await expect(() => expect(restartCalled).toBe(true)).toPass();
  });

  test("back button navigates to dashboard", async ({ page }) => {
    await goToDetail(page);
    await page.getByText("←").click();
    await expect(page).toHaveURL(/\/admin/);
  });

  test("events tab shows event table", async ({ page }) => {
    await goToDetail(page, "events");
    await expect(page.getByText("Normal")).toBeVisible();
    await expect(page.getByText("Started container")).toBeVisible();
  });

  test("health tab shows health status", async ({ page }) => {
    await goToDetail(page, "health");
    await expect(page.getByText("正常")).toBeVisible();
  });
});
