import { expect, test } from "@playwright/test"

// MRP page (time-phased supply planning over the certified
// mrp_supply_plan warehouse contract, v1). Like the EDA page, an
// unprovisioned sandbox must degrade to the informative empty state —
// never a crash. Uses the authenticated superuser state.

test("mrp page renders shell + breadcrumbs", async ({ page }) => {
  await page.goto("/mrp")
  await expect(
    page.getByRole("heading", { name: "Material Requirements Planner" }),
  ).toBeVisible()
  const bc = page.getByTestId("breadcrumbs")
  await expect(bc).toBeVisible()
  await expect(bc.getByText("Smart Services")).toBeVisible()
  await expect(bc.getByText("MRP")).toBeVisible()
})

test("sidebar exposes MRP under Smart Services below EDA", async ({ page }) => {
  await page.goto("/command-center")
  const links = page.getByRole("link")
  const eda = await links.filter({ hasText: /^EDA$/ }).first().boundingBox()
  const mrp = await links.filter({ hasText: "MRP" }).first().boundingBox()
  expect(eda).not.toBeNull()
  expect(mrp).not.toBeNull()
  if (eda && mrp) expect(mrp.y).toBeGreaterThan(eda.y)
  await page.getByRole("link", { name: "MRP" }).click()
  await expect(page).toHaveURL(/\/mrp/)
  await expect(
    page.getByRole("heading", { name: "Material Requirements Planner" }),
  ).toBeVisible()
})

test("mrp renders the planning grid or the not-provisioned state", async ({
  page,
}) => {
  await page.goto("/mrp")
  // Either the seeded plan grid (summary cards + legend + table) or the
  // informative unprovisioned card — never a blank page or error boundary.
  const grid = page.getByText("Supply Planning Grid", { exact: true })
  const emptyState = page.getByText("Data platform not provisioned")
  await expect(grid.or(emptyState).first()).toBeVisible({ timeout: 15000 })
  const provisioned = await grid.isVisible().catch(() => false)
  if (provisioned) {
    await expect(page.getByText("Shortage Days")).toBeVisible()
    await expect(page.getByText("Items Short")).toBeVisible()
    // Exact: the KPI tile is "Below Safety Stock"; the seeded grid's legend
    // also renders a "Below safety stock" chip (case differs).
    await expect(
      page.getByText("Below Safety Stock", { exact: true }),
    ).toBeVisible()
    await expect(
      page.getByRole("button", { name: /Reset what-if/ }),
    ).toBeVisible()
  }
  await expect(page.getByText(/Something went wrong/i)).toHaveCount(0)
})
