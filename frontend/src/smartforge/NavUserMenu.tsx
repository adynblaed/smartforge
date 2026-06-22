import { Link, useNavigate } from "@tanstack/react-router"
import { LogIn, LogOut, Settings } from "lucide-react"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import useAuth from "@/hooks/useAuth"
import logo from "/favicon.svg"

// Top-right account control (mirrors the sidebar user menu): the SmartForge mark
// opens a menu to log in (relogin) or sign out back to the login screen.
export function NavUserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Account"
          data-testid="nav-user-menu"
          className="flex size-9 items-center justify-center overflow-hidden rounded-full border bg-card transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <img src={logo} alt="Account" className="size-6 object-contain" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-52">
        {user ? (
          <>
            <DropdownMenuLabel className="truncate font-normal">
              <div className="text-sm font-medium">{user.full_name ?? "Signed in"}</div>
              <div className="truncate text-xs text-muted-foreground">{user.email}</div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to="/settings">
                <Settings className="mr-2 size-4" /> User Settings
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => logout()}>
              <LogOut className="mr-2 size-4" /> Sign out
            </DropdownMenuItem>
          </>
        ) : (
          <DropdownMenuItem onClick={() => navigate({ to: "/login" })}>
            <LogIn className="mr-2 size-4" /> Log in
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
