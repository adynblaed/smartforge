// TS mirrors of the backend Public schemas (kept minimal — only fields the UI uses).

export type Page<T> = { data: T[]; count: number }

export interface Machine {
  id: string
  code: string
  name: string
  machine_type: string
  status: "running" | "idle" | "fault" | "maintenance" | "offline"
  maintenance_state: string
  health_score: number
  runtime_hours: number
  last_fault_code: string | null
  line_id: string | null
  pos_x: number
  pos_z: number
}

export interface TelemetryEvent {
  id: string
  machine_id: string
  temperature: number
  vibration: number
  cycle_time: number
  power_draw: number
  fault_code: string | null
  line_status: string
  created_at: string | null
}

export interface Alert {
  id: string
  machine_id: string
  rule: string
  severity: "low" | "medium" | "high" | "critical"
  message: string
  recommended_action: string | null
  suggested_window: string | null
  status: "active" | "acknowledged" | "resolved"
  created_at: string | null
}

export interface WorkOrder {
  id: string
  machine_id: string
  fault_type: string
  severity: string
  recommended_task: string
  required_skill: string | null
  priority: number
  status: string
  fiix_sync_state: string
  fiix_id: string | null
}

export type TicketStatus =
  | "open"
  | "acknowledged"
  | "in_progress"
  | "resolved"
  | "closed"

export interface Ticket {
  id: string
  code: string
  title: string
  machine_id: string | null
  machine_code: string | null
  alert_id: string | null
  incident_id: string | null
  severity: "low" | "medium" | "high" | "critical"
  status: TicketStatus
  what_happened: string
  executive_summary: string
  operator_detail: string
  remediation: string
  sop_id: string | null
  sop_anchor: string | null
  suggested_window_days: number
  acknowledged_by: string | null
  acknowledged_at: string | null
  acknowledged_tz: string | null
  created_at: string | null
}

export interface TicketPart {
  id: string
  name: string
  qty_needed: number
  inventory_item_id: string | null
  sku: string | null
  on_hand: number
  unit: string
  lead_time_days: number
  supplier_name: string | null
  supplier_status: string | null
  needed_by: string | null
  order_by: string | null
  in_stock: boolean
  shortfall: number
}

export interface TicketLog {
  id: string
  kind: "system" | "acknowledgement" | "note" | "status_change"
  author_email: string | null
  message: string
  tz: string | null
  created_at: string | null
}

export interface TicketDetail extends Ticket {
  machine_name: string | null
  sop_code: string | null
  incident_title: string | null
  parts: TicketPart[]
  logs: TicketLog[]
}

export interface TicketReference {
  code: string
  kind: "ticket" | "sop" | "kb"
  id: string
  title: string
}

export interface Sop {
  id: string
  code: string
  title: string
  category: string
  entity_type: string
  machine_id: string | null
  summary: string
  revision: string
  created_at: string | null
}

export interface SopSection {
  id: string
  sop_id: string
  anchor: string
  order_index: number
  title: string
  body: string
}

export interface SopDetail extends Sop {
  machine_code: string | null
  sections: SopSection[]
}

export interface SourceRef {
  document_id: string
  title: string
  /** "sop" | "forge_fact" | "document" | machine-doc kind */
  kind: string
  /** Retrieved excerpt, rendered as markdown in the collapsible citation. */
  snippet?: string
  /** SOP code (e.g. "SOP-CNC-001") or KB id — used to deep-link the source. */
  code?: string | null
  /** SOP section anchor for deep-link scrolling. */
  anchor?: string | null
}

export interface AskResponse {
  answer: string
  sources: SourceRef[]
  suggested_actions: string[]
  confidence: number
  session_id: string | null
}

/** Cinematic camera directive for the Factory Simulation (the "Simulation Tool"). */
export interface SimFocus {
  mode: "machine" | "fleet" | "logistics" | "inventory" | "reset" | "none"
  machine_ids: string[]
  follow_forklift: boolean
  label: string
  /** Explicit world point to center on (used for line devices not in `machines`). */
  point?: { x: number; z: number } | null
}

export interface ForgeResponse extends AskResponse {
  /** Machine ids ForgeAI located for this query — highlighted in the scene. */
  highlight: string[]
  /** Where the simulation camera should fly / what it should follow. */
  focus?: SimFocus | null
}

export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  content: string
  created_at: string | null
  updated_at: string | null
}

export interface CommandCenter {
  factory_health_summary: {
    avg_health: number
    machines: number
    at_risk: { code: string; health: number }[]
  }
  kpis: Record<string, number>
  risk_alerts: Alert[]
  production_status: { avg_oee: number; throughput: number }
  maintenance_status: { open_work_orders: number; active_alerts: number }
  customer_impact: { delayed_orders: number }
}

export interface OeeMetric {
  id: string
  line_id: string
  shift: string
  availability: number
  performance: number
  quality: number
  oee: number
  scrap_rate: number
  rework_rate: number
  throughput: number
}

export interface Defect {
  id: string
  defect_type: string
  part_id: string | null
  scrap_cost: number
  is_scrap: boolean
  created_at: string | null
}

export interface InventoryItem {
  id: string
  sku: string
  name: string
  material_type?: string | null
  quantity: number
  unit?: string
  reorder_threshold: number
  supplier_id?: string | null
  below_threshold: boolean
}

export type ReorderStatus = "pending" | "approved" | "adjusted" | "cancelled"

export interface MaterialReorder {
  id: string
  sku: string
  inventory_item_id: string | null
  status: ReorderStatus
  quantity: number
  reason: string | null
  machine_code: string | null
  line: string | null
  scheduled_for: string | null
  signed_off_by: string | null
  signed_off_at: string | null
  created_at: string | null
}

export interface CustomerOrder {
  id: string
  order_number: string
  part_type: string
  quantity: number
  stage: string
  estimated_completion: string | null
  delayed: boolean
  delay_reason: string | null
}

export interface MachineConfiguration {
  id: string
  machine_id: string
  version: number
  is_current: boolean
  is_recommended: boolean
  approved: boolean
  performance_delta: number
  speed: number
  temperature: number
  pressure: number
  feed_rate: number
  tooling_profile: string | null
  material_type: string | null
}

export interface Recommendation {
  id: string
  machine_id: string | null
  line_id: string | null
  category: string
  title: string
  detail: string | null
  confidence: number
  status: "pending" | "accepted" | "rejected"
  outcome_impact: number | null
  created_at: string | null
}

export interface Incident {
  id: string
  title: string
  affected_machines: string | null
  delayed_orders: number
  downtime_minutes: number
  estimated_cost: number
  severity: string
  resolved: boolean
  created_at: string | null
}

export interface RcaRecord {
  id: string
  incident_id: string
  root_cause: string
  corrective_actions: string | null
  timeline_note: string | null
}

export interface PurchaseOrder {
  id: string
  po_number: string
  amount: number
  status: string
  shop_floor_ready: boolean
  supplier_id: string | null
  job_id: string | null
  customer_order_id: string | null
  inventory_item_id: string | null
  created_at: string | null
}

export interface Quote {
  id: string
  customer: string
  part_type: string
  quantity: number
  estimated_price: number
  margin_estimate: number
  timeline_days: number
  risk_flags: string | null
  status: string
  rush: boolean
}

export interface Escalation {
  id: string
  question: string
  ai_confidence: number
  reason: string | null
  assigned_team: string | null
  status: "open" | "assigned" | "resolved"
  original_ai_answer: string | null
  human_response: string | null
  created_at: string | null
}

export interface IntegrationStatus {
  system: string
  connected: boolean
  last_successful_sync: string | null
  failed_records: number
  total_events: number
}

export interface IntegrationsStatus {
  erp: IntegrationStatus
  mes: IntegrationStatus
}

export interface SyncEvent {
  id: string
  entity_type: string
  direction: string
  status: string
  detail: string | null
  created_at: string | null
}

export interface Supplier {
  id: string
  name: string
  status: string
  lead_time_days: number
}
