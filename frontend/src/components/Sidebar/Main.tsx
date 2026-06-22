import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import { ChevronRight, Star } from "lucide-react"
import { useMemo, useState } from "react"

import { cn } from "@/lib/utils"
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import type { Item, NavGroup } from "./nav"

export type { Item, NavGroup }

interface MainProps {
  pinned: Item[]
  groups: NavGroup[]
}

// Starred pages, persisted across sessions.
const FAV_KEY = "sf-sidebar-favorites"
function loadFavorites(): string[] {
  try {
    const raw = localStorage.getItem(FAV_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function Main({ pinned, groups }: MainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const currentPath = useRouterState({ select: (s) => s.location.pathname })

  const [favorites, setFavorites] = useState<string[]>(loadFavorites)
  const toggleFavorite = (path: string) =>
    setFavorites((prev) => {
      const next = prev.includes(path)
        ? prev.filter((p) => p !== path)
        : [...prev, path]
      try {
        localStorage.setItem(FAV_KEY, JSON.stringify(next))
      } catch {
        /* ignore quota / privacy-mode errors */
      }
      return next
    })

  // Resolve favorited paths back to nav items (skips any that no longer exist).
  const allItems = useMemo(() => groups.flatMap((g) => g.items), [groups])
  const favItems = favorites
    .map((p) => allItems.find((it) => it.path === p))
    .filter((it): it is Item => Boolean(it))

  const handleMenuClick = () => {
    if (isMobile) setOpenMobile(false)
  }

  const renderItem = (item: Item) => {
    const fav = favorites.includes(item.path)
    return (
      <SidebarMenuItem key={item.title}>
        <SidebarMenuButton
          tooltip={item.title}
          isActive={currentPath === item.path}
          asChild
        >
          <RouterLink to={item.path} onClick={handleMenuClick}>
            <item.icon />
            <span>{item.title}</span>
          </RouterLink>
        </SidebarMenuButton>
        <SidebarMenuAction
          showOnHover={!fav}
          aria-label={fav ? `Remove ${item.title} from favorites` : `Add ${item.title} to favorites`}
          title={fav ? "Remove from Favorites" : "Add to Favorites"}
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            toggleFavorite(item.path)
          }}
        >
          <Star className={cn(fav && "fill-info text-info")} />
        </SidebarMenuAction>
      </SidebarMenuItem>
    )
  }

  return (
    <>
      {pinned.length > 0 && (
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>{pinned.map(renderItem)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      )}

      {favItems.length > 0 && (
        <SidebarGroup>
          <SidebarGroupLabel className={GROUP_LABEL_CLS}>
            <span className="flex items-center gap-1.5">
              <Star className="size-3.5 fill-info text-info" />
              Favorites
            </span>
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>{favItems.map(renderItem)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      )}

      {groups.map((group) => (
        <NavGroupSection key={group.label} group={group} renderItem={renderItem} />
      ))}
    </>
  )
}

// Section titles: blue, uppercase, a touch larger + bolder than the links so the
// menu's structure reads at a glance.
const GROUP_LABEL_CLS =
  "text-[0.9375rem] font-semibold uppercase tracking-wide text-info/90"

function NavGroupSection({
  group,
  renderItem,
}: {
  group: NavGroup
  renderItem: (item: Item) => React.ReactNode
}) {
  const { state } = useSidebar()
  // Groups start expanded; users can collapse the ones they don't need.
  const [open, setOpen] = useState(true)
  // In icon-collapsed mode the labels/toggles are hidden, so always show items.
  const showItems = open || state === "collapsed"

  return (
    <SidebarGroup>
      <SidebarGroupLabel asChild className={GROUP_LABEL_CLS}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex w-full cursor-pointer items-center justify-between hover:text-info"
        >
          <span>{group.label}</span>
          <ChevronRight
            className={cn("transition-transform duration-200", open && "rotate-90")}
          />
        </button>
      </SidebarGroupLabel>
      {showItems && (
        <SidebarGroupContent>
          <SidebarMenu>{group.items.map(renderItem)}</SidebarMenu>
        </SidebarGroupContent>
      )}
    </SidebarGroup>
  )
}
