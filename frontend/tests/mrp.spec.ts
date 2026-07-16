import { expect, test } from "@playwright/test"

// MRP page (time-phased supply planning over the certified
// api.api_mrp_supply_plan warehouse contract). Like the Data Platform page,
// an unprovisioned sandbox must degrade to the informative empty state —
// never a crash. Uses the authenticated superuser state.

test("mrp page renders shell + breadcrumbs", async ({ page }) => {
  await page.goto("/mrp")
  await expect(page.getByRole("heading", { name: "MRP" })).toBeVisible()
  const bc = page.getByTestId("breadcrumbs")
  await expect(bc).toBeVisible()
  await expect(bc.getByText("Datasources")).toBeVisible()
  await expect(bc.getByText("MRP")).toBeVisible()
})

test("sidebar exposes MRP under Datasources below Data Platform", async ({
  page,
}) => {
  await page.goto("/command-center")
  const links = page.getByRole("link")
  const dataPlatform = await links
    .filter({ hasText: "Data Platform" })
    .first()
    .boundingBox()
  const mrp = await links.filter({ hasText: "MRP" }).first().boundingBox()
  expect(dataPlatform).not.toBeNull()
  expect(mrp).not.toBeNull()
  if (dataPlatform && mrp) expect(mrp.y).toBeGreaterThan(dataPlatform.y)
  await page.getByRole("link", { name: "MRP" }).click()
  await expect(page).toHaveURL(/\/mrp/)
  await expect(page.getByRole("heading", { name: "MRP" })).toBeVisible()
})

test("mrp renders the planning grid or the not-provisioned state", async ({
  page,
}) => {
  await page.goto("/mrp")
  // Either the seeded plan grid (summary cards + legend + table) or the
  // informative unprovisioned card — never a blank page or error boundary.
  const grid = page.getByText("Supply Planning Grid")
  const emptyState = page.getByText("Data platform not provisioned")
  await expect(grid.or(emptyState).first()).toBeVisible({ timeout: 15000 })
  const provisioned = await grid.isVisible().catch(() => false)
  if (provisioned) {
    await expect(page.getByText("Shortage Days")).toBeVisible()
    await expect(page.getByText("Items Short")).toBeVisible()
    await expect(page.getByText("Below Safety Stock")).toBeVisible()
    await expect(
      page.getByRole("button", { name: /Reset what-if/ }),
    ).toBeVisible()
  }
  await expect(page.getByText(/Something went wrong/i)).toHaveCount(0)
})
