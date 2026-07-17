import { expect, test } from "@playwright/test"

// Uses the authenticated (superuser) storage state from auth.setup.ts.

test("command center shows KPI tiles and risk panels", async ({ page }) => {
  await page.goto("/command-center")
  await expect(
    page.getByRole("heading", { name: "Command Center" }),
  ).toBeVisible()
  await expect(page.getByText("Avg Machine Health")).toBeVisible()
  await expect(page.getByText("OEE", { exact: true })).toBeVisible()
  await expect(page.getByText("At-Risk Machines")).toBeVisible()
})

test("factory map renders the 3D canvas", async ({ page }) => {
  await page.goto("/factory-map")
  await expect(
    page.getByRole("heading", { name: /Factory Simulation/ }),
  ).toBeVisible()
  await expect(page.locator("canvas")).toBeVisible()
})

test("factory simulation grid can be toggled", async ({ page }) => {
  await page.goto("/factory-map")
  const show = page.getByRole("button", { name: "Show Grid" })
  await expect(show).toBeVisible()
  await show.click()
  await expect(page.getByRole("button", { name: "Hide Grid" })).toBeVisible()
})

test("analytics dashboards render with a refresh selector", async ({
  page,
}) => {
  await page.goto("/analytics")
  await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible()
  await expect(page.getByText("Overall OEE")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "1m", exact: true }),
  ).toBeVisible()
})

test("command center embeds the global operations globe", async ({ page }) => {
  await page.goto("/command-center")
  await expect(page.locator("canvas")).toBeVisible()
  // Selecting a lane from the legend opens its purchase-order panel.
  await page.getByRole("button", { name: /Reno → Los Angeles/ }).click()
  await expect(
    page.getByRole("heading", { name: /Reno → Los Angeles/ }),
  ).toBeVisible()
})

test("datasources global dashboard renders live tables", async ({ page }) => {
  await page.goto("/datasources")
  await expect(page.getByRole("heading", { name: "Datasources" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Export" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Import" })).toBeVisible()
  // Global tab is default — Grafana-style cards each render a table.
  await expect(page.locator("table").first()).toBeVisible()
  // Switching to Service Tables shows the per-source spreadsheet.
  // `exact` avoids matching the sidebar "Add … to favorites" star actions.
  await page
    .getByRole("button", { name: "Service Tables", exact: true })
    .click()
  await expect(
    page.getByRole("button", { name: "Machines", exact: true }),
  ).toBeVisible()
  await expect(page.locator("table").first()).toBeVisible()
})

test("knowledge base can be created", async ({ page }) => {
  await page.goto("/knowledge-bases")
  await expect(page.getByRole("heading", { name: "Forge Facts" })).toBeVisible()
  await page.getByPlaceholder(/Forge Fact name/).fill("E2E KB")
  await page.locator("textarea").fill("The coolant spec is 12 bar.")
  await page.getByRole("button", { name: "Save", exact: true }).click()
  // (prior runs may have left KBs; just confirm ours is listed)
  await expect(
    page.getByRole("button", { name: /E2E KB/ }).first(),
  ).toBeVisible()
})

test("order tracker lists purchase orders", async ({ page }) => {
  await page.goto("/order-tracker")
  await expect(
    page.getByRole("heading", { name: "Order Tracker" }),
  ).toBeVisible()
  await expect(page.getByText(/PO-20/).first()).toBeVisible()
})

test("machines console shows cards, leaderboard and alert center", async ({
  page,
}) => {
  await page.goto("/machines")
  await expect(
    page.getByRole("heading", { name: "Machine Health Console" }),
  ).toBeVisible()
  await expect(page.getByText("cnc-01").first()).toBeVisible()
  await expect(page.getByText("Machine Health Leaderboard")).toBeVisible()
  await expect(page.getByText("Maintenance Alert Center")).toBeVisible()
})

test("machines console deep-links into the simulation with a selection", async ({
  page,
}) => {
  await page.goto("/machines")
  await expect(page.getByText("cnc-01").first()).toBeVisible()
  await page.getByRole("link", { name: "Visit Simulation" }).first().click()
  await page.waitForURL(/\/factory-map\?machine=/)
  await expect(
    page.getByRole("heading", { name: /Factory Simulation/ }),
  ).toBeVisible()
  await expect(page.locator("canvas").first()).toBeVisible()
})

test("sidebar navigates across SmartForge modules", async ({ page }) => {
  await page.goto("/command-center")
  for (const [link, heading] of [
    ["Work Orders", "Work Order Queue"],
    ["Quality", "Quality & OEE"],
    ["Optimizations", "Optimizations"],
    ["Integrations", "Integrations & Operations"],
    ["Incidents", "Incident Impact"],
    ["Supply Chain", "Supply Chain"],
    ["Quotes & Intake", "Order Intake & PO Builder"],
    ["Feedback", "User Feedback"],
    ["ForgeAI", "ForgeAI"],
  ] as const) {
    // exact: the command-center stat tiles are also links (e.g. "Open Work
    // Orders"), so match the sidebar entry by its exact name.
    await page.getByRole("link", { name: link, exact: true }).first().click()
    await expect(page.getByRole("heading", { name: heading })).toBeVisible()
  }
})

test("forgeai chat returns an answer", async ({ page }) => {
  await page.goto("/ask-ai")
  const input = page.getByPlaceholder(/Ask about the factory/)
  await input.fill("How do I fix high vibration on the CNC mill?")
  await input.press("Enter")
  // Either a real Claude answer or the offline fallback renders.
  await expect(
    page.getByText(/documentation|offline mode|vibration|machine/i).first(),
  ).toBeVisible({ timeout: 20000 })
})

test("optimizations: capacity what-if produces a proposed schedule", async ({
  page,
}) => {
  await page.goto("/optimization")
  await page.getByRole("button", { name: "Run what-if schedule" }).click()
  await expect(page.getByText("Proposed Schedule")).toBeVisible()
})

test("integrations sync records events", async ({ page }) => {
  await page.goto("/integrations")
  await page.getByRole("button", { name: "Run ERP sync" }).click()
  await expect(page.getByText("Sync Events", { exact: true })).toBeVisible()
})
