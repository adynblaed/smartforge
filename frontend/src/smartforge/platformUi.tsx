// Shared UI primitives for the data-platform-backed pages (Data Platform,
// MRP): the per-section query hook, informative degradation, and the sticky
// mini table. Kept out of the route files so both pages render governed data
// with one visual and failure-handling grammar.

import { type UseQueryResult, useQuery } from "@tanstack/react-query"
import { DatabaseZap } from "lucide-react"
import { type ReactNode, useEffect, useRef } from "react"

import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { Loading } from "@/smartforge/components"

// Freshness-style sections poll on a 30s heartbeat; catalog-ish sections
// refresh each minute.
export const REFRESH_FAST = 30_000
export const REFRESH_SLOW = 60_000

// Every section gets its own query so one unprovisioned/failing store never
// blanks the others. `retry: false` because a 503 here means "not
// provisioned" (fresh sandbox) — surface the empty state immediately; the
// poll interval still picks the section up once the platform is bootstrapped.
export function usePlatform<T>(
  key: string | (string | number)[],
  path: string,
  refetchInterval = REFRESH_FAST,
) {
  return useQuery({
    queryKey: ["data-platform", ...(Array.isArray(key) ? key : [key])],
    queryFn: () => sf.get<T>(path),
    staleTime: REFRESH_FAST / 2,
    refetchInterval,
    retry: false,
  })
}

// Informative degradation: a fresh sandbox returns 503 from every
// store-backed endpoint, which must read as "not provisioned yet", never as
// a crash.
export function NotProvisioned({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error ?? "")
  const notProvisioned = msg.startsWith("503")
  return (
    <div className="flex flex-col items-center gap-1.5 rounded-lg border border-dashed px-4 py-10 text-center">
      <DatabaseZap size={20} className="text-muted-foreground" />
      <p className="text-sm font-medium">
        {notProvisioned
          ? "Data platform not provisioned"
          : "Section unavailable"}
      </p>
      <p className="max-w-md text-xs text-muted-foreground">
        {notProvisioned
          ? "This environment's platform stores are not bootstrapped yet. Run the provisioning flow (bootstrap → discovery → plan review → confirm seed) — see the runbooks/ guides."
          : msg || "The request failed; it will retry on the next poll."}
      </p>
    </div>
  )
}

export function Section<T>({
  query,
  children,
}: {
  query: UseQueryResult<T>
  children: (data: T) => ReactNode
}) {
  if (query.isPending) return <Loading />
  if (query.isError || query.data === undefined)
    return <NotProvisioned error={query.error} />
  return <>{children(query.data)}</>
}

export interface Col<T> {
  key: string
  label: string
  align?: "right"
  render: (row: T) => ReactNode
}

// Same visual grammar as the Datasources tables: sticky muted header,
// zebra rows, its own scroll container. Optional row selection (used by the
// Work Orders Explorer to correlate 3D graph nodes with table records).
export function MiniTable<T>({
  cols,
  rows,
  rowKey,
  empty,
  selectedKey,
  onRowClick,
  maxHeightClass = "max-h-96",
}: {
  cols: Col<T>[]
  rows: T[]
  rowKey: (row: T, index: number) => string
  empty: string
  selectedKey?: string | null
  onRowClick?: (row: T, index: number) => void
  /** Scroll threshold (Tailwind max-h class), e.g. ~16 rows = max-h-[35rem]. */
  maxHeightClass?: string
}) {
  const container = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!selectedKey) return
    container.current
      ?.querySelector('[data-row-selected="true"]')
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [selectedKey])
  return (
    <div
      ref={container}
      className={cn("overflow-auto rounded-md border", maxHeightClass)}
    >
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-muted/95 backdrop-blur">
          <tr>
            {cols.map((c) => (
              <th
                key={c.key}
                className={cn(
                  "whitespace-nowrap border-b border-r px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground last:border-r-0",
                  c.align === "right" && "text-right",
                )}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td
                colSpan={cols.length}
                className="px-3 py-8 text-center text-sm text-muted-foreground"
              >
                {empty}
              </td>
            </tr>
          )}
          {rows.map((row, i) => (
            <tr
              key={rowKey(row, i)}
              data-row-selected={selectedKey === rowKey(row, i) || undefined}
              className={cn(
                "odd:bg-muted/20 hover:bg-accent/40",
                onRowClick && "cursor-pointer",
                selectedKey === rowKey(row, i) &&
                  "bg-primary/15 odd:bg-primary/15 hover:bg-primary/20",
              )}
              onClick={onRowClick && (() => onRowClick(row, i))}
            >
              {cols.map((c) => (
                <td
                  key={c.key}
                  className={cn(
                    "max-w-[280px] truncate border-b border-r px-3 py-1.5 last:border-r-0",
                    c.align === "right" && "text-right tabular-nums",
                  )}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
