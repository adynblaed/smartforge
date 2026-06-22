import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { ApiError, OpenAPI } from "./client"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import "./index.css"
import { routeTree } from "./routeTree.gen"

OpenAPI.BASE = import.meta.env.VITE_API_URL
OpenAPI.TOKEN = async () => {
  return localStorage.getItem("access_token") || ""
}

// Treat both the generated client's ApiError and the `sf` wrapper's
// "Unauthorized (401/403)" Error as auth failures.
const isAuthError = (error: Error): boolean => {
  const status = error instanceof ApiError ? error.status : undefined
  return status === 401 || status === 403 || /Unauthorized \((401|403)\)/.test(error.message)
}

const handleApiError = (error: Error) => {
  if (isAuthError(error)) {
    localStorage.removeItem("access_token")
    // Force a clean relogin; guard against a redirect loop on /login itself.
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login"
    }
  }
}

const queryClient = new QueryClient({
  // Never retry auth failures — redirect immediately so no stale "zero data"
  // screen flashes while React Query burns through retries.
  defaultOptions: {
    queries: {
      retry: (count, error) => {
        if (error instanceof Error && isAuthError(error)) return false
        return count < 2
      },
    },
  },
  queryCache: new QueryCache({
    onError: handleApiError,
  }),
  mutationCache: new MutationCache({
    onError: handleApiError,
  }),
})

const router = createRouter({ routeTree })
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
