import { expect, type Locator, type Page } from "@playwright/test";

/** Random 10-digit Indian mobile (starts 6-9) to dodge the 60s OTP resend limit. */
export function randomPhone(): string {
  return `9${Math.floor(100000000 + Math.random() * 899999999)}`;
}

/** True when the locator becomes visible within the timeout, false otherwise. */
async function isVisible(locator: Locator, timeout = 3_000): Promise<boolean> {
  try {
    await locator.waitFor({ state: "visible", timeout });
    return true;
  } catch {
    return false;
  }
}

/** Fill a mobile + request + verify the demo OTP (auto-filled code). */
async function verifyPhoneStep(page: Page): Promise<void> {
  await page.getByPlaceholder("10-digit mobile number").fill(randomPhone());
  await page.getByRole("button", { name: "Send OTP" }).click();
  await expect(
    page.getByRole("button", { name: "Verify & continue" })
  ).toBeVisible();
  await page.getByRole("button", { name: "Verify & continue" }).click();
}

/**
 * Complete first-run onboarding whenever the gate shows after login:
 * 1. Confirm the delivery location (the default Bengaluru preset is pre-selected).
 * 2. Verify the phone via OTP only if the gate still asks for it.
 *
 * The gate can be skipped entirely when this browser already onboarded the
 * customer (location persisted + phone verified in the shared DB).
 */
export async function completeOnboarding(page: Page): Promise<void> {
  const locationHeading = page.getByRole("heading", {
    name: "Where should we deliver?",
  });
  if (await isVisible(locationHeading)) {
    await page.getByRole("button", { name: "Confirm location" }).click();
  }
  const phoneHeading = page.getByRole("heading", {
    name: "One last step — verify your phone",
  });
  if (await isVisible(phoneHeading)) {
    await verifyPhoneStep(page);
  }
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
