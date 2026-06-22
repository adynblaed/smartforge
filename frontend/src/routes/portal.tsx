import {
  createFileRoute,
  Link,
  Outlet,
  redirect,
  useNavigate,
} from "@tanstack/react-router"
import { Factory, LogOut } from "lucide-react"

import { Appearance } from "@/components/Common/Appearance"
import { Button } from "@/components/ui/button"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/portal")({
  component: PortalLayout,
  beforeLoad: () => {
    if (!isLoggedIn()) throw redirect({ to: "/login" })
  },
})

function PortalLayout() {
  const navigate = useNavigate()
  const logout = () => {
    localStorage.removeItem("access_token")
    navigate({ to: "/login" })
  }
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b bg-background/95 px-6 backdrop-blur">
        <Link to="/portal" className="flex items-center gap-2 font-semibold">
          <Factory size={20} className="text-primary" />
          SmartForge Customer Portal
        </Link>
        <nav className="flex items-center gap-2">
          <Button asChild variant="ghost" size="sm">
            <Link to="/portal">My Orders</Link>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to="/portal/ask">Assistant</Link>
          </Button>
          <Appearance />
          <Button
            variant="ghost"
            size="sm"
            onClick={logout}
            aria-label="Log out"
          >
            <LogOut size={16} />
          </Button>
        </nav>
      </header>
      <main className="mx-auto max-w-5xl p-6 md:p-8">
        <Outlet />
      </main>
    </div>
  )
}
