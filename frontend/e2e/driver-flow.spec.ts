import { expect, test } from "@playwright/test";
import { completeCheckoutGate, completeOnboarding } from "./helpers";

/**
 * Driver workflow: a driver is logged in and connected to the notification
 * channel when a restaurant assigns them a delivery. They get a real-time
 * notification, see the delivery in their dashboard, and start the trip.
 */
test("driver receives assignment notification and starts delivery", async ({
  browser,
}) => {
  // Driver logs in first so the notification WebSocket is live.
  const driverContext = await browser.newContext();
  const driver = await driverContext.newPage();
  await driver.goto("/login");
  await driver.getByLabel("Email").fill("rider@foodai.com");
  await driver.getByLabel("Password").fill("password123");
  await driver.getByRole("button", { name: "Log in" }).click();
  await expect(driver).toHaveURL(/\/driver/);
  await expect(driver.getByRole("button", { name: "Notifications" })).toBeVisible();

  // This suite runs against the shared demo database, so notification rows
  // can leak between runs. Open and close the tray to acknowledge anything
  // left over, making the badge assertion below exact.
  await driver.getByRole("button", { name: "Notifications" }).click();
  await driver.getByRole("button", { name: "Notifications" }).click();

  // Customer places an order at Dosa Plaza.
  const customerContext = await browser.newContext();
  const customer = await customerContext.newPage();
  await customer.goto("/login");
  await customer.getByLabel("Email").fill("customer@foodai.com");
  await customer.getByLabel("Password").fill("password123");
  await customer.getByRole("button", { name: "Log in" }).click();
  await completeOnboarding(customer);
  await customer.getByText("Dosa Plaza").first().click();
  await customer.getByRole("button", { name: "ADD" }).first().click();
  await customer.getByRole("link", { name: "View cart →" }).click();
  await completeCheckoutGate(customer);
  await customer.getByRole("button", { name: /Place.*order/ }).click();
  await expect(customer).toHaveURL(/\/tracking\/\d+/);
  const orderUrl = customer.url();
  const orderId = orderUrl.match(/\/tracking\/(\d+)/)?.[1];
  expect(orderId).toBeTruthy();

  // Restaurant assigns rider@foodai.com to the order (does NOT dispatch).
  const restaurantContext = await browser.newContext();
  const restaurant = await restaurantContext.newPage();
  await restaurant.goto("/login");
  await restaurant.getByLabel("Email").fill("dosa@foodai.com");
  await restaurant.getByLabel("Password").fill("password123");
  await restaurant.getByRole("button", { name: "Log in" }).click();
  await expect(restaurant).toHaveURL(/\/restaurant\/orders/);

  const orderCard = restaurant.getByTestId(`restaurant-order-${orderId}`);
  await expect(orderCard).toBeVisible();
  await orderCard.getByRole("button", { name: /Mark confirmed/i }).click();
  await expect(orderCard.getByText("PREPARING")).toBeVisible({ timeout: 10_000 });
  await orderCard.getByRole("button", { name: /Mark preparing/i }).click();
  await orderCard.getByLabel("Select delivery driver").selectOption({ label: "Rider Ram (rider@foodai.com)" });
  await orderCard.getByRole("button", { name: /Assign driver/i }).click();
  await expect(orderCard.getByText(/Assigned to.*Rider Ram/)).toBeVisible({ timeout: 10_000 });

  // The driver's notification bell gets the real-time assignment.
  await expect(driver.getByRole("button", { name: "Notifications" })).toContainText("1", {
    timeout: 15_000,
  });
  await driver.getByRole("button", { name: "Notifications" }).click();
  await expect(
    driver.getByText(new RegExp(`New delivery assigned for order #${orderId}`))
  ).toBeVisible();

  // The driver dashboard lists the delivery with a "Start delivery" action.
  await driver.goto("/driver");
  const deliveryCard = driver.getByTestId(`driver-delivery-${orderId}`);
  await expect(deliveryCard).toBeVisible({ timeout: 10_000 });
  await deliveryCard.getByRole("button", { name: /Start delivery/i }).click();
  await expect(deliveryCard.getByRole("link", { name: "Navigate" })).toBeVisible({ timeout: 10_000 });

  // The customer's live tracking page now reflects OUT FOR DELIVERY.
  await customer.goto(orderUrl);
  await expect(customer.getByText("OUT FOR DELIVERY")).toBeVisible({ timeout: 10_000 });

  await driverContext.close();
  await customerContext.close();
  await restaurantContext.close();
});
