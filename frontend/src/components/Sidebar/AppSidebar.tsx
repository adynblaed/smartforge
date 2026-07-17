import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { useFeatures } from "@/hooks/useFeatures"
import { Main } from "./Main"
import { visibleNavGroups } from "./nav"
import { User } from "./User"

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { enabled } = useFeatures()

  // Shared nav model (also drives the shell breadcrumbs + landing page).
  // Superuser-only and feature-gated items are filtered per user tier.
  const groups = visibleNavGroups(!!currentUser?.is_superuser, enabled)

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
