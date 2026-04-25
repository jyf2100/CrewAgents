/**
 * Shared E2E test helpers.
 *
 * Provides API mocking and login helpers so tests don't need a real backend.
 */
import { type Page, type Route } from "@playwright/test";
import { VALID_ADMIN_KEY } from "./fixtures/mock-data";

/**
 * Login to the admin panel by navigating to the app first, then setting localStorage.
 * This avoids the SecurityError from writing to localStorage on about:blank.
 */
export async function loginAsAdmin(page: Page) {
  // Navigate to the app first to get a proper origin for localStorage
  await page.goto("/admin/login");
  await page.evaluate((key) => {
    localStorage.setItem("admin_api_key", key);
  }, VALID_ADMIN_KEY);
}

/**
 * Intercept all /admin/api/* requests and return mock data.
 */
export async function mockApi(
  page: Page,
  routes: Record<string, unknown>
) {
  await page.route("**/admin/api/**", async (route: Route) => {
    const request = route.request();
    const method = request.method();
    const url = new URL(request.url());
    const path = url.pathname;
    const key = `${method}:${path}`;

    if (key in routes) {
      return route.fulfill({ json: routes[key] });
    }

    // Default: return 404 for unmatched API calls
    return route.fulfill({
      status: 404,
      json: { detail: `No mock for ${key}` },
    });
  });
}
