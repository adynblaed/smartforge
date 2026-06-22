// source: https://usehooks-ts.com/react-hook/use-copy-to-clipboard
import { useCallback, useEffect, useRef, useState } from "react"

type CopiedValue = string | null

type CopyFn = (text: string) => Promise<boolean>

export function useCopyToClipboard(): [CopiedValue, CopyFn] {
  const [copiedText, setCopiedText] = useState<CopiedValue>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Clear any pending reset timer on unmount to avoid setState-after-unmount.
  useEffect(() => () => clearTimeout(timer.current), [])

  const copy: CopyFn = useCallback(async (text) => {
    if (!navigator?.clipboard) {
      console.warn("Clipboard not supported")
      return false
    }

    try {
      await navigator.clipboard.writeText(text)
      setCopiedText(text)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopiedText(null), 2000)
      return true
    } catch (error) {
      console.warn("Copy failed", error)
      setCopiedText(null)
      return false
    }
  }, [])

  return [copiedText, copy]
}
