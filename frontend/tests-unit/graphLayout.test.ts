import { describe, expect, it } from "vitest"

import { buildWorkOrderGraph, nodeScale } from "@/smartforge/graphLayout"
import type { ApiWorkOrderRow } from "@/smartforge/platformTypes"

const row = (patch: Partial<ApiWorkOrderRow>): ApiWorkOrderRow => ({
  work_order_uid: "u",
  work_order_id: 1,
  wo_number: "WO-1",
  parent_work_order_uid: null,
  root_work_order_uid: null,
  genealogy_depth: 0,
  genealogy_path: null,
  child_count: 0,
  is_leaf: true,
  title: null,
  wo_type: null,
  item_no: null,
  qty_ordered: 10,
  qty_completed: 5,
  status: "OR",
  priority: null,
  current_operation: null,
  sales_order_no: null,
  sales_order_line: null,
  machine_code: null,
  scheduled_at: null,
  due_at: null,
  completed_at: null,
  is_closed: false,
  labor_hours: null,
  cost_total: null,
  load_id: null,
  extracted_at: null,
  ...patch,
})

const family = [
  row({ work_order_uid: "root", genealogy_depth: 0 }),
  row({
    work_order_uid: "child-a",
    parent_work_order_uid: "root",
    root_work_order_uid: "root",
    genealogy_depth: 1,
  }),
  row({
    work_order_uid: "child-b",
    parent_work_order_uid: "root",
    root_work_order_uid: "root",
    genealogy_depth: 1,
  }),
  row({
    work_order_uid: "grandchild",
    parent_work_order_uid: "child-a",
    root_work_order_uid: "root",
    genealogy_depth: 2,
  }),
  row({ work_order_uid: "loner", genealogy_depth: 0 }),
]

describe("buildWorkOrderGraph", () => {
  it("creates one node per row and one edge per surviving parent link", () => {
    const g = buildWorkOrderGraph(family)
    expect(g.nodes).toHaveLength(5)
    // root→child-a, root→child-b, child-a→grandchild
    expect(g.edges).toHaveLength(3)
    for (const e of g.edges) {
      expect(g.nodes[e.from]).toBeDefined()
      expect(g.nodes[e.to]).toBeDefined()
    }
  })

  it("clusters a family around its root and separates strangers", () => {
    const g = buildWorkOrderGraph(family)
    const pos = new Map(g.nodes.map((n) => [n.uid, n.position]))
    const dist = (a: string, b: string) => {
      const p = pos.get(a)
      const q = pos.get(b)
      if (!p || !q) throw new Error("missing node")
      return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])
    }
    // family members sit closer to their root than the unrelated order
    expect(dist("root", "child-a")).toBeLessThan(dist("root", "loner"))
    expect(dist("child-a", "grandchild")).toBeLessThan(dist("child-a", "loner"))
  })

  it("keeps siblings together even when the root row was filtered out", () => {
    const orphans = [
      row({
        work_order_uid: "child-a",
        parent_work_order_uid: "gone",
        root_work_order_uid: "gone",
        genealogy_depth: 1,
      }),
      row({
        work_order_uid: "child-b",
        parent_work_order_uid: "gone",
        root_work_order_uid: "gone",
        genealogy_depth: 1,
      }),
    ]
    const g = buildWorkOrderGraph(orphans)
    expect(g.nodes.every((n) => n.rootUid === "gone")).toBe(true)
    // no edge to the missing parent
    expect(g.edges).toHaveLength(0)
  })

  it("is deterministic for the same input", () => {
    const a = buildWorkOrderGraph(family)
    const b = buildWorkOrderGraph([...family].reverse())
    const byUid = (g: typeof a) =>
      new Map(g.nodes.map((n) => [n.uid, n.position.join(",")]))
    expect(byUid(a)).toEqual(byUid(b))
  })

  it("handles the empty result set", () => {
    const g = buildWorkOrderGraph([])
    expect(g.nodes).toHaveLength(0)
    expect(g.edges).toHaveLength(0)
    expect(g.radius).toBeGreaterThan(0)
  })
})

describe("nodeScale", () => {
  it("shrinks with depth so roots anchor each constellation", () => {
    expect(nodeScale(0)).toBeGreaterThan(nodeScale(1))
    expect(nodeScale(1)).toBeGreaterThan(nodeScale(2))
  })
})

describe("value-correlated node size", () => {
  it("prefers cost as the magnitude and scales size with it", () => {
    const g = buildWorkOrderGraph([
      row({ work_order_uid: "big", cost_total: 90_000 }),
      row({ work_order_uid: "small", cost_total: 1_000 }),
    ])
    expect(g.sizeMetric).toBe("cost")
    const size = new Map(g.nodes.map((n) => [n.uid, n.size]))
    const big = size.get("big")
    const small = size.get("small")
    if (big === undefined || small === undefined) throw new Error("missing")
    expect(big).toBeGreaterThan(small)
  })

  it("falls back to quantity when no row carries cost", () => {
    const g = buildWorkOrderGraph([
      row({ work_order_uid: "a", cost_total: null, qty_ordered: 500 }),
      row({ work_order_uid: "b", cost_total: null, qty_ordered: 5 }),
    ])
    expect(g.sizeMetric).toBe("qty")
  })

  it("keeps sizes bounded so one huge order cannot dwarf the field", () => {
    const g = buildWorkOrderGraph([
      row({ work_order_uid: "whale", cost_total: 10_000_000 }),
      row({ work_order_uid: "minnow", cost_total: 1 }),
    ])
    const sizes = g.nodes.map((n) => n.size)
    expect(Math.max(...sizes) / Math.min(...sizes)).toBeLessThan(4)
  })
})
