import { describe, expect, it } from "vitest"

import { descendantStats, formatDescendants } from "@/smartforge/explorer"

const node = (uid: string, parent: string | null = null) => ({
  work_order_uid: uid,
  parent_work_order_uid: parent,
})

describe("descendantStats", () => {
  const family = [
    node("root"),
    node("child-a", "root"),
    node("child-b", "root"),
    node("grand-1", "child-a"),
    node("grand-2", "child-a"),
    node("loner"),
  ]

  it("counts direct children and grandchildren per node", () => {
    const stats = descendantStats(family)
    expect(stats.get("root")).toEqual({ children: 2, grandchildren: 2 })
    expect(stats.get("child-a")).toEqual({ children: 2, grandchildren: 0 })
    expect(stats.get("child-b")).toEqual({ children: 0, grandchildren: 0 })
    expect(stats.get("loner")).toEqual({ children: 0, grandchildren: 0 })
  })

  it("only counts descendants present in the loaded set", () => {
    const stats = descendantStats([node("orphan", "missing-parent")])
    expect(stats.get("orphan")).toEqual({ children: 0, grandchildren: 0 })
  })
})

describe("formatDescendants", () => {
  it("pluralizes children and grandchildren correctly", () => {
    expect(formatDescendants({ children: 1, grandchildren: 2 })).toBe(
      "1 child · 2 grandchildren",
    )
    expect(formatDescendants({ children: 2, grandchildren: 1 })).toBe(
      "2 children · 1 grandchild",
    )
  })

  it("omits zero parts and returns empty when nothing is downstream", () => {
    expect(formatDescendants({ children: 3, grandchildren: 0 })).toBe(
      "3 children",
    )
    expect(formatDescendants({ children: 0, grandchildren: 0 })).toBe("")
    expect(formatDescendants(undefined)).toBe("")
  })
})
