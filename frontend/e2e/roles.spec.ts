import { expect, test } from "@playwright/test";

/**
 * Role-based dashboards: restaurant sees incoming orders and dispatches them;
 * admin sees the platform overview. Uses the seeded demo accounts.
 */
test("restaurant dispatches an order and admin sees the dashboard", async ({
  browser,
}) => {
  // Create an order as the customer first.
  const customerContext = await browser.newContext();
  const customer = await customerContext.newPage();
  await customer.goto("/login");
  await customer.getByLabel("Email").fill("customer@foodai.com");
  await customer.getByLabel("Password").fill("password123");
  await customer.getByRole("button", { name: "Log in" }).click();
  await customer.getByText("Dosa Plaza").click();
  await customer.getByRole("button", { name: "ADD" }).first().click();
  await customer.getByRole("link", { name: "View cart →" }).click();
  await customer.getByRole("button", { name: "Place order" }).click();
  await expect(customer).toHaveURL(/\/tracking\/\d+/);
  const orderUrl = customer.url();

  // Restaurant logs in and sees the order in its queue.
  const restaurantContext = await browser.newContext();
  const restaurant = await restaurantContext.newPage();
  await restaurant.goto("/login");
  await restaurant.getByLabel("Email").fill("dosa@foodai.com");
  await restaurant.getByLabel("Password").fill("password123");
  await restaurant.getByRole("button", { name: "Log in" }).click();
  await expect(restaurant).toHaveURL(/\/restaurant\/orders/);
  await expect(restaurant.getByText("Restaurant dashboard")).toBeVisible();
  await expect(restaurant.getByText("Demo Customer").first()).toBeVisible();

  // Confirm → prepare → assign & dispatch.
  await restaurant.getByRole("button", { name: /Mark confirmed/i }).first().click();
  await expect(restaurant.getByText("PREPARING").first()).toBeVisible({ timeout: 10_000 });
  await restaurant.getByRole("button", { name: /Mark preparing/i }).first().click();
  await restaurant.getByRole("button", { name: /Assign & dispatch/i }).first().click();
  await expect(restaurant.getByText("Dispatched").first()).toBeVisible({ timeout: 10_000 });

  // Customer tracking page now reflects OUT_FOR_DELIVERY.
  await customer.goto(orderUrl);
  await expect(customer.getByText("OUT FOR DELIVERY")).toBeVisible({ timeout: 10_000 });

  // Admin dashboard renders platform stats.
  const adminContext = await browser.newContext();
  const admin = await adminContext.newPage();
  await admin.goto("/login");
  await admin.getByLabel("Email").fill("admin@foodai.com");
  await admin.getByLabel("Password").fill("password123");
  await admin.getByRole("button", { name: "Log in" }).click();
  await expect(admin).toHaveURL(/\/admin/);
  await expect(admin.getByText("Admin dashboard")).toBeVisible();
  await expect(admin.getByText("Total orders")).toBeVisible();
  await expect(admin.getByText("Revenue")).toBeVisible();

  await customerContext.close();
  await restaurantContext.close();
  await adminContext.close();
});

test("wrong password is rejected on the login page", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("customer@foodai.com");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Invalid email or password")).toBeVisible();
});
