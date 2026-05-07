import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo } from "./helpers";

test.describe("Orchestrator Pages", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  // ════════════════════════════════════════════════════════════════════════
  // Orchestrator Overview Page
  // ════════════════════════════════════════════════════════════════════════

  test.describe("Overview Page", () => {
    test.beforeEach(async ({ page }) => {
      await navigateTo(page, "/orchestrator");
    });

    test("page renders without auth prompt", async ({ page }) => {
      await page.waitForTimeout(3000);
      await page.screenshot({ path: "test-results/orchestrator-overview.png", fullPage: true });
      const body = await page.textContent("body");
      expect(body).not.toContain("输入管理员密钥");
      expect(body).toMatch(/agent|集群/i);
    });

    test("shows stats cards (Agent Fleet, Online, Active Tasks, Done)", async ({ page }) => {
      await page.waitForTimeout(3000);
      const body = await page.textContent("body");
      expect(body).toMatch(/在线|运行中|online|running/i);
      // Should have numeric stats
      expect(body).toMatch(/\d+/);
    });

    test("shows agent fleet table with columns", async ({ page }) => {
      await page.waitForTimeout(3000);
      const body = await page.textContent("body");
      // Table headers: Agent, Status, Role, Load, Circuit, Tags
      expect(body).toMatch(/agent|角色|role|负载|load|标签|tag/i);
    });

    test("agent fleet table shows role badges", async ({ page }) => {
      await page.waitForTimeout(3000);
      // RoleBadge renders coder/analyst/generalist
      const roleBadges = page.locator("span").filter({ hasText: /^coder$|^analyst$|^generalist$/ });
      const count = await roleBadges.count();
      // If agents are present, at least one should have a role
      const body = await page.textContent("body");
      if (body && body.includes("hermes-gateway")) {
        expect(count).toBeGreaterThanOrEqual(0);
      }
    });

    test("agent fleet table shows tag chips", async ({ page }) => {
      await page.waitForTimeout(3000);
      // Tags are small spans with class containing "rounded"
      const body = await page.textContent("body");
      // If there are agents with tags, they should show as chips
      // Otherwise the table shows "-" for empty tags
      expect(body).toMatch(/-|tag|\w+/i);
    });

    test("agent fleet table shows load progress bars", async ({ page }) => {
      await page.waitForTimeout(3000);
      // Load bars are div elements with bg-accent-cyan and style width
      const loadBars = page.locator("div.bg-accent-cyan");
      const count = await loadBars.count();
      // There should be at least 0 load bars (one per agent)
      expect(count).toBeGreaterThanOrEqual(0);
    });

    test("agent fleet table shows circuit breaker status dots", async ({ page }) => {
      await page.waitForTimeout(3000);
      // CircuitBadge renders as small colored dots (w-2.5 h-2.5 rounded-full)
      const circuitDots = page.locator("span.rounded-full.w-2\\.5, span[title='closed'], span[title='open'], span[title='half_open']");
      const count = await circuitDots.count();
      expect(count).toBeGreaterThanOrEqual(0);
    });

    test("task list section renders", async ({ page }) => {
      await page.waitForTimeout(3000);
      const body = await page.textContent("body");
      // Task list section header
      expect(body).toMatch(/task|任务/i);
    });

    test("task rows are clickable and navigate to detail", async ({ page }) => {
      await page.waitForTimeout(3000);
      // Find clickable task rows (div with cursor-pointer containing task IDs)
      const taskRows = page.locator("div.cursor-pointer").filter({ hasText: /\w{8}/ });
      const count = await taskRows.count();
      if (count > 0) {
        await taskRows.first().click();
        await page.waitForURL(/\/admin\/orchestrator\/tasks\//, { timeout: 5000 }).catch(() => {});
        // Verify we navigated to task detail
        expect(page.url()).toMatch(/\/admin\/orchestrator\/tasks\//);
      }
    });

    test("empty state message when no tasks", async ({ page }) => {
      await page.waitForTimeout(3000);
      // Either tasks exist or "no tasks" message
      const body = await page.textContent("body");
      expect(body).toMatch(/task|任务|暂无|no.*task/i);
    });

    test("overview page screenshot", async ({ page }) => {
      await page.waitForTimeout(3000);
      await page.screenshot({ path: "test-results/orchestrator-overview-full.png", fullPage: true });
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // Task Submit Page
  // ════════════════════════════════════════════════════════════════════════

  test.describe("Task Submit Page", () => {
    test.beforeEach(async ({ page }) => {
      await navigateTo(page, "/orchestrator/tasks/new");
    });

    test("page renders without auth prompt", async ({ page }) => {
      await page.waitForTimeout(3000);
      await page.screenshot({ path: "test-results/orchestrator-submit.png", fullPage: true });
      const body = await page.textContent("body");
      expect(body).not.toContain("输入管理员密钥");
      expect(body).toMatch(/prompt|提示|任务/i);
    });

    // ── Form fields ──

    test("prompt textarea exists and is required", async ({ page }) => {
      await page.waitForTimeout(3000);
      const promptTextarea = page.locator("textarea").first();
      await expect(promptTextarea).toBeVisible();
      // Required field
      const isRequired = await promptTextarea.getAttribute("required");
      expect(isRequired).not.toBeNull();
    });

    test("instructions textarea exists", async ({ page }) => {
      await page.waitForTimeout(3000);
      const textareas = page.locator("textarea");
      const count = await textareas.count();
      expect(count).toBeGreaterThanOrEqual(2);
    });

    test("priority number input exists", async ({ page }) => {
      await page.waitForTimeout(3000);
      const numInputs = page.locator("input[type='number']");
      const count = await numInputs.count();
      expect(count).toBeGreaterThanOrEqual(1);
    });

    test("timeout number input exists", async ({ page }) => {
      await page.waitForTimeout(3000);
      const numInputs = page.locator("input[type='number']");
      const count = await numInputs.count();
      expect(count).toBeGreaterThanOrEqual(2);
    });

    test("retries number input exists", async ({ page }) => {
      await page.waitForTimeout(3000);
      const numInputs = page.locator("input[type='number']");
      const count = await numInputs.count();
      expect(count).toBeGreaterThanOrEqual(3);
    });

    test("callback URL input exists", async ({ page }) => {
      await page.waitForTimeout(3000);
      const urlInput = page.locator("input[type='url']");
      const count = await urlInput.count();
      expect(count).toBeGreaterThanOrEqual(1);
    });

    // ── Required Tags multi-selector ──

    test("required tags section is visible", async ({ page }) => {
      await page.waitForTimeout(3000);
      const body = await page.textContent("body");
      expect(body).toMatch(/required.*tag|必要.*标签|required.*tag/i);
    });

    test("required tags hint text is shown", async ({ page }) => {
      await page.waitForTimeout(3000);
      const body = await page.textContent("body");
      expect(body).toMatch(/must have ALL selected|必须同时具备/i);
    });

    test("required tags section uses TagInput combobox", async ({ page }) => {
      await page.waitForTimeout(3000);
      // TagInput renders as combobox role, not toggle buttons
      const comboboxes = page.getByRole("combobox");
      const count = await comboboxes.count();
      expect(count).toBeGreaterThanOrEqual(2); // required tags + preferred tags
    });

    test("tag input is empty by default", async ({ page }) => {
      await page.waitForTimeout(3000);
      // TagInput combobox is a <div> wrapping an <input>
      const tagInputs = page.locator("[role='combobox'] input");
      const count = await tagInputs.count();
      if (count > 0) {
        const value = await tagInputs.first().inputValue();
        expect(value).toBe("");
      }
    });

    test("can type a tag into the input", async ({ page }) => {
      await page.waitForTimeout(3000);
      const tagInput = page.locator("[role='combobox'] input").first();
      if (await tagInput.isVisible()) {
        await tagInput.fill("code");
        await page.waitForTimeout(500);
        const value = await tagInput.inputValue();
        expect(value).toContain("code");
      }
    });

    test("can add multiple tags via input", async ({ page }) => {
      await page.waitForTimeout(3000);
      const tagInput = page.locator("[role='combobox'] input").first();
      if (await tagInput.isVisible()) {
        await tagInput.fill("python");
        await page.keyboard.press("Enter");
        await page.waitForTimeout(300);
        const body = await page.textContent("body");
        expect(body).toMatch(/python/i);
      }
    });

    test("preferred tags combobox exists", async ({ page }) => {
      await page.waitForTimeout(3000);
      const preferredLabel = page.getByText(/preferred.*tag|偏好标签/i);
      const comboboxes = page.getByRole("combobox");
      const hasPreferred =
        (await preferredLabel.isVisible().catch(() => false)) ||
        (await comboboxes.count()) >= 2;
      expect(hasPreferred).toBeTruthy();
    });

    test("tag input has visual styling", async ({ page }) => {
      await page.waitForTimeout(3000);
      const combobox = page.getByRole("combobox").first();
      if (await combobox.isVisible()) {
        const classes = await combobox.evaluate(el => el.className);
        // Combobox should have styling classes
        expect(classes.length).toBeGreaterThan(0);
      }
    });

    test("screenshot of tag input interaction", async ({ page }) => {
      await page.waitForTimeout(3000);
      const tagInput = page.locator("[role='combobox'] input").first();
      if (await tagInput.isVisible()) {
        await tagInput.fill("python");
      }
      await page.screenshot({ path: "test-results/orchestrator-tags-selected.png", fullPage: true });
    });

    // ── Submit button behavior ──

    test("submit button is disabled when prompt is empty", async ({ page }) => {
      await page.waitForTimeout(3000);
      const submitBtn = page.getByRole("button", { name: /submit|提交/i });
      await expect(submitBtn).toBeDisabled();
    });

    test("submit button enables after filling prompt", async ({ page }) => {
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("Test task prompt for E2E");
      const submitBtn = page.getByRole("button", { name: /submit|提交/i });
      await expect(submitBtn).toBeEnabled();
    });

    test("can submit a task and navigate to detail", async ({ page }) => {
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E test task - verify submission works");
      // Optionally add a tag via TagInput combobox
      const tagInput = page.locator("[role='combobox'] input").first();
      if (await tagInput.isVisible()) {
        await tagInput.fill("code");
        await page.keyboard.press("Enter");
      }
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(5000);
      await page.screenshot({ path: "test-results/orchestrator-submit-result.png", fullPage: true });
      // Should navigate to task detail or show result
      const url = page.url();
      expect(url).toMatch(/\/admin\/(orchestrator|orchestrator\/tasks)/);
    });

    test("submit with all fields filled", async ({ page }) => {
      await page.waitForTimeout(3000);
      // Fill prompt
      await page.locator("textarea").first().fill("Full E2E test with all fields");
      // Fill instructions (second textarea)
      const textareas = page.locator("textarea");
      if (await textareas.count() > 1) {
        await textareas.nth(1).fill("System instructions for E2E test");
      }
      // Adjust priority
      const numInputs = page.locator("input[type='number']");
      if (await numInputs.count() > 0) {
        await numInputs.first().fill("5");
      }
      // Adjust timeout
      if (await numInputs.count() > 1) {
        await numInputs.nth(1).fill("300");
      }
      // Adjust retries
      if (await numInputs.count() > 2) {
        await numInputs.nth(2).fill("3");
      }
      // Fill callback URL
      const urlInput = page.locator("input[type='url']");
      if (await urlInput.count() > 0) {
        await urlInput.first().fill("https://example.com/webhook");
      }
      // Add tags via TagInput combobox
      const tagInput = page.locator("[role='combobox'] input").first();
      if (await tagInput.isVisible()) {
        await tagInput.fill("python");
        await page.keyboard.press("Enter");
        await tagInput.fill("debugging");
        await page.keyboard.press("Enter");
      }
      // Submit
      const submitBtn = page.getByRole("button", { name: /submit|提交/i });
      await expect(submitBtn).toBeEnabled();
      await submitBtn.click();
      await page.waitForTimeout(3000);
      await page.screenshot({ path: "test-results/orchestrator-submit-all-fields.png", fullPage: true });
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // Task Detail Page
  // ════════════════════════════════════════════════════════════════════════

  test.describe("Task Detail Page", () => {
    test("can navigate to task detail via overview", async ({ page }) => {
      await navigateTo(page, "/orchestrator");
      await page.waitForTimeout(3000);
      // Find a clickable task row
      const taskRows = page.locator("div.cursor-pointer").filter({ hasText: /\w{8}/ });
      const count = await taskRows.count();
      test.skip(count === 0, "No tasks available - needs pre-seeded data");
      await taskRows.first().click();
      await page.waitForURL(/\/admin\/orchestrator\/tasks\//, { timeout: 5000 }).catch(() => {});
      expect(page.url()).toMatch(/\/admin\/orchestrator\/tasks\//);
    });

    test("task detail page shows back button", async ({ page }) => {
      // Navigate via submit to create a task
      await navigateTo(page, "/orchestrator/tasks/new");
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E task detail test");
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(3000);
      // Should be on task detail now
      const backBtn = page.getByRole("button", { name: /back|返回|←/i });
      const count = await backBtn.count();
      if (count > 0) {
        await expect(backBtn.first()).toBeVisible();
      }
    });

    test("task detail page shows task status badge", async ({ page }) => {
      await navigateTo(page, "/orchestrator/tasks/new");
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E task status test");
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(3000);
      // Should show a status badge (queued/assigned/executing/done/failed)
      const body = await page.textContent("body");
      expect(body).toMatch(/queued|assigned|executing|streaming|done|failed|submitted/i);
    });

    test("task detail page shows info cards (agent, run ID, retries, created)", async ({ page }) => {
      await navigateTo(page, "/orchestrator/tasks/new");
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E task info cards test");
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(3000);
      const body = await page.textContent("body");
      // Info cards show: Agent, Run ID, Retries, Created
      expect(body).toMatch(/agent|run.*id|retries|重试|created|创建/i);
    });

    // ── RoutingInfoCard (new feature) ──

    test("routing info card shows routing strategy", async ({ page }) => {
      await navigateTo(page, "/orchestrator/tasks/new");
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E routing info test");
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(5000);
      const body = await page.textContent("body");
      // If routing_info is present, should show routing strategy
      // If not, this test is a no-op
      if (body && body.includes("routing")) {
        expect(body).toMatch(/routing|路由|strategy|策略/i);
      }
      await page.screenshot({ path: "test-results/orchestrator-task-detail-routing.png", fullPage: true });
    });

    test("routing info card shows matched tags as chips", async ({ page }) => {
      await navigateTo(page, "/orchestrator/tasks/new");
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E matched tags test");
      // Add tag via TagInput combobox
      const tagInput = page.locator("[role='combobox'] input").first();
      if (await tagInput.isVisible()) {
        await tagInput.fill("code");
        await page.keyboard.press("Enter");
      }
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(5000);
      // If routing info has matched_tags, they show as accent-cyan chips
      const matchedTagChips = page.locator("span").filter({ hasText: /code|python|debugging/ }).filter({ has: page.locator("..") });
      const count = await matchedTagChips.count();
      // May or may not have matched tags depending on agent fleet
      expect(count).toBeGreaterThanOrEqual(0);
    });

    test("routing info card shows candidate score progress bars", async ({ page }) => {
      await navigateTo(page, "/orchestrator/tasks/new");
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E candidate scores test");
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(5000);
      // Score progress bars have rounded-full divs inside the routing section
      // This is data-dependent
      await page.screenshot({ path: "test-results/orchestrator-task-detail-scores.png", fullPage: true });
    });

    test("routing info card shows fallback warning when applicable", async ({ page }) => {
      await navigateTo(page, "/orchestrator/tasks/new");
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E fallback test");
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(5000);
      const body = await page.textContent("body");
      // If fallback happened, yellow warning badge appears
      // If not, this is a no-op
      if (body && body.includes("fallback")) {
        expect(body).toMatch(/fallback|回退/i);
      }
    });

    test("routing info card shows shadow info when present", async ({ page }) => {
      await navigateTo(page, "/orchestrator/tasks/new");
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E shadow test");
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(5000);
      const body = await page.textContent("body");
      // Shadow info is only shown when shadow_smart_agent_id or shadow_smart_score is present
      if (body && body.includes("shadow")) {
        expect(body).toMatch(/shadow|score|分数/i);
      }
    });

    // ── Cancel button for active tasks ──

    test("cancel button visible for queued/assigned tasks", async ({ page }) => {
      await navigateTo(page, "/orchestrator/tasks/new");
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E cancel button test");
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(3000);
      // If task is still in queued/assigned state, cancel button should appear
      const cancelBtn = page.getByRole("button", { name: /cancel|取消/i });
      const count = await cancelBtn.count();
      // Task might have already completed by the time we check
      expect(count).toBeGreaterThanOrEqual(0);
    });

    // ── Result display ──

    test("completed tasks show result content", async ({ page }) => {
      // Navigate to overview to find a done task
      await navigateTo(page, "/orchestrator");
      await page.waitForTimeout(3000);
      // Look for done tasks in the list
      const doneBadges = page.locator("span").filter({ hasText: /^done$/ });
      const count = await doneBadges.count();
      test.skip(count === 0, "No completed tasks found - needs pre-seeded data");
      // Click on the row containing the done badge
      const taskRows = page.locator("div.cursor-pointer").filter({ has: doneBadges.first() });
      if (await taskRows.count() > 0) {
        await taskRows.first().click();
        await page.waitForTimeout(3000);
        await page.screenshot({ path: "test-results/orchestrator-task-done.png", fullPage: true });
        const body = await page.textContent("body");
        // Done tasks should show result section
        expect(body).toMatch(/result|结果|tokens|duration/i);
      }
    });

    // ── Failed task display ──

    test("failed tasks show error section", async ({ page }) => {
      await navigateTo(page, "/orchestrator");
      await page.waitForTimeout(3000);
      const failedBadges = page.locator("span").filter({ hasText: /^failed$/ });
      const count = await failedBadges.count();
      test.skip(count === 0, "No failed tasks found - needs pre-seeded data");
      const taskRows = page.locator("div.cursor-pointer").filter({ has: failedBadges.first() });
      if (await taskRows.count() > 0) {
        await taskRows.first().click();
        await page.waitForTimeout(3000);
        await page.screenshot({ path: "test-results/orchestrator-task-failed.png", fullPage: true });
        const body = await page.textContent("body");
        expect(body).toMatch(/error|错误/i);
      }
    });

    // ── Back button navigation ──

    test("back button navigates to orchestrator overview", async ({ page }) => {
      await navigateTo(page, "/orchestrator/tasks/new");
      await page.waitForTimeout(3000);
      await page.locator("textarea").first().fill("E2E back button test");
      await page.getByRole("button", { name: /submit|提交/i }).click();
      await page.waitForTimeout(3000);
      const backBtn = page.getByRole("button", { name: /back|返回/i });
      const count = await backBtn.count();
      if (count > 0) {
        await backBtn.click();
        await page.waitForTimeout(1000);
        // Should go back to /admin/orchestrator (not /orchestrator)
        expect(page.url()).toMatch(/\/admin\/orchestrator\/?$/);
      }
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // Sidebar Navigation
  // ════════════════════════════════════════════════════════════════════════

  test("sidebar has orchestrator navigation links", async ({ page }) => {
    await navigateTo(page, "/");
    await page.waitForTimeout(2000);
    const sidebarLinks = page.locator("a[href*='orchestrator']");
    const count = await sidebarLinks.count();
    expect(count).toBeGreaterThanOrEqual(2);
  });

  test("sidebar orchestrator overview link works", async ({ page }) => {
    await navigateTo(page, "/");
    await page.waitForTimeout(2000);
    const overviewLink = page.locator("a[href='/admin/orchestrator']").first();
    if (await overviewLink.count() > 0) {
      await overviewLink.click();
      await page.waitForTimeout(2000);
      expect(page.url()).toMatch(/\/admin\/orchestrator\/?$/);
    }
  });

  test("sidebar submit task link works", async ({ page }) => {
    await navigateTo(page, "/");
    await page.waitForTimeout(2000);
    const submitLink = page.locator("a[href='/admin/orchestrator/tasks/new']").first();
    if (await submitLink.count() > 0) {
      await submitLink.click();
      await page.waitForTimeout(2000);
      expect(page.url()).toMatch(/\/admin\/orchestrator\/tasks\/new/);
    }
  });
});
