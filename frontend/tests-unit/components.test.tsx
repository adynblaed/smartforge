import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  healthColor,
  healthHex,
  KpiTile,
  StatusBadge,
} from "@/smartforge/components"

describe("health color helpers", () => {
  it("maps score bands to semantic tokens", () => {
    expect(healthColor(95)).toContain("success")
    expect(healthColor(65)).toContain("warning")
    expect(healthColor(30)).toContain("danger")
  })

  it("maps score bands to hex", () => {
    expect(healthHex(95)).toBe("#10b981")
    expect(healthHex(65)).toBe("#f59e0b")
    expect(healthHex(30)).toBe("#ef4444")
  })

  it("uses boundary at 80 and 60", () => {
    expect(healthHex(80)).toBe("#10b981")
    expect(healthHex(79)).toBe("#f59e0b")
    expect(healthHex(60)).toBe("#f59e0b")
    expect(healthHex(59)).toBe("#ef4444")
  })
})

describe("KpiTile", () => {
  it("renders label, value and hint", () => {
    render(<KpiTile label="OEE" value="84%" hint="line 01" />)
    expect(screen.getByText("OEE")).toBeInTheDocument()
    expect(screen.getByText("84%")).toBeInTheDocument()
    expect(screen.getByText("line 01")).toBeInTheDocument()
  })
})

describe("StatusBadge", () => {
  it("renders the status text", () => {
    render(<StatusBadge value="critical" />)
    expect(screen.getByText("critical")).toBeInTheDocument()
  })
})
