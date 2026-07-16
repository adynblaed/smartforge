import { describe, expect, it } from "vitest"

import {
  buildDatasetQuery,
  clauseIsComplete,
  fieldFor,
  genealogyLevelLabel,
  OPERATORS,
  WORK_ORDER_FIELDS,
} from "@/smartforge/explorer"

describe("buildDatasetQuery", () => {
  it("emits equality as a bare column param", () => {
    const query = buildDatasetQuery([
      { field: "status", op: "eq", value: "OR" },
    ])
    expect(query).toBe("status=OR&limit=100")
  })

  it("emits non-equality operators with the __op suffix", () => {
    const query = buildDatasetQuery(
      [
        { field: "due_at", op: "lte", value: "2026-08-01" },
        { field: "qty_ordered", op: "gte", value: "10" },
      ],
      { orderBy: "due_at", orderDir: "desc", limit: 250 },
    )
    const params = new URLSearchParams(query)
    expect(params.get("due_at__lte")).toBe("2026-08-01")
    expect(params.get("qty_ordered__gte")).toBe("10")
    expect(params.get("order_by")).toBe("due_at")
    expect(params.get("order_dir")).toBe("desc")
    expect(params.get("limit")).toBe("250")
  })

  it("skips incomplete clauses instead of sending broken filters", () => {
    const query = buildDatasetQuery([
      { field: "item_no", op: "contains", value: "  " },
      { field: "", op: "eq", value: "x" },
      { field: "status", op: "eq", value: "OR" },
    ])
    expect(query).toBe("status=OR&limit=100")
  })

  it("url-encodes values so raw input never breaks the query string", () => {
    const query = buildDatasetQuery([
      { field: "title", op: "contains", value: "door & panel=50%" },
    ])
    expect(new URLSearchParams(query).get("title__contains")).toBe(
      "door & panel=50%",
    )
  })
})

describe("clauseIsComplete", () => {
  it("requires field, operator, and a non-blank value", () => {
    expect(clauseIsComplete({ field: "status", op: "eq", value: "OR" })).toBe(
      true,
    )
    expect(clauseIsComplete({ field: "status", op: "eq", value: " " })).toBe(
      false,
    )
    expect(clauseIsComplete({ field: "", op: "eq", value: "x" })).toBe(false)
  })
})

describe("field registry", () => {
  it("every field maps to a supported operator set", () => {
    for (const field of WORK_ORDER_FIELDS) {
      expect(OPERATORS[field.type].length).toBeGreaterThan(0)
    }
  })

  it("enum fields carry their fixed choices", () => {
    expect(fieldFor(WORK_ORDER_FIELDS, "genealogy_depth")?.options).toEqual([
      "0",
      "1",
      "2",
    ])
    expect(fieldFor(WORK_ORDER_FIELDS, "is_closed")?.options).toEqual([
      "true",
      "false",
    ])
  })
})

describe("genealogyLevelLabel", () => {
  it("uses the industry naming for the three levels", () => {
    expect(genealogyLevelLabel(0)).toBe("root")
    expect(genealogyLevelLabel(1)).toBe("child")
    expect(genealogyLevelLabel(2)).toBe("grandchild")
    expect(genealogyLevelLabel(3)).toBe("level 3")
    expect(genealogyLevelLabel(null)).toBe("—")
  })
})
