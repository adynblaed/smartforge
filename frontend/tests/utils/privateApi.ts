// Note: the `PrivateService` is only available when generating the client
// for local environments
import { OpenAPI, PrivateService } from "../../src/client"

// Same base-URL rule as the app: explicit VITE_API_URL, else the local
// backend (an unset env var must never produce a literal "undefined" URL).
OpenAPI.BASE = process.env.VITE_API_URL ?? "http://localhost:8000"

export const createUser = async ({
  email,
  password,
}: {
  email: string
  password: string
}) => {
  return await PrivateService.createUser({
    requestBody: {
      email,
      password,
      is_verified: true,
      full_name: "Test User",
    },
  })
}
