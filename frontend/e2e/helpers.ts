import { expect, type Page } from "@playwright/test";

/** Random 10-digit Indian mobile (starts 6-9) to dodge the 60s OTP resend limit. */
export function randomPhone(): string {
  return `9${Math.floor(100000000 + Math.random() * 899999999)}`;
}

/**
 * Complete the pre-order verification gate at checkout:
 * 1. Confirm the delivery location (explicit checkbox).
 * 2. Verify the phone via OTP (demo auto-fills the returned code).
 *
 * Must be called on the /checkout page with items in the cart.
 */
export async function completeCheckoutGate(page: Page): Promise<void> {
  await page.getByText("Yes, deliver to this address").click();
  await page.getByPlaceholder("10-digit mobile number").fill(randomPhone());
  await page.getByRole("button", { name: "Send OTP" }).click();
  await expect(
    page.getByRole("button", { name: "Verify & continue" })
  ).toBeVisible();
  await page.getByRole("button", { name: "Verify & continue" }).click();
}
