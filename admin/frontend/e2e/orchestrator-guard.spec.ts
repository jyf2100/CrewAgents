import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("redirects to dashboard when orchestrator is disabled", async ({ page }) => {
  await page.route("**/admin/api/orchestrator/capability", (route) =>
    route.fulfill({ json: { enabled: false } })
  );
  await page.route("**/admin/api/agents", (route) =>
    route.fulfill({ json: { agents: [], total: 0 } })
  );
  await page.route("**/admin/api/cluster/status", (route) =>
    route.fulfill({ json: { nodes: [] } })
  );
  await loginAsAdmin(page);
  await page.goto("/admin/orchestrator");
  await expect(page).toHaveURL(/\/admin\/$/);
});
