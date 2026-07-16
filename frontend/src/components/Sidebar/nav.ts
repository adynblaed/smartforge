import {
  BarChart3,
  BookOpen,
  Bot,
  Boxes,
  CalendarRange,
  Database,
  Factory,
  FileText,
  Gauge,
  LayoutDashboard,
  LifeBuoy,
  type LucideIcon,
  PackageCheck,
  PlugZap,
  ScrollText,
  Server,
  ShieldCheck,
  Siren,
  SlidersHorizontal,
  Table2,
  Terminal,
  Ticket,
  Users,
  Wrench,
} from "lucide-react"

// Single source of truth for app navigation — consumed by the sidebar
// (AppSidebar) AND the shell breadcrumbs (RouteBreadcrumbs) so the two always
// stay in parity.

export type Item = {
  icon: LucideIcon
  title: string
  path: string
  superuserOnly?: boolean
}

export type NavGroup = {
  label: string
  items: Item[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Smart Forge",
    items: [
      {
        icon: LayoutDashboard,
        title: "Command Center",
        path: "/command-center",
      },
      { icon: Factory, title: "Factory Simulation", path: "/factory-map" },
      { icon: Bot, title: "ForgeAI", path: "/ask-ai" },
    ],
  },
  {
    label: "Machine Intelligence",
    items: [
      { icon: Gauge, title: "Machines", path: "/machines" },
      { icon: Wrench, title: "Work Orders", path: "/work-orders" },
      { icon: Ticket, title: "Tickets", path: "/tickets" },
    ],
  },
  {
    label: "Factory Intelligence",
    items: [
      { icon: ShieldCheck, title: "Quality", path: "/quality" },
      {
        icon: SlidersHorizontal,
        title: "Optimizations",
        path: "/optimization",
      },
    ],
  },
  {
    label: "MES",
    items: [
      { icon: Server, title: "Services", path: "/services" },
      { icon: PlugZap, title: "Integrations", path: "/integrations" },
      { icon: Siren, title: "Incidents", path: "/incidents" },
    ],
  },
  {
    label: "Purchase Orders",
    items: [
      { icon: PackageCheck, title: "Order Tracker", path: "/order-tracker" },
      { icon: Boxes, title: "Supply Chain", path: "/supply-chain" },
      { icon: FileText, title: "Quotes & Intake", path: "/quotes" },
    ],
  },
  {
    label: "Customer Portals",
    items: [{ icon: LifeBuoy, title: "Escalations", path: "/escalations" }],
  },
  {
    label: "Dashboards",
    items: [
      { icon: BarChart3, title: "Analytics", path: "/analytics" },
      { icon: Users, title: "Admin", path: "/admin", superuserOnly: true },
      { icon: Terminal, title: "Logs", path: "/logs" },
    ],
  },
  {
    label: "Datasources",
    items: [
      { icon: Table2, title: "Database Tables", path: "/datasources" },
      { icon: Database, title: "Data Platform", path: "/data-platform" },
      { icon: CalendarRange, title: "MRP", path: "/mrp" },
      { icon: BookOpen, title: "Forge Facts", path: "/knowledge-bases" },
      { icon: ScrollText, title: "SOPs", path: "/sops" },
    ],
  },
]

// Internal pages reachable outside the sidebar (user menu / legacy).
const EXTRA_CRUMBS: Record<string, string> = {
  "/settings": "Account Settings",
  "/items": "Items",
}

const ROOT_GROUP = "Smart Forge"

export interface Crumb {
  title: string
  path?: string // omitted = current page (not a link)
}

function flatNav(): { group: NavGroup; item: Item }[] {
  return NAV_GROUPS.flatMap((g) => g.items.map((item) => ({ group: g, item })))
}

/** Breadcrumb trail for a pathname: SmartForge › Group › Page. */
export function breadcrumbsFor(pathname: string): Crumb[] {
  const root: Crumb = { title: "Smart Forge", path: "/command-center" }
  const hit = flatNav().find(({ item }) => item.path === pathname)
  if (hit) {
    const crumbs: Crumb[] = [root]
    // Avoid the redundant "SmartForge › Smart Forge" repeat for the root group.
    if (hit.group.label !== ROOT_GROUP) {
      crumbs.push({ title: hit.group.label, path: hit.group.items[0]?.path })
    }
    crumbs.push({ title: hit.item.title })
    return crumbs
  }
  const extra = EXTRA_CRUMBS[pathname]
  if (extra) return [root, { title: extra }]
  const seg = pathname.split("/").filter(Boolean).pop() ?? "Home"
  const title = seg
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
  return [root, { title }]
}
