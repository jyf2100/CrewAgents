import { test } from '@playwright/test';

test.setTimeout(60000);

test('Check WebUI model selector', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // Login to admin
  await page.goto('http://roc-epyc:40080/admin/login');
  await page.waitForLoadState('networkidle');
  await page.locator('button, [role="tab"]').filter({ hasText: /邮箱|Email/ }).first().click();
  await page.waitForTimeout(300);
  await page.locator('input[placeholder*="邮箱"], input[placeholder*="email"]').first().fill('test123@test.com');
  await page.locator('input[type="password"]:visible').first().fill('123456');
  await page.locator('button:has-text("登录"), button:has-text("Login"), button[type="submit"]').first().click();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1000);

  // Navigate to chat
  await page.goto('http://roc-epyc:40080/admin/chat');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(8000); // Wait for bridge page + redirect

  await page.screenshot({ path: '/tmp/08-webui-loaded.png', fullPage: true });

  // Check iframe content
  const frame = page.frameLocator('iframe[title="Web Chat"]');
  try {
    const bodyText = await frame.locator('body').innerText({ timeout: 5000 });
    console.log(`Iframe body text:\n${bodyText.substring(0, 500)}`);
  } catch (e: any) {
    console.log(`Cannot read iframe: ${e.message}`);
  }

  // Check model selector text
  try {
    const modelSelector = frame.locator('[class*="model"], button:has-text("Select"), [data-testid*="model"]').first();
    const modelText = await modelSelector.textContent({ timeout: 5000 });
    console.log(`Model selector text: ${modelText}`);
  } catch (e: any) {
    console.log(`No model selector found: ${e.message}`);
  }

  await context.close();
});
