// User-intuitive descriptions for API failures. Pure presentation copy — no
// logging, no side effects — so every error surface tells the same story for
// the same status code.

export interface StatusDescription {
  // Short, human headline for the failure.
  title: string
  // What the user can actually do about it.
  hint: string
  // True when the failure is most likely our fault and worth reporting.
  isBug: boolean
}

export function describeStatus(status?: number): StatusDescription {
  switch (status) {
    case 400:
    case 422:
      return {
        title: "Invalid request",
        hint: "The request didn't pass validation — adjust and retry.",
        isBug: false,
      }
    case 401:
      return {
        title: "Session expired",
        hint: "Sign in again to continue.",
        isBug: false,
      }
    case 403:
      return {
        title: "No access",
        hint: "Your role doesn't permit this action.",
        isBug: false,
      }
    case 404:
      return {
        title: "Not found",
        hint: "This resource doesn't exist or was removed.",
        isBug: false,
      }
    case 409:
      return {
        title: "Conflict",
        hint: "The action clashed with the current state — refresh and retry.",
        isBug: false,
      }
    case 429:
      return {
        title: "Rate limited",
        hint: "Too many requests — wait a moment and retry.",
        isBug: false,
      }
    case 500:
      return {
        title: "Something broke",
        hint: "This looks like a bug on our side — please report it with the reference code below.",
        isBug: true,
      }
    case 503:
      return {
        title: "Service unavailable",
        hint: "A backing service is down or not provisioned yet — see the runbooks or retry shortly.",
        isBug: false,
      }
    case 504:
      return {
        title: "Query timed out",
        hint: "The query exceeded its time budget — narrow the filters and retry.",
        isBug: false,
      }
    default:
      return {
        title: "Unexpected error",
        hint: "If this keeps happening, report it with the details below.",
        isBug: true,
      }
  }
}

export interface ApiErrorInfo {
  status: number
  requestId?: string
}

// Structural match for an API failure from either client: the hand-written
// `sf` wrapper's ApiError (which carries requestId) or the generated
// client's ApiError (which does not). Both set name = "ApiError" and a
// numeric status, so this avoids importing the generated code.
export function apiErrorInfo(error: unknown): ApiErrorInfo | undefined {
  if (
    error instanceof Error &&
    error.name === "ApiError" &&
    "status" in error &&
    typeof (error as { status: unknown }).status === "number"
  ) {
    const requestId = (error as { requestId?: unknown }).requestId
    return {
      status: (error as { status: number }).status,
      requestId: typeof requestId === "string" ? requestId : undefined,
    }
  }
  return undefined
}
