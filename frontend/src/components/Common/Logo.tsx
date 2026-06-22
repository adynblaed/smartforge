import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"
import logo from "/favicon.svg"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

const ALT = "SmartForge by FutureForm"

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const img = (cls: string) => (
    <img src={logo} alt={ALT} className={cn("object-contain", cls)} />
  )

  const wordmark = (
    <span className="text-lg font-semibold tracking-tight">
      Smart<span className="text-primary">Forge</span>
    </span>
  )

  let content: React.ReactNode
  if (variant === "icon") {
    content = (
      <span className="sf-logo-shine block rounded-md">
        {img(cn("size-9 rounded-md", className))}
      </span>
    )
  } else if (variant === "responsive") {
    // Navbar: fill the sidebar width when expanded; compact mark when collapsed.
    content = (
      <>
        <span className="sf-logo-shine block w-full rounded-md group-data-[collapsible=icon]:hidden">
          {img(cn("h-auto w-full max-h-16", className))}
        </span>
        <span className="sf-logo-shine hidden rounded-md group-data-[collapsible=icon]:block">
          {img("size-9 rounded-md")}
        </span>
      </>
    )
  } else {
    content = (
      <span className="flex items-center gap-2">
        <span className="sf-logo-shine block rounded-md">
          {img(cn("h-12 w-auto", className))}
        </span>
        {wordmark}
      </span>
    )
  }

  if (!asLink) {
    return content
  }

  return (
    <Link
      to="/"
      className={cn(
        "flex items-center",
        variant === "responsive" && "w-full justify-center",
      )}
    >
      {content}
    </Link>
  )
}
