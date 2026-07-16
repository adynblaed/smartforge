import {
  createFileRoute,
  Outlet,
  redirect,
  useRouter,
} from "@tanstack/react-router"
import { ErrorBoundary } from "react-error-boundary"

import { ErrorFallbackCard } from "@/components/Common/ErrorComponent"
import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import { Separator } from "@/components/ui/separator"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"
import { sf } from "@/smartforge/api"
import { logClientError } from "@/smartforge/clientLog"
import { ForgeAgentProvider } from "@/smartforge/ForgeAgent"
import { NavUserMenu } from "@/smartforge/NavUserMenu"
import { RouteBreadcrumbs } from "@/smartforge/RouteBreadcrumbs"
import { UniversalSearch } from "@/smartforge/UniversalSearch"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({ to: "/login" })
    }
    // Validate the session up-front. A stale/invalid token (e.g. after a DB
    // reseed) must force a clean relogin rather than rendering a zero-data app.
    let role: string | undefined
    try {
      role = (await sf.get<{ role?: string }>("/users/me")).role
    } catch (err) {
      const msg = err instanceof Error ? err.message : ""
      if (/Unauthorized \((401|403)\)/.test(msg)) {
        localStorage.removeItem("access_token")
        throw redirect({ to: "/login" })
      }
      // Transient/non-auth error: let the page load; queries enforce access.
      return
    }
    // Throw the redirect OUTSIDE the try/catch so it is not swallowed.
    if (role === "customer") {
      throw redirect({ to: "/portal" })
    }
  },
})

function Layout() {
  const router = useRouter()
  return (
    <ForgeAgentProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur-md">
            <SidebarTrigger className="-ml-1 text-muted-foreground" />
            <Separator orientation="vertical" className="mr-1 h-5" />
            <RouteBreadcrumbs />
            {/* Centered universal search (hidden on small screens). */}
            <div className="pointer-events-none absolute left-1/2 top-1/2 hidden -translate-x-1/2 -translate-y-1/2 md:block">
              <div className="pointer-events-auto">
                <UniversalSearch />
              </div>
            </div>
            <div className="ml-auto">
              <NavUserMenu />
            </div>
          </header>
          <main className="flex-1 p-6 md:p-8">
            <div className="mx-auto max-w-7xl">
              {/* Render throws in page components keep the app shell (sidebar,
                  header) and offer a reset instead of blanking the screen. */}
              <ErrorBoundary
                FallbackComponent={ErrorFallbackCard}
                onError={(error) => logClientError("layout", error)}
                onReset={() => router.invalidate()}
              >
                <Outlet />
              </ErrorBoundary>
            </div>
          </main>
          <Footer />
        </SidebarInset>
      </SidebarProvider>
    </ForgeAgentProvider>
  )
}

export default Layout
