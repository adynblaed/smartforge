import { Link } from "@tanstack/react-router"
import type { FallbackProps } from "react-error-boundary"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardTitle,
} from "@/components/ui/card"
import { apiErrorInfo, describeStatus } from "@/smartforge/errors"

const MAX_MESSAGE_LENGTH = 200

// One safe line for display: the error message only (never a stack),
// truncated so a huge payload can't blow up the layout.
export function safeErrorMessage(error: unknown): string {
  const raw =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : ""
  const message = raw.trim()
  if (!message) return "Something went wrong. Please try again."
  return message.length > MAX_MESSAGE_LENGTH
    ? `${message.slice(0, MAX_MESSAGE_LENGTH)}…`
    : message
}

interface ErrorComponentProps {
  // TanStack Router passes { error, reset } to error components; both stay
  // optional so the root route can keep rendering this with no props.
  error?: unknown
  reset?: () => void
}

// User-intuitive framing for a failure: a describeStatus entry keyed on the
// ApiError status when the error came from either API client, plus the
// correlation id (reference code) when the response carried one.
function describeError(error: unknown) {
  const info = apiErrorInfo(error)
  return { ...describeStatus(info?.status), requestId: info?.requestId }
}

const ErrorComponent = ({ error, reset }: ErrorComponentProps) => {
  const { title, hint, isBug, requestId } = describeError(error)
  return (
    <div
      className="flex min-h-screen items-center justify-center flex-col p-4"
      data-testid="error-component"
    >
      <div className="flex items-center z-10">
        <div className="flex flex-col ml-4 items-center justify-center p-4">
          <span className="text-6xl md:text-8xl font-bold leading-none mb-4">
            Error
          </span>
          <span className="text-2xl font-bold mb-2">{title}</span>
        </div>
      </div>

      <p className="text-lg text-muted-foreground mb-2 text-center z-10">
        {hint}
      </p>
      <p className="text-sm text-muted-foreground/80 mb-2 text-center z-10">
        {safeErrorMessage(error)}
      </p>
      {requestId && (
        <p className="font-mono text-xs text-muted-foreground mb-2 text-center z-10">
          Reference: {requestId}
        </p>
      )}
      {isBug && (
        <p className="text-xs text-muted-foreground mb-2 text-center z-10">
          This is likely a bug — include the reference when reporting.
        </p>
      )}
      <div className="mt-2 flex items-center gap-2 z-10">
        {reset && (
          <Button variant="outline" onClick={reset}>
            Try again
          </Button>
        )}
        <Link to="/">
          <Button>Go Home</Button>
        </Link>
      </div>
    </div>
  )
}

// Compact in-shell fallback for react-error-boundary: keeps the sidebar /
// portal chrome and offers a reset without taking over the whole viewport.
export function ErrorFallbackCard({
  error,
  resetErrorBoundary,
}: FallbackProps) {
  const { title, hint, isBug, requestId } = describeError(error)
  return (
    <Card className="mx-auto my-8 max-w-lg" data-testid="error-fallback-card">
      <CardContent className="flex flex-col gap-2">
        <CardTitle>{title}</CardTitle>
        <CardDescription>{hint}</CardDescription>
        <p className="text-xs text-muted-foreground/80">
          {safeErrorMessage(error)}
        </p>
        {requestId && (
          <p className="font-mono text-xs text-muted-foreground">
            Reference: {requestId}
          </p>
        )}
        {isBug && (
          <p className="text-xs text-muted-foreground">
            This is likely a bug — include the reference when reporting.
          </p>
        )}
      </CardContent>
      <CardFooter className="gap-2">
        <Button variant="outline" onClick={resetErrorBoundary}>
          Try again
        </Button>
        <Link to="/">
          <Button variant="ghost">Go Home</Button>
        </Link>
      </CardFooter>
    </Card>
  )
}

export default ErrorComponent
