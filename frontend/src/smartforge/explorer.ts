// Query-builder model for the governed dataset endpoints
// (GET /warehouse/datasets/{dataset}). Pure functions + field registry —
// unit-tested in tests-unit/explorer.test.ts. The server re-validates
// everything (allowlisted columns + operators, bound values); this module
// only builds the documented `column__op=value` grammar.

export type FieldType = "text" | "number" | "date" | "enum"

export interface ExplorerField {
  key: string
  label: string
  type: FieldType
  /** Fixed choices rendered as a select (enum fields only). */
  options?: string[]
}

export interface OperatorOption {
  value: string
  label: string
}

/** Operators the backend allowlists, narrowed per field type (IQ-004). */
export const OPERATORS: Record<FieldType, OperatorOption[]> = {
  text: [
    { value: "eq", label: "is" },
    { value: "neq", label: "is not" },
    { value: "contains", label: "contains" },
  ],
  enum: [
    { value: "eq", label: "is" },
    { value: "neq", label: "is not" },
  ],
  number: [
    { value: "eq", label: "=" },
    { value: "gte", label: "≥" },
    { value: "lte", label: "≤" },
    { value: "gt", label: ">" },
    { value: "lt", label: "<" },
  ],
  date: [
    { value: "eq", label: "on" },
    { value: "gte", label: "on or after" },
    { value: "lte", label: "on or before" },
  ],
}

/**
 * The certified api.api_work_orders contract, as a query-builder registry.
 * Keep in sync with dbt/models/api/api_work_orders.sql (additive, API-016).
 */
export const WORK_ORDER_FIELDS: ExplorerField[] = [
  { key: "wo_number", label: "WO number", type: "text" },
  { key: "item_no", label: "Item", type: "text" },
  { key: "title", label: "Title", type: "text" },
  { key: "status", label: "Status", type: "text" },
  { key: "priority", label: "Priority", type: "text" },
  { key: "current_operation", label: "Current operation", type: "text" },
  { key: "sales_order_no", label: "Sales order", type: "text" },
  { key: "machine_code", label: "Machine", type: "text" },
  {
    key: "genealogy_depth",
    label: "Genealogy level",
    type: "enum",
    options: ["0", "1", "2"],
  },
  {
    key: "is_closed",
    label: "Closed",
    type: "enum",
    options: ["true", "false"],
  },
  {
    key: "is_leaf",
    label: "Leaf order",
    type: "enum",
    options: ["true", "false"],
  },
  { key: "child_count", label: "Child count", type: "number" },
  { key: "qty_ordered", label: "Qty ordered", type: "number" },
  { key: "qty_completed", label: "Qty completed", type: "number" },
  { key: "cost_total", label: "Total cost", type: "number" },
  { key: "due_at", label: "Due date", type: "date" },
  { key: "scheduled_at", label: "Scheduled date", type: "date" },
  { key: "work_order_uid", label: "Work order UUID", type: "text" },
  { key: "parent_work_order_uid", label: "Parent UUID", type: "text" },
  { key: "root_work_order_uid", label: "Root UUID", type: "text" },
]

export interface FilterClause {
  field: string
  op: string
  value: string
}

export function fieldFor(
  fields: ExplorerField[],
  key: string,
): ExplorerField | undefined {
  return fields.find((f) => f.key === key)
}

/** A clause participates in the query only when fully specified. */
export function clauseIsComplete(clause: FilterClause): boolean {
  return Boolean(clause.field && clause.op && clause.value.trim() !== "")
}

/**
 * Build the documented query string: `field=value` for equality,
 * `field__op=value` otherwise, plus order/limit. Incomplete clauses are
 * skipped (a half-typed row must not 422 the whole query).
 */
export function buildDatasetQuery(
  clauses: FilterClause[],
  options: { orderBy?: string; orderDir?: "asc" | "desc"; limit?: number } = {},
): string {
  const params = new URLSearchParams()
  for (const clause of clauses) {
    if (!clauseIsComplete(clause)) continue
    const key =
      clause.op === "eq" ? clause.field : `${clause.field}__${clause.op}`
    params.set(key, clause.value.trim())
  }
  if (options.orderBy) {
    params.set("order_by", options.orderBy)
    params.set("order_dir", options.orderDir ?? "asc")
  }
  params.set("limit", String(options.limit ?? 100))
  return params.toString()
}

/** Human summary of the genealogy level, mirroring the industry naming. */
export function genealogyLevelLabel(depth: number | null | undefined): string {
  if (depth === null || depth === undefined) return "—"
  if (depth === 0) return "root"
  if (depth === 1) return "child"
  if (depth === 2) return "grandchild"
  return `level ${depth}`
}
