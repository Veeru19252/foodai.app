/**
 * Documentation screenshot capture.
 *
 * Drives the real, running app (backend :8000 + frontend :3000) and writes
 * PNGs into ../docs/screenshots for the README. Not an assertion suite — it
 * fails loudly if a page the README advertises cannot be reached, so a broken
 * screenshot can never quietly ship.
 *
 * Run: npx playwright test e2e/screenshots.spec.ts
 */
import { expect, test, type Page } from "@playwright/test";
import { completeOnboarding, randomPhone } from "./helpers";

const OUT = "../docs/screenshots";

async function login(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Log in" }).click();
}

async function shot(page: Page, name: string, fullPage = true): Promise<void> {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(700); // let charts/maps finish painting
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage });
  console.log(`captured ${name}.png`);
}

// Sequencing: playwright.config.ts already sets `workers: 1`, and these
// captures walk one shared account through a real order, so they must not
// interleave. No describe.configure() call is needed here.
//
// The "@screenshots" tag lets CI skip this file with
// `--grep-invert "@screenshots"`: it regenerates the committed
// docs/screenshots/*.png and needs a seeded local database.
test.describe("@screenshots", () => {
test("capture login and restaurant listing", async ({ page }) => {
  // `/` is a role-based redirect, not a marketing page, so the entry point
  // the README shows is the login screen.
  await page.goto("/login");
  await expect(page.getByLabel("Email")).toBeVisible();
  await shot(page, "01-login");

  // Customer: log in, clear the first-run gate, land on the listing.
  await login(page, "customer@foodai.com");
  await expect(page).toHaveURL(/\/restaurants/);
  await completeOnboarding(page);
  await expect(page.getByText("Spice Garden").first()).toBeVisible();
  await shot(page, "03-restaurant-listing");
});

test("capture menu, cart and checkout", async ({ page }) => {
  await login(page, "customer@foodai.com");
  await expect(page).toHaveURL(/\/restaurants/);
  await completeOnboarding(page);

  // Open a menu and add items so the cart is non-empty.
  await page.getByText("Spice Garden").first().click();
  await expect(
    page.getByRole("heading", { name: "Spice Garden" }).last()
  ).toBeVisible();
  await page.getByRole("button", { name: "ADD" }).first().click();
  await page.getByRole("button", { name: "ADD" }).nth(1).click();
  await shot(page, "04-menu");
  await page.getByRole("button", { name: "Close" }).click();

  // Add a second restaurant for the multi-restaurant cart.
  await page.getByText("Dosa Plaza").first().click();
  await expect(
    page.getByRole("heading", { name: "Dosa Plaza" }).last()
  ).toBeVisible();
  await page.getByRole("button", { name: "ADD" }).first().click();
  await page.getByRole("button", { name: "Close" }).click();

  // Checkout with a promo applied.
  await page.getByRole("link", { name: "View cart →" }).click();
  await expect(page).toHaveURL(/\/checkout/);
  await page.getByPlaceholder("WELCOME10").fill("WELCOME10");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByText("Promo code applied!")).toBeVisible();
  await shot(page, "05-checkout");
});

test("capture live tracking with the AI ETA explainability panel", async ({
  page,
}) => {
  await login(page, "customer@foodai.com");
  await expect(page).toHaveURL(/\/restaurants/);
  await completeOnboarding(page);

  await page.getByText("Spice Garden").first().click();
  await expect(
    page.getByRole("heading", { name: "Spice Garden" }).last()
  ).toBeVisible();
  await page.getByRole("button", { name: "ADD" }).first().click();
  await page.getByRole("button", { name: "Close" }).click();

  await page.getByRole("link", { name: "View cart →" }).click();
  await expect(page).toHaveURL(/\/checkout/);
  await page.getByText("Yes, deliver to this address").click();
  await page.getByPlaceholder("10-digit mobile number").fill(randomPhone());
  await page.getByRole("button", { name: "Send OTP" }).click();
  await page.getByText("Verify & continue").click();
  await page.getByRole("button", { name: /Place.*order/ }).click();
  await expect(page).toHaveURL(/\/tracking\/\d+/);

  await expect(page.getByRole("heading", { name: "Live tracking" })).toBeVisible();
  await expect(page.getByText("AI ETA")).toBeVisible();
  await shot(page, "06-live-tracking");

  // Open "Why this ETA?" — the SHAP panel is a headline feature.
  await page.getByText("Why this ETA?").click();
  await expect(page.getByText(/The model scores/)).toBeVisible();
  await shot(page, "07-live-tracking-shap");
});

test("capture restaurant panel, driver console and admin dashboard", async ({
  page,
}) => {
  // Restaurant owner: order inbox with accept/reject.
  await login(page, "spice@foodai.com");
  await expect(page).toHaveURL(/\/restaurant\/orders/);
  await expect(
    page.getByRole("heading", { name: "Restaurant dashboard" })
  ).toBeVisible();
  // Viewport-only: the full inbox page is ~4800px tall and renders unreadable
  // when scaled down inside a README.
  await shot(page, "08-restaurant-orders", false);

  // Restaurant analytics.
  await page.goto("/restaurant/analytics");
  await page.waitForTimeout(800);
  await shot(page, "09-restaurant-analytics");

  // Delivery partner console with the earnings summary.
  await login(page, "rider@foodai.com");
  await expect(page).toHaveURL(/\/driver/);
  await expect(page.getByRole("heading", { name: "My deliveries" })).toBeVisible();
  await shot(page, "10-driver-console", false);

  // Admin: metric cards, charts and the demand forecast panel.
  await login(page, "admin@foodai.com");
  await expect(page).toHaveURL(/\/admin/);
  await expect(page.getByRole("heading", { name: "Admin dashboard" })).toBeVisible();
  await page.waitForTimeout(1200); // charts render from fetched data
  await shot(page, "11-admin-dashboard");
});
});
