import { useQuery } from "@tanstack/react-query"

import { sf } from "@/smartforge/api"

/** GET /features — the caller's tier + every site-wide gate resolved. */
export interface FeaturesResponse {
  tier: string
  role: string
  features: Record<string, boolean>
}

/**
 * Site-wide feature gates for the signed-in user. Server-authoritative
 * (app/core/features.py); elevated gates are additionally enforced on
 * their backend routes — this hook only drives what the UI offers.
 */
export function useFeatures() {
  const query = useQuery({
    queryKey: ["features", "me"],
    queryFn: () => sf.get<FeaturesResponse>("/features"),
    staleTime: 60_000,
    retry: false,
  })
  return {
    ...query,
    tier: query.data?.tier,
    /** Gated items default CLOSED until the server says otherwise. */
    enabled: (key: string) => query.data?.features?.[key] === true,
  }
}
