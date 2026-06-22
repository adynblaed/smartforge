import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { Main } from "./Main"
import { NAV_GROUPS } from "./nav"
import { User } from "./User"

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  // Shared nav model (also drives the shell breadcrumbs). Filter superuser-only
  // items (e.g. Admin) and drop any group left empty.
  const groups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((it) => !it.superuserOnly || currentUser?.is_superuser),
  })).filter((g) => g.items.length > 0)

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main pinned={[]} groups={groups} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
