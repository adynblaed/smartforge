import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { ApiError as ClientApiError, OpenAPI } from "./client"
import ErrorComponent from "./components/Common/ErrorComponent"
import NotFound from "./components/Common/NotFound"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import "./index.css"
import { routeTree } from "./routeTree.gen"
import { ApiError } from "./smartforge/api"
import {
  installGlobalErrorLogging,
  logClientError,
} from "./smartforge/clientLog"

OpenAPI.BASE = import.meta.env.VITE_API_URL
OpenAPI.TOKEN = async () => {
  return localStorage.getItem("access_token") || ""
}

// Catch-all logging for errors that escape React entirely.
installGlobalErrorLogging()

// Both the `sf` wrapper's ApiError and the generated client's ApiError carry
// a real HTTP status; anything else is status-less (network failure, render
// throw, ...).
const statusOf = (error: Error): number | undefined => {
  if (error instanceof ApiError) return error.status
  if (error instanceof ClientApiError) return error.status
  return undefined
}

// Treat both typed ApiErrors and the legacy "Unauthorized (401/403)" message
// shape (kept for backward compatibility) as auth failures.
const isAuthError = (error: Error): boolean => {
  const status = statusOf(error)
  return (
    status === 401 ||
    status === 403 ||
    /Unauthorized \((401|403)\)/.test(error.message)
  )
}

const handleApiError = (error: Error, scope: "query" | "mutation") => {
  if (isAuthError(error)) {
    localStorage.removeItem("access_token")
    // Force a clean relogin; guard against a redirect loop on /login itself.
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login"
    }
    return
  }
  // Non-auth failures: log them (single hook for a future Sentry) but leave
  // the UI handling to the query/route that owns it.
  logClientError(scope, error)
}

const queryClient = new QueryClient({
  // Never retry auth failures — redirect immediately so no stale "zero data"
  // screen flashes while React Query burns through retries.
  defaultOptions: {
    queries: {
      retry: (count, error) => {
        if (error instanceof Error && isAuthError(error)) return false
        const status = error instanceof Error ? statusOf(error) : undefined
        // Don't hammer a failing server: retry 5xx at most once.
        if (status !== undefined && status >= 500) return count < 1
        return count < 2
      },
      // Surface server failures to the route error boundary (which offers a
      // retry); 4xx stays page-local so screens can render partial state.
      throwOnError: (error) => {
        const status = statusOf(error)
        return status !== undefined && status >= 500
      },
    },
  },
  queryCache: new QueryCache({
    onError: (error) => handleApiError(error, "query"),
  }),
  mutationCache: new MutationCache({
    onError: (error) => handleApiError(error, "mutation"),
  }),
})

const router = createRouter({
  routeTree,
  // Route-level defaults so a child route's error/404 renders INSIDE the
  // parent shell (sidebar preserved) instead of TanStack's unstyled built-ins.
  defaultErrorComponent: ({ error, reset }) => (
    <ErrorComponent error={error} reset={reset} />
  ),
  defaultNotFoundComponent: () => <NotFound />,
})
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <Toaster richColors closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
