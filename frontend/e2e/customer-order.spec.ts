import { expect, test } from "@playwright/test";

/**
 * Full customer journey: login → browse → add to cart → checkout with a promo
 * → place the order → live tracking page loads with the AI ETA.
 */
test("customer places an order and sees live tracking", async ({ page }) => {
  // 1. Login as the demo customer
  await page.goto("/login");
  await page.getByLabel("Email").fill("customer@foodai.com");
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/restaurants/);

  // 2. Browse restaurants — Spice Garden should be visible
  await expect(page.getByText("Spice Garden")).toBeVisible();

  // 3. Open the menu and add two items
  await page.getByText("Spice Garden").first().click();
  await expect(
    page.getByRole("heading", { name: "Spice Garden" }).last()
  ).toBeVisible();
  const addButtons = page.getByRole("button", { name: "ADD" });
  await addButtons.first().click();
  await addButtons.first().click(); // qty 2 of the first item
  await page.getByRole("button", { name: "ADD" }).nth(1).click(); // second item

  // 4. Go to checkout via the sticky cart bar
  await page.getByRole("link", { name: "View cart →" }).click();
  await expect(page).toHaveURL(/\/checkout/);

  // 5. Apply a valid promo
  await page.getByPlaceholder("WELCOME10").fill("WELCOME10");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByText("Promo code applied!")).toBeVisible();
  await expect(page.getByText("Promo discount")).toBeVisible();

  // 6. Place the order
  await page.getByRole("button", { name: "Place order" }).click();
  await expect(page).toHaveURL(/\/tracking\/\d+/);

  // 7. Live tracking page renders order info + AI ETA
  await expect(page.getByRole("heading", { name: "Live tracking" })).toBeVisible();
  await expect(page.getByText("AI ETA")).toBeVisible();
  await expect(page.getByText(/~?(\d+)/).first()).toBeVisible();
  await expect(page.getByText(/live updates|polling fallback/)).toBeVisible();

  // Capture the order id for follow-up tests
  const orderId = page.url().match(/\/tracking\/(\d+)/)?.[1];
  expect(orderId).toBeTruthy();
  test.info().annotations.push({ type: "orderId", description: orderId });
});
