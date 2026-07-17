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

import { OmegaIcon } from "@/components/Sidebar/OmegaIcon"

// Single source of truth for app navigation — consumed by the sidebar
// (AppSidebar) AND the shell breadcrumbs (RouteBreadcrumbs) so the two always
// stay in parity.

export type Item = {
  icon: LucideIcon
  title: string
  path: string
  superuserOnly?: boolean
  /** Site-wide feature gate key (GET /features); gated items stay hidden
   * until the server resolves the gate open for this user's tier. */
  feature?: string
}

export type NavGroup = {
  label: string
  items: Item[]
}

/** One filter shared by the sidebar and the landing page so both surfaces
 * always agree on what this user can see. */
export function visibleNavGroups(
  isSuperuser: boolean,
  featureEnabled: (key: string) => boolean,
): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => {
      if (item.superuserOnly && !isSuperuser) return false
      if (item.feature && !isSuperuser && !featureEnabled(item.feature))
        return false
      return true
    }),
  })).filter((group) => group.items.length > 0)
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
    label: "Smart Services",
    items: [
      { icon: Database, title: "EDA", path: "/eda" },
      { icon: CalendarRange, title: "MRP", path: "/mrp" },
      { icon: OmegaIcon as LucideIcon, title: "Omega", path: "/omega" },
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
    label: "Purchase Orders",
    items: [
      { icon: PackageCheck, title: "Order Tracker", path: "/order-tracker" },
      { icon: Boxes, title: "Supply Chain", path: "/supply-chain" },
      { icon: FileText, title: "Quotes & Intake", path: "/quotes" },
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
    label: "Dashboards",
    items: [
      {
        icon: BarChart3,
        title: "Analytics",
        path: "/analytics",
        feature: "analytics_exec",
      },
      { icon: Users, title: "Admin", path: "/admin", superuserOnly: true },
      {
        icon: Terminal,
        title: "Logs",
        path: "/logs",
        feature: "logs_console",
      },
    ],
  },
  {
    label: "Datasources",
    items: [
      { icon: Table2, title: "Service Tables", path: "/datasources" },
      { icon: BookOpen, title: "Forge Facts", path: "/knowledge-bases" },
      { icon: ScrollText, title: "SOPs", path: "/sops" },
      { icon: LifeBuoy, title: "Feedback", path: "/feedback" },
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
