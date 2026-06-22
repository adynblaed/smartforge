import { Link, useRouterState } from "@tanstack/react-router"
import { Fragment } from "react"

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { breadcrumbsFor } from "@/components/Sidebar/nav"

/**
 * Route-driven breadcrumb trail for the app shell header. Derived from the same
 * NAV_GROUPS the sidebar uses, so the trail always mirrors the sidebar grouping.
 */
export function RouteBreadcrumbs() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const crumbs = breadcrumbsFor(pathname)

  return (
    <Breadcrumb data-testid="breadcrumbs">
      <BreadcrumbList>
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1
          return (
            <Fragment key={`${c.title}-${i}`}>
              <BreadcrumbItem>
                {last || !c.path ? (
                  <BreadcrumbPage>{c.title}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink asChild>
                    <Link to={c.path}>{c.title}</Link>
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
              {!last && <BreadcrumbSeparator />}
            </Fragment>
          )
        })}
      </BreadcrumbList>
    </Breadcrumb>
  )
}
