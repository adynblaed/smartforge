import { expect, test } from "@playwright/test"

// Post-launch data validation: every page must render real, non-empty demo
// data (not zeros / empty states). Uses the authenticated superuser state.

test("command center renders live KPIs + machines", async ({ page }) => {
  await page.goto("/command-center")
  await expect(page.getByText("Avg Machine Health")).toBeVisible()
  // 3 machines are seeded — the hint only shows when the query returned data
  await expect(page.getByText(/3 machines/)).toBeVisible()
  // at-risk list shows seeded machine codes
  await expect(page.getByText(/-01/).first()).toBeVisible()
})

test("factory simulation renders the 3D canvas", async ({ page }) => {
  await page.goto("/factory-map")
  await expect(page.locator("canvas").first()).toBeVisible()
})

test("shell breadcrumbs mirror the sidebar grouping", async ({ page }) => {
  await page.goto("/tickets")
  const bc = page.getByTestId("breadcrumbs")
  await expect(bc).toBeVisible()
  await expect(bc.getByText("Machine Intelligence")).toBeVisible()
  await expect(bc.getByText("Tickets")).toBeVisible()
  // the group crumb is a link to the group's first page
  await bc.getByRole("link", { name: "Machine Intelligence" }).click()
  await expect(page).toHaveURL(/\/machines/)
  // another section resolves correctly too
  await page.goto("/order-tracker")
  await expect(
    page.getByTestId("breadcrumbs").getByText("Order Tracker"),
  ).toBeVisible()
})

test("machine click opens the same live panel as the line fixtures", async ({ page }) => {
  // Visit Simulation deep-links /factory-map?machine=<id> which auto-pins the
  // machine's EntityPanel — the same panel the PLC/Server fixtures use.
  await page.goto("/machines")
  await page.getByRole("link", { name: /Visit Simulation/i }).first().click()
  await expect(page.getByText("Active power draw")).toBeVisible({ timeout: 15000 })
})

test("machine console: 3 machines, telemetry, alerts", async ({ page }) => {
  await page.goto("/machines")
  for (const code of ["cnc-01", "arm-01", "press-01"]) {
    await expect(page.getByText(code).first()).toBeVisible()
  }
  await expect(page.getByText(/\d+°C/).first()).toBeVisible() // live telemetry
  // live 3D preview pane (same scene as the sim) renders a canvas per card
  await expect(page.locator("canvas").first()).toBeVisible()
  await expect(page.getByText("Machine Health Leaderboard")).toBeVisible()
  await expect(page.getByRole("button", { name: "Ticket" }).first()).toBeVisible()
})

test("work orders queue has rows", async ({ page }) => {
  await page.goto("/work-orders")
  await expect(page.getByRole("heading", { name: "Work Order Queue" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Approve" }).first()).toBeVisible()
})

test("quality shows OEE + defect data", async ({ page }) => {
  await page.goto("/quality")
  await expect(page.getByRole("heading", { name: "Quality & OEE" })).toBeVisible()
  await expect(page.getByText(/%/).first()).toBeVisible()
})

test("optimizations: config + capacity + simulation studio", async ({ page }) => {
  await page.goto("/optimization")
  await expect(page.getByRole("heading", { name: "Optimizations" })).toBeVisible()
  // Planning folded in: capacity what-if + per-machine simulation studio.
  await expect(page.getByText("Scheduling & Capacity", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Run what-if schedule" })).toBeVisible()
  await expect(page.getByText(/Simulation Studio/)).toBeVisible()
})

test("integrations status", async ({ page }) => {
  await page.goto("/integrations")
  await expect(page.getByRole("heading", { name: "Integrations & Operations" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Run ERP sync" })).toBeVisible()
})

test("incidents impact view", async ({ page }) => {
  await page.goto("/incidents")
  await expect(page.getByRole("heading", { name: "Incident Impact" })).toBeVisible()
})

test("supply chain risk", async ({ page }) => {
  await page.goto("/supply-chain")
  await expect(page.getByRole("heading", { name: "Supply Chain" })).toBeVisible()
  await expect(page.getByText("Supplier Risk", { exact: true })).toBeVisible()
})

test("quotes & intake", async ({ page }) => {
  await page.goto("/quotes")
  await expect(page.getByRole("heading", { name: "Order Intake & PO Builder" })).toBeVisible()
})

test("escalations panel", async ({ page }) => {
  await page.goto("/escalations")
  await expect(page.getByRole("heading", { name: "Customer Escalations" })).toBeVisible()
})

test("askai answers (no connectivity error)", async ({ page }) => {
  await page.goto("/ask-ai")
  const input = page.getByPlaceholder(/Ask about the factory/)
  await input.fill("How do I fix high vibration?")
  await input.press("Enter")
  await expect(
    page.getByText(/vibration|machine|cnc|spindle|bearing|maintenance|offline/i).first(),
  ).toBeVisible({ timeout: 20000 })
  await expect(page.getByText(/couldn't reach the assistant/)).toHaveCount(0)
})

test("analytics dashboards non-empty", async ({ page }) => {
  await page.goto("/analytics")
  await expect(page.getByText("Overall OEE")).toBeVisible()
  await expect(page.getByRole("button", { name: "1m", exact: true })).toBeVisible()
})

test("datasources global tables", async ({ page }) => {
  await page.goto("/datasources")
  await expect(page.locator("table").first()).toBeVisible()
})

test("order tracker datasource lists active POs by order", async ({ page }) => {
  await page.goto("/datasources")
  // the enriched order-tracker table joins POs to their customer order
  await expect(page.getByText("Acme Robotics").first()).toBeVisible()
  await expect(page.getByText(/PO-20/).first()).toBeVisible()
})

test("tickets center: serialized tickets, parts & SOP guidance", async ({ page }) => {
  await page.goto("/tickets")
  await expect(
    page.getByRole("heading", { name: "Maintenance Alert Center" }),
  ).toBeVisible()
  // The "All" tab always contains the seeded CNC vibration ticket regardless of
  // its current status.
  await page.getByRole("tab", { name: /All/ }).click()
  await expect(page.getByText("TICKET-0001")).toBeVisible()
  await page.getByText("CNC-01 elevated vibration").click()
  await expect(page.getByText("Parts & Materials")).toBeVisible()
  await expect(page.getByRole("button", { name: /View SOP/ })).toBeVisible()
})

test("acknowledged ticket shows user email + timestamp", async ({ page }) => {
  await page.goto("/tickets")
  await page.getByRole("tab", { name: /Acknowledged/ }).click()
  await expect(page.getByText(/Acknowledged/).first()).toBeVisible()
  await expect(page.getByText(/@smartforge\.com/).first()).toBeVisible()
})

test("sops library renders chaptered procedures + deep-link", async ({ page }) => {
  await page.goto("/sops")
  await expect(
    page.getByRole("heading", { name: /Standard Operating Procedures/ }),
  ).toBeVisible()
  await expect(page.getByText("SOP-PRESS-001").first()).toBeVisible()
  await page.goto("/sops?sop=SOP-PRESS-001&section=hydraulic-oil-service")
  await expect(page.getByText("Hydraulic Oil & Seal Service").first()).toBeVisible()
})

test("services page lists platform integrations", async ({ page }) => {
  await page.goto("/services")
  await expect(page.getByRole("heading", { name: "Services" })).toBeVisible()
  await expect(page.getByText("Platform Services")).toBeVisible()
  await expect(page.getByText("Anthropic Claude")).toBeVisible()
})

test("logs console shows per-service log lines", async ({ page }) => {
  await page.goto("/logs")
  await expect(page.getByRole("heading", { name: "Logs" })).toBeVisible()
  await expect(page.getByText("backend", { exact: true }).first()).toBeVisible()
  await expect(page.getByText(/journald/)).toBeVisible()
})

test("services health board reports live status + cross-links to logs", async ({
  page,
}) => {
  await page.goto("/services")
  await expect(page.getByText("PostgreSQL")).toBeVisible()
  // live health probe stamps a latency on the running database
  await expect(page.getByText(/Primary operational database · /)).toBeVisible()
  // a service streams to the Logs console
  await page.getByRole("link", { name: /View logs/ }).first().click()
  await expect(page).toHaveURL(/\/logs\?service=/)
  await expect(page.getByRole("heading", { name: "Logs" })).toBeVisible()
})

test("logs console exposes the real audit trail", async ({ page }) => {
  await page.goto("/logs?service=audit")
  await expect(page.getByText("audit", { exact: true }).first()).toBeVisible()
  // the audit stream surfaces real platform actions (e.g. forge.answer, login)
  await expect(page.getByText(/·\s+\w+\.\w+/).first()).toBeVisible()
})

test("machine card deep-links to its scoped SOPs", async ({ page }) => {
  await page.goto("/machines")
  await page.getByRole("link", { name: "View SOPs" }).first().click()
  await expect(page).toHaveURL(/\/sops\?machine=/)
  await expect(page.getByText(/Showing SOPs for/)).toBeVisible()
})

test("forge facts manager", async ({ page }) => {
  await page.goto("/knowledge-bases")
  await expect(page.getByRole("heading", { name: "Forge Facts" })).toBeVisible()
  await expect(page.getByRole("button", { name: "New Forge Fact" })).toBeVisible()
})

test("ForgeAI prioritizes SOPs and cites them as clickable sources", async ({
  page,
}) => {
  await page.goto("/ask-ai")
  const input = page.getByPlaceholder("Ask about the factory…")
  await input.fill(
    "What do the docs say about the CNC Mill VF-2 — Operating & Maintenance SOP?",
  )
  await input.press("Enter")
  // SOP-first RAG: the CNC SOP must be cited as a source (it exists in seed).
  const sopSource = page.getByRole("button", { name: /SOP-CNC-001/ }).first()
  await expect(sopSource).toBeVisible({ timeout: 25000 })
  // Expanding reveals the excerpt + a deep link into the SOPs page.
  await sopSource.click()
  await expect(
    page.getByRole("link", { name: /View SOP-CNC-001/ }).first(),
  ).toBeVisible()
})

test("order tracker lists purchase orders", async ({ page }) => {
  await page.goto("/order-tracker")
  await expect(page.getByText(/PO-20/).first()).toBeVisible()
})

test("site-wide ForgeAI agent toggles, answers, and persists across tabs", async ({
  page,
}) => {
  await page.goto("/command-center")
  // Closed by default → toggle is shown.
  const toggle = page.getByTestId("forge-toggle")
  await expect(toggle).toBeVisible()
  await toggle.click()
  const panel = page.getByTestId("forge-panel")
  await expect(panel).toBeVisible()
  // Ask a question via the agent.
  const input = page.getByPlaceholder("Ask about the factory…")
  await input.fill("Give me a fleet overview")
  await input.press("Enter")
  await page.waitForTimeout(12000)
  await expect(panel.getByText(/couldn't reach the assistant/)).toHaveCount(0)
  // The panel (and its conversation) lives site-wide → persists to Factory Sim.
  await page.getByRole("link", { name: "Factory Simulation" }).click()
  await expect(page.getByTestId("forge-panel")).toBeVisible()
})

test("sidebar exposes the account menu (logout)", async ({ page }) => {
  await page.goto("/command-center")
  await expect(page.getByTestId("user-menu")).toBeVisible()
})

test("stale token forces a clean relogin (no zero-data screen)", async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "stale.invalid.token"),
  )
  await page.goto("/command-center")
  // Must bounce to login instead of rendering an empty command center.
  await page.waitForURL(/\/login/, { timeout: 15000 })
})

// Validates the ACTUAL production nginx artifact (not the Vite dev server): the
// SPA calls the API same-origin and nginx proxies it to the backend.
test("nginx artifact serves data same-origin (front→back through proxy)", async ({
  page,
}) => {
  const username = process.env.FIRST_SUPERUSER
  const password = process.env.FIRST_SUPERUSER_PASSWORD
  test.skip(!username || !password, "superuser creds not in env")
  const res = await page.request.post("http://frontend/api/v1/login/access-token", {
    form: { username: username!, password: password! },
  })
  expect(res.ok()).toBeTruthy()
  const token = (await res.json()).access_token as string
  await page.addInitScript((t) => localStorage.setItem("access_token", t), token)
  await page.goto("http://frontend/command-center")
  await expect(page.getByText("Avg Machine Health")).toBeVisible({ timeout: 15000 })
  await expect(page.getByText(/3 machines/)).toBeVisible({ timeout: 15000 })
})
