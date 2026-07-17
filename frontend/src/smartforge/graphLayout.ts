// Deterministic 3D constellation layout for the Work Orders genealogy graph.
// Pure functions (no three.js) so the embedding is unit-testable.
//
// The projection follows UMAP presentation practice — related records form
// tight local clusters, unrelated clusters spread apart, color encodes a
// category — but the embedding itself is exact, not stochastic: work orders
// cluster by their genealogy root ("constellations"), with parents and
// children placed on radial shells per depth. Deterministic placement means
// the same query always renders the same map (no seed jitter between runs),
// and re-queries only move what actually changed.

import type { ApiWorkOrderRow } from "@/smartforge/platformTypes"

export interface GraphNode {
  uid: string
  row: ApiWorkOrderRow
  /** 0 = constellation root (or orphan), 1 = child, 2 = grandchild… */
  depth: number
  rootUid: string
  position: [number, number, number]
  /** Final render radius: hierarchy base × value magnitude (see below). */
  size: number
}

/** Edge endpoints as node indices into `nodes` (both always present). */
export interface GraphEdge {
  from: number
  to: number
}

export interface WorkOrderGraphModel {
  nodes: GraphNode[]
  edges: GraphEdge[]
  /** Extent of the constellation field — used to frame the camera. */
  radius: number
  /** Which magnitude drives node size ("cost" | "qty" | null). */
  sizeMetric: "cost" | "qty" | null
}

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5))

function hashStr(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

/** Stable 0..1 pseudo-random derived from the uid (never Math.random). */
const jitter = (uid: string, salt: string): number =>
  (hashStr(`${salt}:${uid}`) % 1000) / 1000

/**
 * Magnitude → size factor. Financial value when the result set carries
 * cost, quantity otherwise. Square-root mapping (perceived area, not
 * diameter, should track the value) into a bounded factor so one huge
 * order can't dwarf the field.
 */
// Postgres NUMERIC crosses the JSON boundary as a string — coerce before
// comparing or aggregating (matching eda.ts / mrp.ts boundary handling).
const asMagnitude = (value: unknown): number => {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : 0
}

export function sizeMetricFor(rows: ApiWorkOrderRow[]): "cost" | "qty" | null {
  if (rows.some((r) => asMagnitude(r.cost_total) > 0)) return "cost"
  if (rows.some((r) => asMagnitude(r.qty_ordered) > 0)) return "qty"
  return null
}

export function magnitudeOf(
  row: ApiWorkOrderRow,
  metric: "cost" | "qty" | null,
): number {
  if (metric === "cost") return asMagnitude(row.cost_total)
  if (metric === "qty") return asMagnitude(row.qty_ordered)
  return 0
}

export function sizeFactor(value: number, max: number): number {
  if (max <= 0) return 1
  return 0.65 + 1.05 * Math.sqrt(Math.min(1, value / max))
}

export function buildWorkOrderGraph(
  rows: ApiWorkOrderRow[],
): WorkOrderGraphModel {
  const byUid = new Map(rows.map((r) => [r.work_order_uid, r]))
  const sizeMetric = sizeMetricFor(rows)
  const maxMagnitude = rows.reduce(
    (max, r) => Math.max(max, magnitudeOf(r, sizeMetric)),
    0,
  )

  // Constellation key: the genealogy root when known — even if the root row
  // itself was filtered out, siblings still cluster together.
  const clusterKey = (r: ApiWorkOrderRow): string =>
    r.root_work_order_uid ?? r.work_order_uid

  const clusters = new Map<string, ApiWorkOrderRow[]>()
  for (const r of rows) {
    const key = clusterKey(r)
    const members = clusters.get(key) ?? []
    members.push(r)
    clusters.set(key, members)
  }

  // Cluster centers on a phyllotaxis spiral (galaxy plane) — the classic
  // "islands on a plane" reading of a 2.5D embedding. Sorted keys keep the
  // placement independent of row order.
  const keys = [...clusters.keys()].sort()
  const clusterSpacing = 7
  const centers = new Map<string, [number, number, number]>()
  keys.forEach((key, i) => {
    const angle = i * GOLDEN_ANGLE + jitter(key, "spin") * 0.5
    const r = clusterSpacing * Math.sqrt(i + 0.3)
    centers.set(key, [
      r * Math.cos(angle),
      (jitter(key, "lift") - 0.5) * 3,
      r * Math.sin(angle),
    ])
  })

  const nodes: GraphNode[] = []
  const indexByUid = new Map<string, number>()

  for (const key of keys) {
    const members = clusters.get(key) ?? []
    const [cx, cy, cz] = centers.get(key) ?? [0, 0, 0]

    // Depth shells: root at the center, children on a ring, grandchildren
    // on a wider ring, each shell dropping slightly so hierarchy reads at
    // a glance even before edges are drawn.
    const byDepth = new Map<number, ApiWorkOrderRow[]>()
    for (const r of members) {
      const depth = r.genealogy_depth ?? (r.parent_work_order_uid ? 1 : 0)
      const shell = byDepth.get(depth) ?? []
      shell.push(r)
      byDepth.set(depth, shell)
    }

    for (const [depth, shell] of [...byDepth.entries()].sort(
      (a, b) => a[0] - b[0],
    )) {
      shell.sort((a, b) => a.work_order_uid.localeCompare(b.work_order_uid))
      // Ring radii spaced so bodies in one constellation don't crowd their
      // origin (cluster-to-cluster spacing is set separately above).
      const ringRadius =
        depth === 0 ? 0 : depth * (2.4 + Math.min(1.6, shell.length * 0.11))
      const phase = jitter(key, `ring${depth}`) * Math.PI * 2
      shell.forEach((r, i) => {
        const angle = phase + (i / Math.max(1, shell.length)) * Math.PI * 2
        const wobble = (jitter(r.work_order_uid, "y") - 0.5) * 0.6
        const position: [number, number, number] =
          depth === 0 && shell.length === 1
            ? [cx, cy + 0.2, cz]
            : [
                cx + ringRadius * Math.cos(angle),
                cy - depth * 0.7 + wobble,
                cz + ringRadius * Math.sin(angle),
              ]
        indexByUid.set(r.work_order_uid, nodes.length)
        nodes.push({
          uid: r.work_order_uid,
          row: r,
          depth,
          rootUid: key,
          position,
          size:
            nodeScale(depth) *
            sizeFactor(magnitudeOf(r, sizeMetric), maxMagnitude),
        })
      })
    }
  }

  // Edges only where both endpoints survived the filter.
  const edges: GraphEdge[] = []
  for (const node of nodes) {
    const parentUid = node.row.parent_work_order_uid
    if (!parentUid || !byUid.has(parentUid)) continue
    const from = indexByUid.get(parentUid)
    const to = indexByUid.get(node.uid)
    if (from !== undefined && to !== undefined) edges.push({ from, to })
  }

  const radius = nodes.reduce(
    (max, n) => Math.max(max, Math.hypot(n.position[0], n.position[2])),
    4,
  )
  return { nodes, edges, radius, sizeMetric }
}

/** Node radius by hierarchy: roots read as the anchor of each constellation.
 * The grandchild floor keeps moons clearly visible even at the minimum
 * value-size factor. */
export function nodeScale(depth: number): number {
  if (depth <= 0) return 0.72
  if (depth === 1) return 0.5
  return 0.42
}
