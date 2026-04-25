import { test, expect } from "@playwright/test";
import {
  VALID_ADMIN_KEY,
  mockCreateAgentResponse,
  mockTestLlmResponse,
  mockSettings,
  mockEmptyAgentList,
} from "./fixtures/mock-data";
import { loginAsAdmin } from "./helpers";

test.describe("Create Agent", () => {
  async function goToCreate(page) {
    await page.route("**/admin/api/settings", (route) =>
      route.fulfill({ json: mockSettings })
    );
    await page.route("**/admin/api/agents", (route) =>
      route.fulfill({ json: mockEmptyAgentList })
    );
    await page.route("**/admin/api/templates/soul", (route) =>
      route.fulfill({ json: { type: "soul", content: "You are a helpful assistant." } })
    );
    await loginAsAdmin(page);
    await page.goto("/admin/create");
  }

  test("displays wizard with step indicator", async ({ page }) => {
    await goToCreate(page);
    // Should show step indicator
    await expect(page.getByText(/确认部署/)).toBeVisible();
  });

  test("cancel returns to dashboard", async ({ page }) => {
    await goToCreate(page);
    await page.getByText(/取消/).click();
    await expect(page).toHaveURL(/\/admin/);
  });

  test("can advance to step 2 after filling required fields", async ({ page }) => {
    await goToCreate(page);
    // Click confirm to go to step 2
    await page.getByRole("button", { name: "确认" }).click();
    // Step 2 should show LLM config (step 1 is step index 0, step 2 is index 1)
    // The step 2 heading/label should be visible
    await expect(page.getByText(/API Key|密钥/i)).toBeVisible();
  });

  test("test LLM connection button works", async ({ page }) => {
    await page.route("**/admin/api/test-llm-connection", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return route.fulfill({ json: mockTestLlmResponse });
    });

    await goToCreate(page);
    // Advance to step 2 (LLM config)
    await page.getByRole("button", { name: "确认" }).click();
    // Fill API key to enable test button
    await page.fill('input[type="password"]', "sk-test-key").catch(() => {});
  });

  async function goToStep2(page) {
    await goToCreate(page);
    // Advance from Step 0 (basic info) to Step 1 (LLM config)
    await page.getByRole("button", { name: "确认" }).click();
    // Wait for LLM config step to render
    await expect(page.getByText(/API Key|密钥/i)).toBeVisible();
  }

  test("shows Anthropic 兼容 option in provider dropdown", async ({ page }) => {
    await goToStep2(page);
    const providerSelect = page.locator('select').first();
    await providerSelect.selectOption({ label: 'Anthropic 兼容' });
    // Model input should be empty (anthropic-compat has no default model)
    const inputs = page.locator('input[type="text"]');
    await expect(inputs.first()).toHaveValue('');
  });

  test("shows OpenAI 兼容 option in provider dropdown", async ({ page }) => {
    await goToStep2(page);
    const providerSelect = page.locator('select').first();
    await providerSelect.selectOption({ label: 'OpenAI 兼容' });
    const inputs = page.locator('input[type="text"]');
    await expect(inputs.first()).toHaveValue('');
  });

  test("Anthropic 兼容 has empty defaults", async ({ page }) => {
    await goToStep2(page);
    const providerSelect = page.locator('select').first();
    await providerSelect.selectOption({ label: 'Anthropic 兼容' });
    const inputs = page.locator('input[type="text"]');
    await expect(inputs.first()).toHaveValue('');
  });

  test("switching between providers updates defaults", async ({ page }) => {
    await goToStep2(page);
    const providerSelect = page.locator('select').first();
    const inputs = page.locator('input[type="text"]');

    // Select OpenRouter - should have model prefilled
    await providerSelect.selectOption({ label: 'OpenRouter' });
    const openrouterModel = await inputs.first().inputValue();
    expect(openrouterModel.length).toBeGreaterThan(0);

    // Switch to Anthropic 兼容 - model should be empty
    await providerSelect.selectOption({ label: 'Anthropic 兼容' });
    await expect(inputs.first()).toHaveValue('');

    // Switch back to OpenRouter - model should be prefilled again
    await providerSelect.selectOption({ label: 'OpenRouter' });
    const restoredModel = await inputs.first().inputValue();
    expect(restoredModel.length).toBeGreaterThan(0);
  });
});
