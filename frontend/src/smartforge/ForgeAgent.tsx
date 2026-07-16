import { useRouterState } from "@tanstack/react-router"
import { Maximize2, Minus, Plus, Sparkles } from "lucide-react"
import type { ReactNode } from "react"
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import { cn } from "@/lib/utils"
import { sf } from "./api"
import { ChatPanel } from "./ChatPanel"
import {
  createForgeSession,
  ensureForgeSession,
  forgeSessionKey,
} from "./forgeChat"
import type { ForgeResponse, SimFocus } from "./types"

// A focus directive plus a monotonic token, so the simulation re-runs its
// cinematic move even when the same entity is asked about twice.
export interface ForgeFocus extends SimFocus {
  token: number
}

// Site-wide ForgeAI agent. The panel + its conversation live at the layout
// level (mounted once, persists across tab navigation). Pages read `open` and
// `highlightIds` to react to it — e.g. the Factory Simulation highlights the
// machines ForgeAI locates.
interface ForgeAgentValue {
  open: boolean
  highlightIds: string[]
  focus: ForgeFocus | null
  setOpen: (v: boolean) => void
  toggle: () => void
  setHighlightIds: (ids: string[]) => void
  setFocus: (f: SimFocus | null) => void
}

const ForgeAgentContext = createContext<ForgeAgentValue | null>(null)

export function useForgeAgent(): ForgeAgentValue {
  const ctx = useContext(ForgeAgentContext)
  if (!ctx) {
    throw new Error("useForgeAgent must be used within a ForgeAgentProvider")
  }
  return ctx
}

export function ForgeAgentProvider({ children }: { children: ReactNode }) {
  const [open, setOpenState] = useState(false)
  // Keep the panel (and its ChatPanel conversation) mounted once first opened.
  const [mounted, setMounted] = useState(false)
  const [highlightIds, setHighlightIds] = useState<string[]>([])
  const [focus, setFocusState] = useState<ForgeFocus | null>(null)
  const focusToken = useRef(0)
  const setFocus = useCallback((f: SimFocus | null) => {
    if (!f || f.mode === "none") {
      setFocusState(null)
      return
    }
    focusToken.current += 1
    setFocusState({ ...f, token: focusToken.current })
  }, [])
  // The dedicated ForgeAI page IS the full experience — hide the floating agent
  // there to avoid a redundant pop-up.
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const onForgePage = pathname === "/ask-ai"

  const setOpen = useCallback((v: boolean) => {
    if (v) setMounted(true)
    setOpenState(v)
  }, [])
  const toggle = useCallback(() => {
    setMounted(true)
    setOpenState((o) => !o)
  }, [])

  const value = useMemo(
    () => ({
      open,
      highlightIds,
      focus,
      setOpen,
      toggle,
      setHighlightIds,
      setFocus,
    }),
    [open, highlightIds, focus, setOpen, toggle, setFocus],
  )

  return (
    <ForgeAgentContext.Provider value={value}>
      {children}

      {/* Show/hide affordance — on every page except the dedicated ForgeAI page. */}
      {!open && !onForgePage && (
        <button
          type="button"
          onClick={toggle}
          aria-label="Open ForgeAI"
          data-testid="forge-toggle"
          className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full border border-primary/40 bg-background/95 px-4 py-2.5 text-sm font-semibold text-primary shadow-2xl backdrop-blur transition-colors hover:bg-accent"
        >
          <Sparkles size={16} /> ForgeAI
        </button>
      )}

      {mounted && !onForgePage && (
        <ForgeAgentPanel
          hidden={!open}
          onMinimize={() => {
            setOpenState(false)
            setHighlightIds([])
          }}
          onHighlight={setHighlightIds}
          onFocus={setFocus}
        />
      )}
    </ForgeAgentContext.Provider>
  )
}

// Width presets the "widen" button steps through; free-drag clamps between the
// viewport-normalized min/max so the panel stays usable on desktop and mobile.
const WIDTH_KEY = "forgeai-panel-width"
const WIDTH_STEPS = [380, 480, 600, 720]

function loadPanelWidth(): number {
  try {
    const n = Number(localStorage.getItem(WIDTH_KEY))
    if (Number.isFinite(n) && n >= 300) return n
  } catch {
    /* ignore */
  }
  return 380
}

function ForgeAgentPanel({
  hidden,
  onMinimize,
  onHighlight,
  onFocus,
}: {
  hidden: boolean
  onMinimize: () => void
  onHighlight: (ids: string[]) => void
  onFocus: (f: SimFocus | null) => void
}) {
  // Shares the ForgeAI page's session store: opens on the last-selected chat,
  // and "New chat" here shows up in the page's history too.
  const [active, setActive] = useState(() => ensureForgeSession().active)
  useEffect(() => {
    if (!hidden) setActive(ensureForgeSession().active)
  }, [hidden])
  const newChat = () => setActive(createForgeSession())

  // User-resizable width (persisted), clamped to the viewport.
  const [width, setWidth] = useState(loadPanelWidth)
  const [vw, setVw] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth : 1280,
  )
  useEffect(() => {
    const onResize = () => setVw(window.innerWidth)
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])
  useEffect(() => {
    try {
      localStorage.setItem(WIDTH_KEY, String(width))
    } catch {
      /* ignore */
    }
  }, [width])

  const maxW = Math.min(760, vw - 24)
  const minW = Math.min(340, maxW)
  const w = Math.max(minW, Math.min(width, maxW))

  const dragRef = useRef<{ x: number; w: number } | null>(null)
  const startDrag = (e: React.PointerEvent) => {
    dragRef.current = { x: e.clientX, w }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onDrag = (e: React.PointerEvent) => {
    if (!dragRef.current) return
    // Anchored bottom-right → dragging the left edge leftward widens it.
    const next = dragRef.current.w + (dragRef.current.x - e.clientX)
    setWidth(Math.max(minW, Math.min(next, maxW)))
  }
  const endDrag = (e: React.PointerEvent) => {
    dragRef.current = null
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
  }
  const widen = () => {
    const next = WIDTH_STEPS.find((p) => p > w + 4) ?? WIDTH_STEPS[0]
    setWidth(Math.min(next, maxW))
  }

  return (
    <div
      data-testid="forge-panel"
      style={{ width: w }}
      className={cn(
        "fixed bottom-4 right-4 top-20 z-40 flex max-w-[calc(100vw-1.5rem)] flex-col overflow-hidden rounded-xl border border-border bg-background/95 shadow-2xl backdrop-blur-md",
        hidden && "hidden",
      )}
    >
      {/* left-edge drag handle — resize the panel width */}
      {/* biome-ignore lint/a11y/useSemanticElements: window-splitter — an <hr> cannot host pointer handlers or children */}
      <div
        onPointerDown={startDrag}
        onPointerMove={onDrag}
        onPointerUp={endDrag}
        role="separator"
        tabIndex={0}
        aria-orientation="vertical"
        aria-valuenow={Math.round(w)}
        aria-valuemin={Math.round(minW)}
        aria-valuemax={Math.round(maxW)}
        aria-label="Resize ForgeAI panel width"
        title="Drag to resize"
        className="group absolute bottom-0 left-0 top-0 z-20 flex w-2 cursor-ew-resize touch-none items-center justify-center hover:bg-primary/10"
      >
        <span className="h-10 w-0.5 rounded-full bg-border transition-colors group-hover:bg-primary/60" />
      </div>

      <div className="flex items-center justify-between border-b py-3 pl-5 pr-4">
        <div className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-full bg-primary/15 text-primary">
            <Sparkles size={15} />
          </span>
          <div>
            <h2 className="text-sm font-semibold leading-tight">ForgeAI</h2>
            <p className="text-[11px] text-muted-foreground">
              Live operations assistant
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={widen}
            aria-label="Widen ForgeAI panel"
            title="Resize — widen the panel"
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Maximize2 size={15} />
          </button>
          <button
            type="button"
            onClick={newChat}
            aria-label="New chat"
            title="New chat"
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Plus size={16} />
          </button>
          <button
            type="button"
            onClick={onMinimize}
            aria-label="Minimize ForgeAI"
            title="Minimize (keeps your conversation)"
            className="rounded-md p-1 text-muted-foreground hover:bg-accent"
          >
            <Minus size={16} />
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 p-2">
        <ChatPanel
          key={active}
          placeholder="Ask about the factory…"
          suggestions={[
            "Which machine is most at risk?",
            "Show me the press",
            "Are there any active faults?",
            "Give me a fleet overview",
          ]}
          ask={async (q) => {
            const res = await sf.post<ForgeResponse>("/ask-ai/forge", {
              question: q,
            })
            onHighlight(res.highlight ?? [])
            onFocus(res.focus ?? null)
            return res
          }}
          // Shared session store — same chats as the dedicated ForgeAI page.
          persistKey={forgeSessionKey(active)}
        />
      </div>
    </div>
  )
}
