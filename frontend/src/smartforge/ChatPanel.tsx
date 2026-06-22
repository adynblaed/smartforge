import { Link } from "@tanstack/react-router"
import {
  BookOpen,
  Bot,
  ChevronRight,
  FileText,
  ScrollText,
  Send,
  Trash2,
  User,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { LOW_CONFIDENCE } from "./constants"
import { Markdown } from "./markdown"
import type { AskResponse, SourceRef } from "./types"

interface Turn {
  role: "user" | "assistant"
  text: string
  sources?: SourceRef[]
  actions?: string[]
  confidence?: number
}

function loadTurns(key?: string): Turn[] {
  if (!key || typeof window === "undefined") return []
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as Turn[]) : []
  } catch {
    return []
  }
}

export function ChatPanel({
  ask,
  placeholder = "Ask a question…",
  suggestions = [],
  onEscalate,
  persistKey,
  onActivity,
}: {
  ask: (q: string) => Promise<AskResponse>
  placeholder?: string
  suggestions?: string[]
  onEscalate?: (q: string) => void
  // When set, the conversation is persisted to localStorage under this key so it
  // survives navigation (one shared thread per user).
  persistKey?: string
  // Notifies the host of agent activity so it can drive a visualizer.
  onActivity?: (state: "idle" | "thinking" | "answer") => void
}) {
  const [turns, setTurns] = useState<Turn[]>(() => loadTurns(persistKey))
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Keep the latest message in view as the conversation grows.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [turns, busy])

  // Persist the thread when a key is provided.
  useEffect(() => {
    if (!persistKey || typeof window === "undefined") return
    try {
      localStorage.setItem(persistKey, JSON.stringify(turns))
    } catch {
      /* quota / private mode — non-fatal */
    }
  }, [turns, persistKey])

  const send = async (q: string) => {
    if (!q.trim() || busy) return
    setInput("")
    setTurns((t) => [...t, { role: "user", text: q }])
    setBusy(true)
    onActivity?.("thinking")
    try {
      const res = await ask(q)
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          text: res.answer,
          sources: res.sources,
          actions: res.suggested_actions,
          confidence: res.confidence,
        },
      ])
      onActivity?.("answer")
    } catch {
      setTurns((t) => [
        ...t,
        { role: "assistant", text: "Sorry — I couldn't reach the assistant." },
      ])
      onActivity?.("idle")
    } finally {
      setBusy(false)
    }
  }

  const clear = () => {
    setTurns([])
    if (persistKey && typeof window !== "undefined") {
      try {
        localStorage.removeItem(persistKey)
      } catch {
        /* non-fatal */
      }
    }
  }

  return (
    <div className="flex h-full flex-col rounded-lg border bg-card">
      <div
        ref={scrollRef}
        aria-live="polite"
        className="flex-1 space-y-4 overflow-y-auto p-4"
      >
        {turns.length === 0 && (
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>Ask anything about machines, faults, maintenance, or orders.</p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  className="rounded-full border px-3 py-1 text-xs hover:bg-accent"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div
            key={i}
            className={cn(
              "flex items-start gap-3",
              t.role === "user" && "flex-row-reverse",
            )}
          >
            {/* self-start keeps the avatar a fixed circle instead of stretching
                to the full height of the message bubble */}
            <div className="mt-1 size-7 shrink-0 self-start rounded-full bg-muted p-1.5">
              {t.role === "user" ? <User size={14} /> : <Bot size={14} />}
            </div>
            <div
              className={cn(
                "min-w-0 rounded-lg px-3 py-2 text-sm",
                // Both bubbles are theme-adaptive surfaces; the user bubble is a
                // soft Future Form (brand) tint instead of a loud solid teal.
                t.role === "user"
                  ? "max-w-[80%] bg-primary/15 text-foreground"
                  : "max-w-[92%] bg-muted",
              )}
            >
              {t.role === "assistant" ? (
                <Markdown content={t.text} />
              ) : (
                <p className="whitespace-pre-wrap">{t.text}</p>
              )}
              {t.sources && t.sources.length > 0 && (
                <SourceList sources={t.sources} />
              )}
              {t.actions && t.actions.length > 0 && (
                <ul className="mt-2 list-disc pl-4 text-xs text-muted-foreground">
                  {t.actions.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              )}
              {onEscalate &&
                t.role === "assistant" &&
                (t.confidence ?? 1) < LOW_CONFIDENCE && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-2"
                    onClick={() => onEscalate(turns[i - 1]?.text ?? "")}
                  >
                    Talk to a human
                  </Button>
                )}
            </div>
          </div>
        ))}
        {busy && <p className="text-sm text-muted-foreground">Thinking…</p>}
      </div>
      <form
        className="flex gap-2 border-t p-3"
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
        />
        {persistKey && turns.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            onClick={clear}
            title="Clear conversation"
            aria-label="Clear conversation"
          >
            <Trash2 size={16} />
          </Button>
        )}
        <Button type="submit" disabled={busy} aria-label="Send message">
          <Send size={16} />
        </Button>
      </form>
    </div>
  )
}

// Citations rendered as individually-expandable, deep-linkable sources. SOPs are
// shown first (authoritative), then Forge Facts. Expanding a source reveals its
// retrieved excerpt (rendered as markdown, so embedded images/instructions from
// the datasource show inline) and a link straight to the source.
const KIND_LABEL: Record<string, string> = {
  sop: "SOP",
  forge_fact: "Forge Fact",
}

function kindIcon(kind: string) {
  if (kind === "sop") return <ScrollText size={12} className="text-sky-400" />
  if (kind === "forge_fact") return <BookOpen size={12} className="text-emerald-400" />
  return <FileText size={12} className="text-muted-foreground" />
}

function rank(kind: string): number {
  return kind === "sop" ? 0 : kind === "forge_fact" ? 1 : 2
}

function SourceList({ sources }: { sources: SourceRef[] }) {
  // Stable SOP-first ordering even for older persisted turns.
  const ordered = [...sources].sort((a, b) => rank(a.kind) - rank(b.kind))
  return (
    <div className="mt-2 space-y-1 border-t pt-2">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        Sources · {ordered.length}
      </div>
      {ordered.map((s, i) => (
        <SourceItem key={`${s.document_id}-${s.anchor ?? ""}-${i}`} source={s} />
      ))}
    </div>
  )
}

function SourceItem({ source: s }: { source: SourceRef }) {
  const [open, setOpen] = useState(false)
  const label = KIND_LABEL[s.kind] ?? "Reference"
  return (
    <div className="rounded-md border bg-background/60 text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left hover:bg-accent/50"
      >
        <ChevronRight
          size={12}
          className={cn("shrink-0 transition-transform", open && "rotate-90")}
        />
        {kindIcon(s.kind)}
        <span className="shrink-0 rounded bg-muted px-1 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        <span className="truncate font-medium">{s.title}</span>
      </button>
      {open && (
        <div className="border-t px-2 py-2">
          {s.snippet ? (
            <Markdown content={s.snippet} className="text-xs" />
          ) : (
            <p className="text-muted-foreground">No excerpt available.</p>
          )}
          {s.kind === "sop" && s.code && (
            <Link
              to="/sops"
              search={{ sop: s.code, section: s.anchor ?? undefined }}
              className="mt-2 inline-flex items-center gap-1 font-medium text-primary hover:underline"
            >
              View {s.code}
              {s.anchor ? ` · ${s.anchor}` : ""} →
            </Link>
          )}
          {s.kind === "forge_fact" && (
            <Link
              to="/knowledge-bases"
              className="mt-2 inline-flex items-center gap-1 font-medium text-primary hover:underline"
            >
              Open in Forge Facts →
            </Link>
          )}
        </div>
      )}
    </div>
  )
}
