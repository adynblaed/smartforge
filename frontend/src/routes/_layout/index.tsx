import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowUpRight, ChevronRight } from "lucide-react"
import { useMemo } from "react"

import { NAV_GROUPS, type NavGroup } from "@/components/Sidebar/nav"
import useAuth from "@/hooks/useAuth"
import { userDisplayName } from "@/smartforge/components"

export const Route = createFileRoute("/_layout/")({
  component: HomePage,
  head: () => ({ meta: [{ title: "Smart Forge — Home" }] }),
})

// 16:9 category thumbnails (served from public/thumbnails).
const GROUP_THUMB: Record<string, string> = {
  "Smart Forge": "/thumbnails/planetary.jpg",
  "Machine Intelligence": "/thumbnails/machine_intelligence.jpg",
  "Factory Intelligence": "/thumbnails/factory_intelligence.jpg",
  MES: "/thumbnails/mes_hook.jpg",
  "Purchase Orders": "/thumbnails/purchase_orders_rack.jpg",
  "Customer Portals": "/thumbnails/customer_orders.jpg",
  Dashboards: "/thumbnails/dashboards.jpg",
  Datasources: "/thumbnails/datasources.jpg",
}

const EMBLEM = "/favicon.svg"

// Rotating hero copy — a fresh combination is chosen on each visit.
const EYEBROWS = [
  "Smart Forge · Mission Control",
  "Smart Forge · Operations Hub",
  "Smart Forge · Control Deck",
  "Smart Forge · Command Deck",
  "Smart Forge · Flight Deck",
]
const WELCOMES = [
  "Welcome aboard",
  "Welcome back",
  "Good to see you",
  "Systems online",
  "All systems go",
  "Ready when you are",
]
const TAGLINES = [
  (n: number, m: number) =>
    `Your launchpad for the entire platform — ${n} services across ${m} domains. Choose a destination to begin.`,
  (n: number, m: number) =>
    `${n} services across ${m} domains, one console. Where to next?`,
  (n: number, m: number) =>
    `Mission control for the whole factory — ${n} services across ${m} domains at your command.`,
  (n: number, m: number) =>
    `Every system in one place — ${n} services across ${m} domains. Pick a destination.`,
  (n: number, m: number) =>
    `The whole platform, ready to launch — ${n} services across ${m} domains.`,
]
const pick = <T,>(arr: T[]): T => arr[Math.floor(Math.random() * arr.length)]

function HomePage() {
  const { user } = useAuth()
  // Same model + superuser filtering as the sidebar.
  const groups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((it) => !it.superuserOnly || user?.is_superuser),
  })).filter((g) => g.items.length > 0)
  const totalServices = groups.reduce((n, g) => n + g.items.length, 0)

  // Fresh hero copy per visit.
  const hero = useMemo(() => {
    const name = userDisplayName(user)
    return {
      eyebrow: pick(EYEBROWS),
      welcome: `${pick(WELCOMES)}, ${name === "there" ? "Operator" : name}`,
      tagline: pick(TAGLINES)(totalServices, groups.length),
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, totalServices, groups.length])

  return (
    <div className="flex flex-col gap-8">
      {/* mission-control hero */}
      <section className="relative overflow-hidden rounded-2xl bg-card p-8 sm:p-10">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              "linear-gradient(var(--foreground) 1px, transparent 1px), linear-gradient(90deg, var(--foreground) 1px, transparent 1px)",
            backgroundSize: "44px 44px",
          }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full opacity-30 blur-3xl"
          style={{ background: "radial-gradient(circle, var(--primary), transparent 70%)" }}
        />
        <div className="relative flex flex-col gap-3">
          <span className="text-xs font-semibold uppercase tracking-[0.3em] text-info">
            {hero.eyebrow}
          </span>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            {hero.welcome}
          </h1>
          <p className="max-w-2xl text-muted-foreground">{hero.tagline}</p>
        </div>
      </section>

      {/* service directory */}
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {groups.map((g) => (
          <CategoryCard key={g.label} group={g} />
        ))}
      </div>
    </div>
  )
}

function CategoryCard({ group }: { group: NavGroup }) {
  const thumb = GROUP_THUMB[group.label]
  const first = group.items[0]?.path ?? "/command-center"

  return (
    <div className="group flex flex-col overflow-hidden rounded-2xl bg-card shadow-[var(--shadow-soft)] transition-all hover:shadow-[var(--shadow-glass)]">
      {/* 16:9 clickable banner → the group's first page */}
      <Link to={first} className="relative block aspect-video overflow-hidden">
        {thumb ? (
          <img
            src={thumb}
            alt={group.label}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.06]"
          />
        ) : (
          <div
            className="relative h-full w-full"
            style={{
              backgroundImage:
                "linear-gradient(135deg, var(--primary) 0%, color-mix(in oklab, var(--primary) 35%, #05060a) 100%)",
            }}
          >
            <img
              src={EMBLEM}
              alt=""
              aria-hidden
              className="absolute left-1/2 top-1/2 size-24 -translate-x-1/2 -translate-y-1/2 opacity-90 transition-transform duration-500 group-hover:scale-110"
            />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/25 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-2 p-4">
          <h2 className="text-lg font-semibold tracking-tight text-white drop-shadow">
            {group.label}
          </h2>
          <span className="rounded-full bg-white/15 p-1.5 text-white backdrop-blur transition-colors group-hover:bg-white/30">
            <ArrowUpRight size={16} />
          </span>
        </div>
      </Link>

      {/* service links */}
      <nav className="flex flex-col gap-0.5 p-2">
        {group.items.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-accent"
          >
            <item.icon size={16} className="shrink-0 text-muted-foreground" />
            <span className="font-medium">{item.title}</span>
            <ChevronRight
              size={15}
              className="ml-auto shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-60"
            />
          </Link>
        ))}
      </nav>
    </div>
  )
}
