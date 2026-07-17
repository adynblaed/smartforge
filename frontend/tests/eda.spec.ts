import { expect, test } from "@playwright/test"

// EDA observability page (front-to-back over /api/v1/platform, /warehouse
// and /lake). In a freshly provisioned sandbox those stores may not exist
// yet and every section must degrade to its informative empty state —
// never a crash or a blank screen. Uses the authenticated superuser state
// (chromium project depends on the auth setup, same as validation.spec.ts).

test("eda page renders shell + breadcrumbs", async ({ page }) => {
  await page.goto("/eda")
  await expect(
    page.getByRole("heading", { name: "Exploratory Data Analysis" }),
  ).toBeVisible()
  const bc = page.getByTestId("breadcrumbs")
  await expect(bc).toBeVisible()
  await expect(bc.getByText("Smart Services")).toBeVisible()
  await expect(bc.getByText("EDA")).toBeVisible()
})

test("sidebar exposes EDA under Smart Services", async ({ page }) => {
  await page.goto("/command-center")
  await page.getByRole("link", { name: "EDA", exact: true }).click()
  await expect(page).toHaveURL(/\/eda/)
  await expect(
    page.getByRole("heading", { name: "Exploratory Data Analysis" }),
  ).toBeVisible()
})

test("every section renders data or the not-provisioned empty state", async ({
  page,
}) => {
  await page.goto("/eda")
  for (const title of [
    "Recent Updates",
    "Work Orders Explorer",
    "Warehouse Marts & Datasets",
    "Lake Datasets & Load Manifests",
  ]) {
    await expect(page.getByText(title, { exact: true })).toBeVisible()
  }
  // Health tiles are always present, provisioned or not.
  await expect(page.getByText("Tables Tracked")).toBeVisible()
  // Graceful degradation: a section shows either a data table or the
  // informative empty state pointing at the runbooks — never nothing.
  const anyTable = page.locator("table").first()
  const emptyState = page.getByText("Data platform not provisioned").first()
  await expect(anyTable.or(emptyState)).toBeVisible({ timeout: 15000 })
  // And in no case does the router error boundary take over the page.
  await expect(page.getByText(/Something went wrong/i)).toHaveCount(0)
})

test("work orders explorer exposes the read-only query builder", async ({
  page,
}) => {
  await page.goto("/eda")
  await expect(page.getByRole("button", { name: "Run query" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Add filter" })).toBeVisible()
  await expect(page.getByText("certified · read-only")).toBeVisible()
  // Results area shows either rows or an informative empty/unprovisioned
  // state — the builder never crashes the page.
  await expect(page.getByText(/Something went wrong/i)).toHaveCount(0)
})
