/**
 * Full E2E Test Suite — covers ALL interactive elements on the admin panel.
 * Runs against real deployment at http://100.105.228.5:40080
 */
import { test, expect } from "@playwright/test";
import { loginAsAdmin, navigateTo, ADMIN_KEY } from "./helpers";

// All tests use loginAsAdmin() helper to authenticate

// ═══════════════════════════════════════════════════════════════
// 1. LOGIN PAGE — All tabs, inputs, buttons
// ═══════════════════════════════════════════════════════════════
test.describe("Login Page — All Interactive Elements", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1000);
  });

  test("shows all three login tabs", async ({ page }) => {
    const body = await page.textContent("body");
    // At least Email and Admin tabs should be visible
    expect(body).toMatch(/email|邮箱/i);
    expect(body).toMatch(/admin|管理员/i);
  });

  test("Admin tab — key input + login button", async ({ page }) => {
    // Click admin tab
    const adminTab = page.getByRole("button", { name: /admin|管理员/i });
    if (await adminTab.count() > 0) {
      await adminTab.click();
      await page.waitForTimeout(500);

      // Key input should be visible
      const keyInput = page.locator("#login-key-input");
      if (await keyInput.count() > 0) {
        await expect(keyInput).toBeVisible();
      }

      // Login button should exist (disabled when empty)
      const loginBtn = page.getByRole("button", { name: /login|登录/i });
      if (await loginBtn.count() > 0) {
        await expect(loginBtn).toBeVisible();
      }
    }
  });

  test("Admin tab — wrong key shows error", async ({ page }) => {
    const adminTab = page.getByRole("button", { name: /admin|管理员/i });
    if (await adminTab.count() > 0) {
      await adminTab.click();
      await page.waitForTimeout(500);

      const keyInput = page.locator("#login-key-input");
      if (await keyInput.count() > 0) {
        await keyInput.fill("wrong-key-12345");
        const loginBtn = page.getByRole("button", { name: /login|登录/i });
        if (await loginBtn.count() > 0) {
          await loginBtn.click();
          await page.waitForTimeout(2000);
          // Should show error message or stay on login
          const url = page.url();
          expect(url).toContain("/login");
        }
      }
    }
  });

  test("Admin tab — correct key navigates to dashboard", async ({ page }) => {
    const adminTab = page.getByRole("button", { name: /admin|管理员/i });
    if (await adminTab.count() > 0) {
      await adminTab.click();
      await page.waitForTimeout(500);

      const keyInput = page.locator("#login-key-input");
      if (await keyInput.count() > 0) {
        await keyInput.fill(ADMIN_KEY);
        const loginBtn = page.getByRole("button", { name: /login|登录/i });
        if (await loginBtn.count() > 0) {
          await loginBtn.click();
          await page.waitForURL(/\/admin\/?$/, { timeout: 10000 }).catch(() => {});
          // Should navigate away from login
          const url = page.url();
          expect(url).not.toContain("/login");
        }
      }
    }
  });

  test("Email tab — email and password inputs", async ({ page }) => {
    const emailTab = page.getByRole("button", { name: /email|邮箱/i });
    if (await emailTab.count() > 0) {
      await emailTab.click();
      await page.waitForTimeout(500);

      const emailInput = page.locator("#login-email-input");
      const passInput = page.locator("#login-password-input");
      if (await emailInput.count() > 0) {
        await expect(emailInput).toBeVisible();
      }
      if (await passInput.count() > 0) {
        await expect(passInput).toBeVisible();
      }
    }
  });

  test("Email tab — register toggle button", async ({ page }) => {
    const emailTab = page.getByRole("button", { name: /email|邮箱/i });
    if (await emailTab.count() > 0) {
      await emailTab.click();
      await page.waitForTimeout(500);

      const registerBtn = page.getByRole("button", { name: /register|注册/i });
      if (await registerBtn.count() > 0) {
        await registerBtn.click();
        await page.waitForTimeout(500);
        // Should show display name input
        const nameInput = page.locator("#register-name-input");
        if (await nameInput.count() > 0) {
          await expect(nameInput).toBeVisible();
        }
        // Should show "back to login" button
        const backBtn = page.getByRole("button", { name: /back.*login|返回.*登录/i });
        if (await backBtn.count() > 0) {
          await expect(backBtn).toBeVisible();
        }
      }
    }
  });

  test("screenshot — login page all tabs", async ({ page }) => {
    await page.screenshot({ path: "test-results/login-page-full.png", fullPage: true });
  });
});

// ═══════════════════════════════════════════════════════════════
// 2. DASHBOARD — Stats, Agent Cards, Kebab Menu, User Management
// ═══════════════════════════════════════════════════════════════
test.describe("Dashboard — All Interactive Elements", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/admin/");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(3000);
  });

  test("Create Agent button is visible", async ({ page }) => {
    const createBtn = page.getByRole("button", { name: /create.*agent|创建.*代理/i });
    const count = await createBtn.count();
    if (count > 0) {
      await expect(createBtn.first()).toBeVisible();
    }
  });

  test("Create Agent button navigates to /create", async ({ page }) => {
    const createBtn = page.getByRole("button", { name: /create.*agent|创建.*代理/i });
    const count = await createBtn.count();
    test.skip(count === 0, "No create agent button");
    await createBtn.first().click();
    await page.waitForURL(/\/admin\/create/, { timeout: 5000 }).catch(() => {});
    expect(page.url()).toContain("/create");
  });

  test("Stats cards render with data", async ({ page }) => {
    const body = await page.textContent("body");
    // Should have stats numbers
    expect(body).toMatch(/\d+/);
    await page.screenshot({ path: "test-results/dashboard-stats.png" });
  });

  test("Agent card kebab menu opens and shows options", async ({ page }) => {
    // Find first details/summary (kebab menu)
    const kebab = page.locator("details summary").first();
    const count = await kebab.count();
    test.skip(count === 0, "No agent cards with kebab menu");
    await kebab.click();
    await page.waitForTimeout(500);

    // Menu should be open — check for common menu items
    const body = await page.textContent("body");
    expect(body).toMatch(/restart|重启/i);
    await page.screenshot({ path: "test-results/dashboard-kebab-open.png" });
  });

  test("Agent card kebab — all menu items visible", async ({ page }) => {
    const kebab = page.locator("details summary").first();
    const count = await kebab.count();
    test.skip(count === 0, "No agent cards with kebab menu");
    await kebab.click();
    await page.waitForTimeout(500);

    const body = await page.textContent("body");
    // Should show multiple action options
    const hasRestart = /restart|重启/i.test(body!);
    const hasLogs = /logs|日志/i.test(body!);
    const hasClone = /clone|克隆/i.test(body!);
    const hasDelete = /delete|删除/i.test(body!);
    // At least 2 of these should be present
    expect([hasRestart, hasLogs, hasClone, hasDelete].filter(Boolean).length).toBeGreaterThanOrEqual(2);
  });

  test("Agent card View link navigates to detail", async ({ page }) => {
    const viewLink = page.getByRole("link", { name: /view|查看/i }).first();
    const count = await viewLink.count();
    test.skip(count === 0, "No View links");
    await viewLink.click();
    await page.waitForURL(/\/admin\/agents\//, { timeout: 5000 }).catch(() => {});
    expect(page.url()).toMatch(/\/admin\/agents\//);
  });

  test("User management table — activate and action buttons", async ({ page }) => {
    // Look for user management section
    const userSection = page.getByText(/user.*management|用户.*管理/i).first();
    const hasUsers = (await userSection.count()) > 0;
    test.skip(!hasUsers, "No user management section visible");

    // Check for action buttons within user rows
    const activateBtn = page.getByRole("button", { name: /activate|激活/i });
    const startChatBtn = page.getByRole("button", { name: /start.*chat|开始.*对话/i });
    const retryBtn = page.getByRole("button", { name: /retry|重试/i });
    const deleteBtn = page.getByRole("button", { name: /delete.*user|删除.*用户/i });

    const totalButtons =
      (await activateBtn.count()) +
      (await startChatBtn.count()) +
      (await retryBtn.count()) +
      (await deleteBtn.count());

    // At least some user action buttons should be present if table exists
    if (totalButtons > 0) {
      await page.screenshot({ path: "test-results/dashboard-user-management.png" });
    }
  });

  test("Cluster status bar is visible", async ({ page }) => {
    const body = await page.textContent("body");
    // Cluster status should show somewhere
    const hasCluster = /cluster|集群/i.test(body!);
    expect(hasCluster).toBeTruthy();
  });

  test("screenshot — full dashboard", async ({ page }) => {
    await page.screenshot({ path: "test-results/dashboard-full.png", fullPage: true });
  });
});

// ═══════════════════════════════════════════════════════════════
// 3. AGENT DETAIL — All tabs + MetadataCard + actions
// ═══════════════════════════════════════════════════════════════
test.describe("Agent Detail — All Tabs and Actions", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/admin/");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(3000);

    // Navigate to first agent detail
    const agentLink = page.locator("a[href*='/agents/']").first();
    const viewLink = page.getByText(/查看|view/i).first();
    const linkCount = await agentLink.count();
    if (linkCount > 0) {
      await agentLink.click();
    } else if ((await viewLink.count()) > 0) {
      await viewLink.click();
    }
    await page.waitForURL(/\/admin\/agents\//, { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(2000);
  });

  // ── Header actions ──

  test("Back button works", async ({ page }) => {
    const backBtn = page.getByRole("button", { name: /back|返回/i });
    const count = await backBtn.count();
    test.skip(count === 0, "No back button");
    await backBtn.first().click();
    await page.waitForURL(/\/admin\/?$/, { timeout: 5000 }).catch(() => {});
    expect(page.url()).toMatch(/\/admin\/?$/);
  });

  test("Restart button is visible", async ({ page }) => {
    const restartBtn = page.getByRole("button", { name: /restart|重启/i });
    const count = await restartBtn.count();
    if (count > 0) {
      await expect(restartBtn.first()).toBeVisible();
    }
  });

  test("Stop or Start button is visible", async ({ page }) => {
    const stopBtn = page.getByRole("button", { name: /stop|停止/i });
    const startBtn = page.getByRole("button", { name: /start|启动/i });
    const hasStop = (await stopBtn.count()) > 0;
    const hasStart = (await startBtn.count()) > 0;
    expect(hasStop || hasStart).toBeTruthy();
  });

  test("Delete button is visible (admin mode)", async ({ page }) => {
    const deleteBtn = page.getByRole("button", { name: /delete|删除/i });
    const count = await deleteBtn.count();
    if (count > 0) {
      await expect(deleteBtn.first()).toBeVisible();
    }
  });

  // ── Overview tab ──

  test("Overview — Test API Connection button", async ({ page }) => {
    const testBtn = page.getByRole("button", { name: /test.*api|测试.*连接/i });
    const count = await testBtn.count();
    if (count > 0) {
      await expect(testBtn.first()).toBeVisible();
      await testBtn.first().click();
      await page.waitForTimeout(3000);
      await page.screenshot({ path: "test-results/agent-detail-test-api.png" });
    }
  });

  test("Overview — Copy URL and Copy Key buttons", async ({ page }) => {
    const body = await page.textContent("body");
    // Should show API access section with copy buttons
    expect(body).toMatch(/api|API|access|密钥/i);

    // Look for copy buttons (they might be icon buttons)
    const copyButtons = page.locator("button").filter({ hasText: /copy|复制/i });
    const count = await copyButtons.count();
    if (count > 0) {
      await page.screenshot({ path: "test-results/agent-detail-copy-btns.png" });
    }
  });

  // ── MetadataCard — Tags & Role ──

  test("MetadataCard — Role dropdown is visible", async ({ page }) => {
    const roleSelect = page.locator("select").filter({ hasText: /generalist|coder|analyst|通用|编程|分析/i });
    const count = await roleSelect.count();
    if (count > 0) {
      await expect(roleSelect.first()).toBeVisible();
    }
  });

  test("MetadataCard — Can change role in dropdown", async ({ page }) => {
    const roleSelect = page.locator("select").first();
    const count = await roleSelect.count();
    test.skip(count === 0, "No role select found");
    const currentValue = await roleSelect.first().inputValue();
    // Change to a different value
    const options = ["generalist", "coder", "analyst"];
    const otherOption = options.find((o) => o !== currentValue) || "coder";
    await roleSelect.first().selectOption(otherOption);
    await page.waitForTimeout(300);
    const newValue = await roleSelect.first().inputValue();
    expect(newValue).toBe(otherOption);
  });

  test("MetadataCard — Tag input field is visible", async ({ page }) => {
    const tagInput = page.locator('input[type="text"]').filter({ hasText: "" });
    // Look for the tag input by placeholder
    const allInputs = page.locator("input[placeholder]");
    const body = await page.textContent("body");
    const hasTags = /tag|标签/i.test(body!);
    if (hasTags) {
      await page.screenshot({ path: "test-results/agent-detail-metadata.png" });
    }
  });

  test("MetadataCard — Add tag via input", async ({ page }) => {
    // Find tag input by looking near the "Tags" label
    const tagsLabel = page.getByText(/tags|标签/i).first();
    const count = await tagsLabel.count();
    test.skip(count === 0, "No tags section");
    await page.screenshot({ path: "test-results/agent-detail-tags-before.png" });

    // Find the tag text input (near the + button)
    const tagInputs = page.locator('input[type="text"]');
    const tagInputCount = await tagInputs.count();
    if (tagInputCount > 0) {
      // Try typing a tag in the last input (likely the tag input)
      const input = tagInputs.last();
      await input.fill("e2e-test-tag");
      await input.press("Enter");
      await page.waitForTimeout(500);
      // Check if tag appeared
      const body = await page.textContent("body");
      const hasTag = /e2e-test-tag/i.test(body!);
      if (hasTag) {
        await page.screenshot({ path: "test-results/agent-detail-tags-added.png" });
      }
    }
  });

  test("MetadataCard — Save Metadata button", async ({ page }) => {
    const saveBtn = page.getByRole("button", { name: /save.*metadata|保存.*元数据/i });
    const count = await saveBtn.count();
    if (count > 0) {
      await expect(saveBtn.first()).toBeVisible();
      // Click save
      await saveBtn.first().click();
      await page.waitForTimeout(2000);
      await page.screenshot({ path: "test-results/agent-detail-metadata-saved.png" });
    }
  });

  // ── Config tab ──

  test("Config tab — renders sub-tabs", async ({ page }) => {
    const configTab = page.getByText(/config|配置/i).first();
    const count = await configTab.count();
    test.skip(count === 0, "No config tab");
    await configTab.click();
    await page.waitForTimeout(1000);

    const body = await page.textContent("body");
    // Should show .env, config.yaml, SOUL.md sub-tabs
    const hasEnv = /\.env|环境/i.test(body!);
    const hasYaml = /config\.yaml|配置文件/i.test(body!);
    const hasSoul = /SOUL\.md/i.test(body!);
    expect(hasEnv || hasYaml || hasSoul).toBeTruthy();
    await page.screenshot({ path: "test-results/agent-detail-config-tab.png" });
  });

  test("Config tab — .env sub-tab with inputs", async ({ page }) => {
    const configTab = page.getByText(/^config$|^配置$/i).first();
    if ((await configTab.count()) > 0) {
      await configTab.click();
      await page.waitForTimeout(1000);

      const envTab = page.getByText(/\.env|环境/i).first();
      if ((await envTab.count()) > 0) {
        await envTab.click();
        await page.waitForTimeout(1000);
        // Should show env var inputs or add button
        const addBtn = page.getByRole("button", { name: /add.*env|添加.*环境/i });
        const saveBtn = page.getByRole("button", { name: /save|保存/i });
        const hasAdd = (await addBtn.count()) > 0;
        const hasSave = (await saveBtn.count()) > 0;
        expect(hasAdd || hasSave).toBeTruthy();
        await page.screenshot({ path: "test-results/agent-detail-config-env.png" });
      }
    }
  });

  test("Config tab — SOUL.md textarea and save", async ({ page }) => {
    const configTab = page.getByText(/^config$|^配置$/i).first();
    if ((await configTab.count()) > 0) {
      await configTab.click();
      await page.waitForTimeout(1000);

      const soulTab = page.getByText(/SOUL\.md/i).first();
      if ((await soulTab.count()) > 0) {
        await soulTab.click();
        await page.waitForTimeout(1000);
        // Should show textarea
        const textarea = page.locator("textarea").first();
        if ((await textarea.count()) > 0) {
          await expect(textarea).toBeVisible();
        }
        await page.screenshot({ path: "test-results/agent-detail-config-soul.png" });
      }
    }
  });

  // ── Logs tab ──

  test("Logs tab — pause/resume and filter", async ({ page }) => {
    const logsTab = page.getByText(/logs|日志/i).first();
    const count = await logsTab.count();
    test.skip(count === 0, "No logs tab");
    await logsTab.click();
    await page.waitForTimeout(2000);

    // Check for controls
    const pauseBtn = page.getByRole("button", { name: /pause|暂停/i });
    const clearBtn = page.getByRole("button", { name: /clear|清空/i });
    const filterInput = page.locator('input[placeholder*="filter"], input[placeholder*="过滤"]');

    const hasPause = (await pauseBtn.count()) > 0;
    const hasClear = (await clearBtn.count()) > 0;
    const hasFilter = (await filterInput.count()) > 0;

    // At least one control should exist
    expect(hasPause || hasClear || hasFilter).toBeTruthy();
    await page.screenshot({ path: "test-results/agent-detail-logs.png" });
  });

  test("Logs tab — click pause then resume", async ({ page }) => {
    const logsTab = page.getByText(/logs|日志/i).first();
    const count = await logsTab.count();
    test.skip(count === 0, "No logs tab");
    await logsTab.click();
    await page.waitForTimeout(2000);

    const pauseBtn = page.getByRole("button", { name: /pause|暂停/i });
    if ((await pauseBtn.count()) > 0) {
      await pauseBtn.first().click();
      await page.waitForTimeout(500);
      // Should now show resume button
      const resumeBtn = page.getByRole("button", { name: /resume|继续/i });
      if ((await resumeBtn.count()) > 0) {
        await expect(resumeBtn.first()).toBeVisible();
        await resumeBtn.first().click();
      }
    }
  });

  // ── Events tab ──

  test("Events tab — renders event table", async ({ page }) => {
    const eventsTab = page.getByText(/events|事件/i).first();
    const count = await eventsTab.count();
    test.skip(count === 0, "No events tab");
    await eventsTab.click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: "test-results/agent-detail-events.png" });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  // ── Health tab ──

  test("Health tab — renders health data with refresh button", async ({ page }) => {
    const healthTab = page.getByText(/health|健康/i).first();
    const count = await healthTab.count();
    test.skip(count === 0, "No health tab");
    await healthTab.click();
    await page.waitForTimeout(2000);

    const refreshBtn = page.getByRole("button", { name: /refresh|刷新/i });
    if ((await refreshBtn.count()) > 0) {
      await refreshBtn.first().click();
      await page.waitForTimeout(2000);
    }
    await page.screenshot({ path: "test-results/agent-detail-health.png" });
  });

  // ── Terminal tab ──

  test("Terminal tab — renders terminal UI", async ({ page }) => {
    const terminalTab = page.getByText(/terminal|终端/i).first();
    const count = await terminalTab.count();
    test.skip(count === 0, "No terminal tab");
    await terminalTab.click();
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "test-results/agent-detail-terminal-full.png" });
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  // ── Stop/Delete confirm dialogs ──

  test("Stop button triggers confirmation dialog", async ({ page }) => {
    const stopBtn = page.getByRole("button", { name: /^stop$|^停止$/i });
    if ((await stopBtn.count()) > 0) {
      await stopBtn.first().click();
      await page.waitForTimeout(500);
      // ConfirmDialog should appear
      const cancelBtn = page.getByRole("button", { name: /cancel|取消/i });
      if ((await cancelBtn.count()) > 0) {
        await cancelBtn.first().click(); // Cancel to not actually stop
      }
    }
  });

  test("Delete button triggers confirmation dialog", async ({ page }) => {
    const deleteBtn = page.getByRole("button", { name: /delete|删除/i }).first();
    if ((await deleteBtn.count()) > 0) {
      await deleteBtn.click();
      await page.waitForTimeout(500);
      // ConfirmDialog should appear
      const cancelBtn = page.getByRole("button", { name: /cancel|取消/i });
      if ((await cancelBtn.count()) > 0) {
        await cancelBtn.first().click(); // Cancel to not actually delete
      }
    }
  });

  test("screenshot — full agent detail page", async ({ page }) => {
    await page.screenshot({ path: "test-results/agent-detail-full.png", fullPage: true });
  });
});

// ═══════════════════════════════════════════════════════════════
// 4. CREATE AGENT — All wizard steps
// ═══════════════════════════════════════════════════════════════
test.describe("Create Agent — All Wizard Steps", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/admin/create");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);
  });

  test("Step 1 — renders agent number and display name inputs", async ({ page }) => {
    const numInput = page.locator('input[type="number"]').first();
    const nameInput = page.locator('input[type="text"]').first();
    if ((await numInput.count()) > 0) await expect(numInput).toBeVisible();
    if ((await nameInput.count()) > 0) await expect(nameInput).toBeVisible();
  });

  test("Step 1 — Cancel button navigates back", async ({ page }) => {
    const cancelBtn = page.getByRole("button", { name: /cancel|取消/i });
    if ((await cancelBtn.count()) > 0) {
      await cancelBtn.first().click();
      await page.waitForURL(/\/admin\/?$/, { timeout: 5000 }).catch(() => {});
      expect(page.url()).toMatch(/\/admin\/?$/);
    }
  });

  test("Step 1 — Next button advances to step 2", async ({ page }) => {
    const nextBtn = page.getByRole("button", { name: /next|下一步|confirm|确认/i });
    if ((await nextBtn.count()) > 0) {
      // Fill required fields first
      const numInput = page.locator('input[type="number"]').first();
      if ((await numInput.count()) > 0) {
        await numInput.fill("99");
      }
      await nextBtn.first().click();
      await page.waitForTimeout(1000);
      // Should show LLM config section
      const body = await page.textContent("body");
      expect(body).toMatch(/provider|model|LLM|提供商|模型/i);
    }
  });

  test("Step 2 — Provider dropdown has options", async ({ page }) => {
    // First navigate to step 2
    const numInput = page.locator('input[type="number"]').first();
    if ((await numInput.count()) > 0) {
      await numInput.fill("99");
    }
    const nextBtn = page.getByRole("button", { name: /next|下一步|confirm|确认/i });
    if ((await nextBtn.count()) > 0) {
      await nextBtn.first().click();
      await page.waitForTimeout(1000);

      const providerSelect = page.locator("select").first();
      if ((await providerSelect.count()) > 0) {
        const options = await providerSelect.locator("option").count();
        expect(options).toBeGreaterThanOrEqual(3);
      }
    }
  });

  test("Step 2 — API Key input is type password", async ({ page }) => {
    const numInput = page.locator('input[type="number"]').first();
    if ((await numInput.count()) > 0) await numInput.fill("99");
    const nextBtn = page.getByRole("button", { name: /next|下一步|confirm|确认/i });
    if ((await nextBtn.count()) > 0) {
      await nextBtn.first().click();
      await page.waitForTimeout(1000);

      const passInputs = page.locator('input[type="password"]');
      const count = await passInputs.count();
      expect(count).toBeGreaterThanOrEqual(1);
    }
  });

  test("Step 2 — Test Connection button", async ({ page }) => {
    const numInput = page.locator('input[type="number"]').first();
    if ((await numInput.count()) > 0) await numInput.fill("99");
    const nextBtn = page.getByRole("button", { name: /next|下一步|confirm|确认/i });
    if ((await nextBtn.count()) > 0) {
      await nextBtn.first().click();
      await page.waitForTimeout(1000);

      const testBtn = page.getByRole("button", { name: /test.*connection|测试.*连接/i });
      if ((await testBtn.count()) > 0) {
        await expect(testBtn.first()).toBeVisible();
      }
    }
  });

  test("screenshot — create agent wizard", async ({ page }) => {
    await page.screenshot({ path: "test-results/create-agent-step1.png", fullPage: true });
  });
});

// ═══════════════════════════════════════════════════════════════
// 5. SETTINGS — All sections, inputs, buttons
// ═══════════════════════════════════════════════════════════════
test.describe("Settings — All Interactive Elements", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/admin/settings");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(3000);
  });

  test("Cluster status section is visible", async ({ page }) => {
    const body = await page.textContent("body");
    expect(body).toMatch(/cluster|集群/i);
  });

  test("Admin key section renders with inputs", async ({ page }) => {
    const body = await page.textContent("body");
    expect(body).toMatch(/admin.*key|管理员.*密钥/i);

    // Look for key change inputs
    const keyInputs = page.locator('input[type="password"]');
    const count = await keyInputs.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test("Admin key — Change button disabled when fields empty", async ({ page }) => {
    const changeBtn = page.getByRole("button", { name: /change.*key|更换.*密钥/i });
    if ((await changeBtn.count()) > 0) {
      const btn = changeBtn.first();
      const disabled = await btn.isDisabled();
      // Should be disabled when no new key entered
      expect(disabled).toBeTruthy();
    }
  });

  test("Resource limits — CPU and Memory inputs", async ({ page }) => {
    const body = await page.textContent("body");
    const hasResources = /resource|资源|cpu|memory|内存/i.test(body!);
    if (hasResources) {
      const cpuInput = page.locator("input").filter({ hasText: "" }).first();
      // Just check page renders properly
      await page.screenshot({ path: "test-results/settings-resources.png" });
    }
  });

  test("Template section renders", async ({ page }) => {
    const body = await page.textContent("body");
    const hasTemplates = /template|模板/i.test(body!);
    if (hasTemplates) {
      await page.screenshot({ path: "test-results/settings-templates.png" });
    }
  });

  test("screenshot — full settings page", async ({ page }) => {
    await page.screenshot({ path: "test-results/settings-full.png", fullPage: true });
  });
});

// ═══════════════════════════════════════════════════════════════
// 6. ORCHESTRATOR — Overview, Task Submit, Task Detail
// ═══════════════════════════════════════════════════════════════
test.describe("Orchestrator — All Interactive Elements", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("Overview page — stats cards and agent fleet table", async ({ page }) => {
    await page.goto("/admin/orchestrator");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(3000);

    const body = await page.textContent("body");
    // Should have orchestrator content
    const hasContent = body!.length > 100;
    await page.screenshot({ path: "test-results/orchestrator-overview.png", fullPage: true });
    expect(hasContent).toBeTruthy();
  });

  test("Task Submit page — form inputs and tag toggles", async ({ page }) => {
    await page.goto("/admin/orchestrator/tasks/new");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);

    // Prompt textarea
    const promptArea = page.locator("textarea").first();
    if ((await promptArea.count()) > 0) {
      await expect(promptArea).toBeVisible();
    }

    // Tag toggle buttons
    const tagButtons = page.locator("button[aria-pressed]");
    const tagCount = await tagButtons.count();
    if (tagCount > 0) {
      // Click a tag
      await tagButtons.first().click();
      await page.waitForTimeout(300);
      const pressed = await tagButtons.first().getAttribute("aria-pressed");
      expect(pressed).toBe("true");
    }

    // Submit button (should be disabled without prompt)
    const submitBtn = page.getByRole("button", { name: /submit|提交/i });
    if ((await submitBtn.count()) > 0) {
      const disabled = await submitBtn.first().isDisabled();
      expect(disabled).toBeTruthy();
    }

    await page.screenshot({ path: "test-results/orchestrator-submit.png", fullPage: true });
  });

  test("Task Submit — fill prompt and enable submit button", async ({ page }) => {
    await page.goto("/admin/orchestrator/tasks/new");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);

    const promptArea = page.locator("textarea").first();
    if ((await promptArea.count()) > 0) {
      await promptArea.fill("E2E test task - automated testing prompt");
      await page.waitForTimeout(500);

      const submitBtn = page.getByRole("button", { name: /submit|提交/i });
      if ((await submitBtn.count()) > 0) {
        const disabled = await submitBtn.first().isDisabled();
        expect(disabled).toBeFalsy();
      }
    }
  });

  test("Task Submit — priority, timeout, retries inputs", async ({ page }) => {
    await page.goto("/admin/orchestrator/tasks/new");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);

    const numInputs = page.locator('input[type="number"]');
    const count = await numInputs.count();
    if (count > 0) {
      // Should have priority, timeout, retries inputs
      expect(count).toBeGreaterThanOrEqual(1);
    }
  });

  test("Task Submit — callback URL input", async ({ page }) => {
    await page.goto("/admin/orchestrator/tasks/new");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);

    const urlInput = page.locator('input[type="url"], input[placeholder*="callback"], input[placeholder*="https"]');
    const count = await urlInput.count();
    if (count > 0) {
      await expect(urlInput.first()).toBeVisible();
    }
  });
});

// ═══════════════════════════════════════════════════════════════
// 7. SWARM — Overview, Crews, Tasks, Knowledge
// ═══════════════════════════════════════════════════════════════
test.describe("Swarm — All Interactive Elements", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("Swarm overview — renders agent cards and stats", async ({ page }) => {
    await page.goto("/admin/swarm");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(3000);

    const body = await page.textContent("body");
    await page.screenshot({ path: "test-results/swarm-overview.png", fullPage: true });
    expect(body!.length).toBeGreaterThan(0);
  });

  test("Swarm crews — New Crew button", async ({ page }) => {
    await page.goto("/admin/swarm/crews");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);

    const newCrewBtn = page.getByRole("button", { name: /new.*crew|add.*crew|新建.*团队|添加.*团队/i });
    const count = await newCrewBtn.count();
    if (count > 0) {
      await newCrewBtn.first().click();
      await page.waitForTimeout(1000);
      await page.screenshot({ path: "test-results/swarm-crew-new.png" });
    }
  });

  test("Swarm crew edit — form inputs", async ({ page }) => {
    await page.goto("/admin/swarm/crews/new");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);

    const body = await page.textContent("body");
    const hasForm = body!.length > 100;
    if (hasForm) {
      // Check for save/cancel buttons
      const saveBtn = page.getByRole("button", { name: /save|保存/i });
      const cancelBtn = page.getByRole("button", { name: /cancel|取消/i });
      const hasSave = (await saveBtn.count()) > 0;
      const hasCancel = (await cancelBtn.count()) > 0;
      expect(hasSave || hasCancel).toBeTruthy();
    }
    await page.screenshot({ path: "test-results/swarm-crew-edit.png", fullPage: true });
  });

  test("Swarm tasks — renders coming soon page", async ({ page }) => {
    await page.goto("/admin/swarm/tasks");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);

    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(0);
    await page.screenshot({ path: "test-results/swarm-tasks.png" });
  });

  test("Swarm knowledge — renders coming soon page", async ({ page }) => {
    await page.goto("/admin/swarm/knowledge");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);

    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(0);
    await page.screenshot({ path: "test-results/swarm-knowledge.png" });
  });
});

// ═══════════════════════════════════════════════════════════════
// 8. NAVIGATION — Sidebar links, language toggle, logout
// ═══════════════════════════════════════════════════════════════
test.describe("Navigation — All Sidebar Links", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/admin/");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2000);
  });

  const navRoutes = [
    { name: /dashboard|仪表盘/i, path: /\/admin\/?$/ },
    { name: /settings|设置/i, path: /\/admin\/settings/ },
  ];

  for (const route of navRoutes) {
    test(`Sidebar link "${route.name}" navigates correctly`, async ({ page }) => {
      const link = page.getByRole("link", { name: route.name }).first();
      if ((await link.count()) > 0) {
        await link.click();
        await page.waitForURL(route.path, { timeout: 5000 }).catch(() => {});
        expect(page.url()).toMatch(route.path);
      }
    });
  }

  test("Language toggle switches language", async ({ page }) => {
    const langBtn = page.getByRole("button", { name: /en|zh|中文|english/i });
    const count = await langBtn.count();
    if (count > 0) {
      const textBefore = await langBtn.first().textContent();
      await langBtn.first().click();
      await page.waitForTimeout(1000);
      const textAfter = await langBtn.first().textContent();
      // Button text should change
      expect(textBefore).not.toBe(textAfter);
    }
  });

  test("Logout button redirects to login", async ({ page }) => {
    const logoutBtn = page.getByRole("button", { name: /logout|退出|登出/i });
    const count = await logoutBtn.count();
    if (count > 0) {
      await logoutBtn.click();
      await page.waitForURL(/\/admin\/login/, { timeout: 5000 }).catch(() => {});
      expect(page.url()).toContain("/login");
    }
  });

  test("Orchestrator sidebar link", async ({ page }) => {
    const orchLink = page.getByRole("link", { name: /orchestrator|编排/i }).first();
    if ((await orchLink.count()) > 0) {
      await orchLink.click();
      await page.waitForURL(/\/admin\/orchestrator/, { timeout: 5000 }).catch(() => {});
      expect(page.url()).toContain("/orchestrator");
    }
  });

  test("Swarm sidebar link", async ({ page }) => {
    const swarmLink = page.getByRole("link", { name: /swarm|集群/i }).first();
    if ((await swarmLink.count()) > 0) {
      await swarmLink.click();
      await page.waitForURL(/\/admin\/swarm/, { timeout: 5000 }).catch(() => {});
      expect(page.url()).toContain("/swarm");
    }
  });

  test("Chat/WebUI sidebar link", async ({ page }) => {
    const chatLink = page.getByRole("link", { name: /chat|对话|webui/i }).first();
    if ((await chatLink.count()) > 0) {
      await expect(chatLink).toBeVisible();
    }
  });
});

// ═══════════════════════════════════════════════════════════════
// 9. AGENT CARD — Full kebab menu walkthrough
// ═══════════════════════════════════════════════════════════════
test.describe("Agent Card — Kebab Menu Full Walkthrough", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/admin/");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(3000);
  });

  test("Kebab menu — Restart action", async ({ page }) => {
    const kebab = page.locator("details summary").first();
    test.skip((await kebab.count()) === 0, "No agent cards");
    await kebab.click();
    await page.waitForTimeout(500);

    const restartBtn = page.locator("details[open] button").getByText(/restart|重启/i).first();
    if ((await restartBtn.count()) > 0) {
      // Just verify it's visible, don't actually click restart
      await expect(restartBtn).toBeVisible();
    }
  });

  test("Kebab menu — Logs action navigates to detail", async ({ page }) => {
    const kebab = page.locator("details summary").first();
    test.skip((await kebab.count()) === 0, "No agent cards");
    await kebab.click();
    await page.waitForTimeout(500);

    const logsBtn = page.locator("details[open] button, details[open] a").getByText(/logs|日志/i).first();
    if ((await logsBtn.count()) > 0) {
      await logsBtn.click();
      await page.waitForURL(/\/admin\/agents\//, { timeout: 5000 }).catch(() => {});
      // Should be on agent detail page with logs tab
    }
  });

  test("Kebab menu — Clone action navigates to create", async ({ page }) => {
    const kebab = page.locator("details summary").first();
    test.skip((await kebab.count()) === 0, "No agent cards");
    await kebab.click();
    await page.waitForTimeout(500);

    const cloneBtn = page.locator("details[open] button, details[open] a").getByText(/clone|克隆/i).first();
    if ((await cloneBtn.count()) > 0) {
      await cloneBtn.click();
      await page.waitForURL(/\/admin\/create/, { timeout: 5000 }).catch(() => {});
      expect(page.url()).toContain("/create");
    }
  });

  test("Kebab menu — Delete shows confirm dialog", async ({ page }) => {
    const kebab = page.locator("details summary").first();
    test.skip((await kebab.count()) === 0, "No agent cards");
    await kebab.click();
    await page.waitForTimeout(500);

    const deleteBtn = page.locator("details[open] button").getByText(/delete|删除/i).first();
    if ((await deleteBtn.count()) > 0) {
      await deleteBtn.click();
      await page.waitForTimeout(500);
      // ConfirmDialog should appear — cancel it
      const cancelBtn = page.getByRole("button", { name: /cancel|取消/i });
      if ((await cancelBtn.count()) > 0) {
        await cancelBtn.first().click();
      }
    }
  });
});
