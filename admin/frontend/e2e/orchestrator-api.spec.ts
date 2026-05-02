import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("orchestrator capability check", async ({ page }) => {
  await page.route("**/admin/api/orchestrator/capability", (route) =>
    route.fulfill({ json: { enabled: true } })
  );
  await loginAsAdmin(page);
  await page.goto("/admin/");
});
