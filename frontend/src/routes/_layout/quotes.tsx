import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Download, Eye, FileDown, FileText } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { sf } from "@/smartforge/api"
import { KpiTile, OrderStatusBadge, PageHeader, Panel } from "@/smartforge/components"
import {
  downloadPurchaseOrderPdf,
  downloadQuotePdf,
  makePoNumber,
  openPurchaseOrderPdf,
} from "@/smartforge/pdf"
import type { Page, Quote } from "@/smartforge/types"

export const Route = createFileRoute("/_layout/quotes")({
  component: QuotesPage,
  head: () => ({ meta: [{ title: "Quotes & Intake - Smart Forge" }] }),
})

function QuotesPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Order Intake & PO Builder"
        description="AI-assisted quoting and one-click generation of formal Quote & Purchase Order PDFs."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <POReview />
        <QuoteBuilder />
      </div>
    </div>
  )
}

// Review pane: every purchase order with a color-coded status, viewable or
// downloadable as a formal PDF.
function POReview() {
  const { data } = useQuery({
    queryKey: ["quotes"],
    queryFn: () => sf.get<Page<Quote>>("/quotes"),
  })

  return (
    <Panel title="PO Review">
      <ul className="divide-y">
        {data?.data.map((q) => {
          const po = makePoNumber(q)
          return (
            <li key={q.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <OrderStatusBadge status={q.status} />
                  <span className="truncate text-sm font-medium">
                    {q.customer} — {q.part_type} ×{q.quantity}
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {po} · ${q.estimated_price.toFixed(0)}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button size="sm" variant="outline" onClick={() => openPurchaseOrderPdf(q, po)}>
                  <Eye size={14} /> View
                </Button>
                <Button size="sm" variant="outline" onClick={() => downloadPurchaseOrderPdf(q, po)}>
                  <Download size={14} /> Download
                </Button>
              </div>
            </li>
          )
        })}
        {data?.data.length === 0 && (
          <li className="py-3 text-sm text-muted-foreground">No purchase orders yet.</li>
        )}
      </ul>
    </Panel>
  )
}

function QuoteBuilder() {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    customer: "",
    part_type: "",
    quantity: 100,
    rush: false,
  })
  const { data } = useQuery({
    queryKey: ["quotes"],
    queryFn: () => sf.get<Page<Quote>>("/quotes"),
  })
  const generate = useMutation({
    mutationFn: () => sf.post<Quote>("/quotes/generate", form),
    onSettled: () => qc.invalidateQueries({ queryKey: ["quotes"] }),
  })

  return (
    <Panel title="Quote & PO Builder">
      <form
        className="mb-4 space-y-2"
        onSubmit={(e) => {
          e.preventDefault()
          generate.mutate()
        }}
      >
        <Input
          placeholder="Customer"
          value={form.customer}
          onChange={(e) => setForm({ ...form, customer: e.target.value })}
        />
        <Input
          placeholder="Part type"
          value={form.part_type}
          onChange={(e) => setForm({ ...form, part_type: e.target.value })}
        />
        <div className="flex items-center gap-3">
          <Input
            type="number"
            placeholder="Quantity"
            value={form.quantity}
            onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.rush}
              onChange={(e) => setForm({ ...form, rush: e.target.checked })}
            />
            Rush
          </label>
          <Button type="submit" disabled={generate.isPending}>
            Generate
          </Button>
        </div>
      </form>

      {generate.data && (
        <div className="mb-4 space-y-3">
          <div className="grid grid-cols-3 gap-2">
            <KpiTile label="Price" value={`$${generate.data.estimated_price.toFixed(0)}`} />
            <KpiTile label="Margin" value={`${(generate.data.margin_estimate * 100).toFixed(0)}%`} />
            <KpiTile label="Timeline" value={`${generate.data.timeline_days}d`} />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => downloadQuotePdf(generate.data!)}>
              <FileText size={14} /> Download Draft
            </Button>
            <Button
              size="sm"
              onClick={() => downloadPurchaseOrderPdf(generate.data!, makePoNumber(generate.data!))}
            >
              <FileDown size={14} /> Export PDF
            </Button>
          </div>
        </div>
      )}

      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr className="border-b">
            <th className="py-2 pr-4">Customer</th>
            <th className="py-2 pr-4">Part</th>
            <th className="py-2 pr-4">Status</th>
            <th className="py-2 pr-4">Price</th>
            <th className="py-2">Artifacts</th>
          </tr>
        </thead>
        <tbody>
          {data?.data.map((q) => (
            <tr key={q.id} className="border-b">
              <td className="py-2 pr-4">{q.customer}</td>
              <td className="py-2 pr-4">{q.part_type} ×{q.quantity}</td>
              <td className="py-2 pr-4">
                <OrderStatusBadge status={q.status} />
              </td>
              <td className="py-2 pr-4 tabular-nums">${q.estimated_price.toFixed(0)}</td>
              <td className="py-2">
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => downloadQuotePdf(q)}
                    className="inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] hover:bg-accent"
                  >
                    <FileText size={12} /> Draft
                  </button>
                  <button
                    type="button"
                    onClick={() => downloadPurchaseOrderPdf(q, makePoNumber(q))}
                    className="inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] hover:bg-accent"
                  >
                    <Download size={12} /> PO
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}
