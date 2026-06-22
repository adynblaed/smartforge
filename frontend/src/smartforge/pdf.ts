import { jsPDF } from "jspdf"

import { spaceGroteskBold, spaceGroteskRegular } from "./fonts/spaceGrotesk"
import type { Quote } from "./types"

// Professional Quote / Purchase Order artifacts generated client-side from the
// PO Builder. Branded "Future Form" — an all-black, refined treatment set
// entirely in Space Grotesk (embedded below for jsPDF).

const MARGIN = 16
const RIGHT = 194
const INK: [number, number, number] = [17, 17, 20]
const BLACK: [number, number, number] = [10, 10, 12] // masthead
const MUTED: [number, number, number] = [110, 112, 120]
const FAINT: [number, number, number] = [205, 207, 214]
const LINE: [number, number, number] = [223, 224, 230]
const BAND: [number, number, number] = [243, 243, 245] // table header fill

const FONT = "SpaceGrotesk"

// Register the embedded Space Grotesk faces on a doc (normal + bold).
function useFont(doc: jsPDF): jsPDF {
  doc.addFileToVFS("SpaceGrotesk-Regular.ttf", spaceGroteskRegular)
  doc.addFont("SpaceGrotesk-Regular.ttf", FONT, "normal")
  doc.addFileToVFS("SpaceGrotesk-Bold.ttf", spaceGroteskBold)
  doc.addFont("SpaceGrotesk-Bold.ttf", FONT, "bold")
  doc.setFont(FONT, "normal")
  return doc
}

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

// All-black masthead with the wordmark and a right-aligned document badge.
function header(doc: jsPDF, kind: string, ref: string): number {
  doc.setFillColor(...BLACK)
  doc.rect(0, 0, 210, 27, "F")

  doc.setFont(FONT, "bold")
  doc.setFontSize(20)
  doc.setTextColor(255, 255, 255)
  doc.text("FUTURE FORM", MARGIN, 14)
  doc.setFont(FONT, "normal")
  doc.setFontSize(7.5)
  doc.setTextColor(...FAINT)
  doc.text("SMART FACTORY SYSTEMS", MARGIN, 19.5)
  doc.text("599 E Nugget Ave · Sparks NV 89431 · sales@futureform.com", MARGIN, 23.5)

  // document badge (right)
  doc.setFont(FONT, "bold")
  doc.setFontSize(13)
  doc.setTextColor(255, 255, 255)
  doc.text(kind.toUpperCase(), RIGHT, 13, { align: "right" })
  doc.setFont(FONT, "normal")
  doc.setFontSize(8)
  doc.setTextColor(...FAINT)
  doc.text(ref, RIGHT, 18.5, { align: "right" })
  doc.text(`ISSUED ${new Date().toISOString().slice(0, 10)}`, RIGHT, 22.5, {
    align: "right",
  })

  // thin black rule under the masthead
  doc.setDrawColor(...INK)
  doc.setLineWidth(0.5)
  doc.line(MARGIN, 34, RIGHT, 34)
  return 46
}

function field(doc: jsPDF, label: string, value: string, x: number, y: number): void {
  doc.setFont(FONT, "bold")
  doc.setFontSize(7.5)
  doc.setTextColor(...MUTED)
  doc.text(label.toUpperCase(), x, y)
  doc.setFont(FONT, "normal")
  doc.setFontSize(10.5)
  doc.setTextColor(...INK)
  doc.text(value || "—", x, y + 6)
}

function parties(doc: jsPDF, left: [string, string], right: [string, string], y: number): number {
  field(doc, left[0], left[1], MARGIN, y)
  field(doc, right[0], right[1], 112, y)
  return y + 18
}

function lineItems(doc: jsPDF, q: Quote, startY: number): number {
  const unit = q.quantity > 0 ? q.estimated_price / q.quantity : q.estimated_price
  let y = startY

  // table header band (light) with bold dark labels
  doc.setFillColor(...BAND)
  doc.rect(MARGIN, y - 5, RIGHT - MARGIN, 9, "F")
  doc.setFont(FONT, "bold")
  doc.setFontSize(8)
  doc.setTextColor(...INK)
  doc.text("DESCRIPTION", MARGIN + 2, y)
  doc.text("QTY", 120, y, { align: "right" })
  doc.text("UNIT", 152, y, { align: "right" })
  doc.text("AMOUNT", RIGHT - 2, y, { align: "right" })
  y += 11

  doc.setFont(FONT, "normal")
  doc.setFontSize(10)
  doc.setTextColor(...INK)
  doc.text(`${q.part_type} [${q.rush ? "RUSH" : "STANDARD"}]`, MARGIN + 2, y)
  doc.text(String(q.quantity), 120, y, { align: "right" })
  doc.text(money(unit), 152, y, { align: "right" })
  doc.text(money(q.estimated_price), RIGHT - 2, y, { align: "right" })
  y += 6
  doc.setDrawColor(...LINE)
  doc.setLineWidth(0.3)
  doc.line(MARGIN, y, RIGHT, y)
  y += 10

  // totals box (right)
  const boxX = 128
  doc.setFont(FONT, "normal")
  doc.setFontSize(9.5)
  doc.setTextColor(...MUTED)
  doc.text("Subtotal", boxX, y)
  doc.setTextColor(...INK)
  doc.text(money(q.estimated_price), RIGHT - 2, y, { align: "right" })
  y += 6
  doc.setTextColor(...MUTED)
  doc.text("Tax / handling", boxX, y)
  doc.setTextColor(...INK)
  doc.text(money(0), RIGHT - 2, y, { align: "right" })
  y += 4
  doc.setDrawColor(...INK)
  doc.setLineWidth(0.5)
  doc.line(boxX, y, RIGHT, y)
  y += 6
  doc.setFont(FONT, "bold")
  doc.setFontSize(11.5)
  doc.setTextColor(...INK)
  doc.text("TOTAL", boxX, y)
  doc.text(money(q.estimated_price), RIGHT - 2, y, { align: "right" })
  return y + 12
}

function footer(doc: jsPDF, note: string): void {
  doc.setDrawColor(...INK)
  doc.setLineWidth(0.5)
  doc.line(MARGIN, 272, RIGHT, 272)
  doc.setFont(FONT, "normal")
  doc.setFontSize(7.5)
  doc.setTextColor(...MUTED)
  doc.text(note, MARGIN, 278)
  doc.text("Future Form · futureform.com", RIGHT, 278, { align: "right" })
}

function buildQuote(q: Quote): jsPDF {
  const doc = useFont(new jsPDF())
  let y = header(doc, "QUOTE", `Prepared for ${q.customer}`)
  y = parties(doc, ["Bill to", q.customer], ["Lead time", `${q.timeline_days} days`], y)
  y = lineItems(doc, q, y + 2)
  doc.setFont(FONT, "normal")
  doc.setFontSize(9.5)
  doc.setTextColor(...MUTED)
  doc.text(`Margin estimate: ${(q.margin_estimate * 100).toFixed(0)}%`, MARGIN, y)
  if (q.risk_flags) {
    y += 6
    doc.text(`Risk flags: ${q.risk_flags}`, MARGIN, y)
  }
  footer(doc, "This quotation is valid for 30 days from the date above.")
  return doc
}

function buildPO(q: Quote, poNumber: string): jsPDF {
  const doc = useFont(new jsPDF())
  let y = header(doc, "PURCHASE ORDER", poNumber)
  y = parties(
    doc,
    ["Vendor / customer", q.customer],
    ["Ship to", "Future Form · Receiving Dock"],
    y,
  )
  y = lineItems(doc, q, y + 2)
  doc.setFont(FONT, "normal")
  doc.setFontSize(9.5)
  doc.setTextColor(...MUTED)
  doc.text(`Requested delivery: ${q.timeline_days} days`, MARGIN, y)
  y += 6
  doc.text("Payment terms: Net 30", MARGIN, y)

  doc.setFont(FONT, "bold")
  doc.setFontSize(9)
  doc.setTextColor(...INK)
  doc.text("AUTHORIZED BY", MARGIN, 250)
  doc.setDrawColor(...INK)
  doc.setLineWidth(0.4)
  doc.line(MARGIN, 260, 86, 260)
  doc.setFont(FONT, "normal")
  doc.setFontSize(8)
  doc.setTextColor(...MUTED)
  doc.text("Future Form Procurement", MARGIN, 265)
  footer(doc, "Governed by Future Form standard procurement terms.")
  return doc
}

export function downloadQuotePdf(q: Quote): void {
  buildQuote(q).save(
    `Quote-${q.customer.replace(/\s+/g, "_")}-${q.part_type.replace(/\s+/g, "_")}.pdf`,
  )
}

export function downloadPurchaseOrderPdf(q: Quote, poNumber: string): void {
  buildPO(q, poNumber).save(`${poNumber}.pdf`)
}

// Open the PO in a new browser tab for a quick "View".
export function openPurchaseOrderPdf(q: Quote, poNumber: string): void {
  buildPO(q, poNumber).output("dataurlnewwindow")
}

// Deterministic-enough PO number for a generated artifact. The customer tag
// falls back to "FF" (never "PO") so the number never renders as "PO-PO-…".
export function makePoNumber(q: Quote): string {
  const tag = q.customer.replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase() || "FF"
  const n = Math.abs(
    Array.from(q.id).reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7),
  )
  return `PO-${tag}-${(n % 9000) + 1000}`
}
