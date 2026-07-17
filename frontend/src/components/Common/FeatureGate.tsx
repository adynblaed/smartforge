import { ShieldOff } from "lucide-react"

import { useFeatures } from "@/hooks/useFeatures"

/**
 * Defense-in-depth page gate. Three layers keep a gated feature closed:
 * the nav hides its entry, the backend 403s its elevated routes, and this
 * wrapper stops a direct-URL visit from rendering the page shell at all.
 * It is UX, never the security boundary — that lives server-side
 * (app/core/features.py require_feature).
 */
export function FeatureGate({
  feature,
  children,
}: {
  feature: string
  children: React.ReactNode
}) {
  const { isPending, enabled } = useFeatures()
  if (isPending) return null
  if (!enabled(feature))
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-16 text-center">
        <ShieldOff size={20} className="text-muted-foreground" />
        <p className="text-sm font-medium">
          This area requires a higher access tier
        </p>
        <p className="max-w-md text-xs text-muted-foreground">
          The "{feature}" feature is not enabled for your account. Contact an
          administrator if you believe you need access.
        </p>
      </div>
    )
  return <>{children}</>
}
