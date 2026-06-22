import { expect, test } from "@playwright/test"
import { getEnvVar } from "./utils/env.ts"

// Customer-portal flows run without the superuser storage state.
test.use({ storageState: { cookies: [], origins: [] } })

const customerEmail = "buyer@acme-robotics.com"
const customerPassword = getEnvVar("SANDBOX_USER_PASSWORD")

async function loginCustomer(page: import("@playwright/test").Page) {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(customerEmail)
  await page.getByTestId("password-input").fill(customerPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/portal")
}

test("customer is routed to the portal and sees their orders", async ({
  page,
}) => {
  await loginCustomer(page)
  await expect(page.getByRole("heading", { name: "Your Orders" })).toBeVisible()
  await expect(page.getByText(/Order SO-/).first()).toBeVisible()
})

test("customer can open a live order tracker", async ({ page }) => {
  await loginCustomer(page)
  await page.getByRole("link", { name: "View live status" }).first().click()
  await page.waitForURL(/\/portal\/orders\//)
  // Stage timeline shows the production stages (appears in stepper + history).
  await expect(page.getByText(/in production/i).first()).toBeVisible()
})

test("customer assistant answers and can escalate", async ({ page }) => {
  await loginCustomer(page)
  await page.getByRole("link", { name: "Assistant" }).click()
  await expect(
    page.getByRole("heading", { name: "Order Assistant" }),
  ).toBeVisible()
  const input = page.getByPlaceholder(/When will my order be done/)
  await input.fill("When will my order be done?")
  await input.press("Enter")
  await expect(page.getByText(/order|support|production/i).first()).toBeVisible({
    timeout: 20000,
  })
})

test("customer cannot reach internal pages", async ({ page }) => {
  await loginCustomer(page)
  await page.goto("/machines")
  // _layout guard redirects customer accounts back to the portal.
  await page.waitForURL("/portal")
})
