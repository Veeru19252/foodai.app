import { expect, test } from "@playwright/test";

/**
 * Full customer journey: login → browse two restaurants → build a
 * multi-restaurant cart → checkout with a promo → place a batch order →
 * live tracking page loads with the AI ETA.
 */
test("customer places a multi-restaurant order and sees live tracking", async ({
  page,
}) => {
  // 1. Login as the demo customer
  await page.goto("/login");
  await page.getByLabel("Email").fill("customer@foodai.com");
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/restaurants/);

  // 2. Browse restaurants — Spice Garden should be visible
  //    (.first(): the AI recommendation row also shows it above the grid)
  await expect(page.getByText("Spice Garden").first()).toBeVisible();

  // 3. Open Spice Garden and add two items
  await page.getByText("Spice Garden").first().click();
  await expect(
    page.getByRole("heading", { name: "Spice Garden" }).last()
  ).toBeVisible();
  const addButtons = page.getByRole("button", { name: "ADD" });
  await addButtons.first().click();
  await addButtons.first().click(); // qty 2 of the first item
  await page.getByRole("button", { name: "ADD" }).nth(1).click(); // second item
  await page.getByRole("button", { name: "Close" }).click();

  // 4. Add an item from a second restaurant (multi-restaurant cart)
  //    (.first() because "Dosa Plaza" also appears in the AI recommendation row)
  await page.getByText("Dosa Plaza").first().click();
  await expect(
    page.getByRole("heading", { name: "Dosa Plaza" }).last()
  ).toBeVisible();
  await page.getByRole("button", { name: "ADD" }).first().click();
  await page.getByRole("button", { name: "Close" }).click();

  // 5. Go to checkout via the sticky cart bar
  await page.getByRole("link", { name: "View cart →" }).click();
  await expect(page).toHaveURL(/\/checkout/);

  // 6. The summary shows both restaurant groups
  await expect(page.getByText("Spice Garden")).toBeVisible();
  await expect(page.getByText("Dosa Plaza")).toBeVisible();

  // 7. Apply a valid promo
  await page.getByPlaceholder("WELCOME10").fill("WELCOME10");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByText("Promo code applied!")).toBeVisible();
  await expect(page.getByText("Promo discount")).toBeVisible();

  // 8. Place the batch order
  await page.getByRole("button", { name: /Place.*2 orders/ }).click();
  await expect(page).toHaveURL(/\/tracking\/\d+/);

  // 9. Live tracking page renders order info + AI ETA
  await expect(page.getByRole("heading", { name: "Live tracking" })).toBeVisible();
  await expect(page.getByText("AI ETA")).toBeVisible();
  await expect(page.getByText(/~?(\d+)/).first()).toBeVisible();
  await expect(page.getByText(/live updates|polling fallback/)).toBeVisible();

  // 10. AI explainability panel breaks down the ETA into factors
  await page.getByText("Why this ETA?").click();
  await expect(page.getByText(/The model scores/)).toBeVisible();
  // Contribution rows show signed minute impacts (e.g. "+2.3 min" / "−1.1 min")
  await expect(page.getByText(/\d+\.\d\s*min/).first()).toBeVisible();

  // Capture the order id for follow-up tests
  const orderId = page.url().match(/\/tracking\/(\d+)/)?.[1];
  expect(orderId).toBeTruthy();
  test.info().annotations.push({ type: "orderId", description: orderId });

  // 11. Both orders appear under "My orders"
  await page.goto("/orders");
  await expect(page.getByText("Spice Garden").first()).toBeVisible();
  await expect(page.getByText("Dosa Plaza").first()).toBeVisible();
});
