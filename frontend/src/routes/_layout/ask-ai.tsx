import { createFileRoute } from "@tanstack/react-router"
import { MessageSquare, Plus, Sparkles, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"

import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { ChatPanel } from "@/smartforge/ChatPanel"
import { PageHeader } from "@/smartforge/components"
import {
  createForgeSession,
  ensureForgeSession,
  forgeSessionKey,
  forgeSessionTitle,
  saveForgeIndex,
  setForgeActive,
} from "@/smartforge/forgeChat"
import { type CubeState, ForgeChatCube } from "@/smartforge/ForgeChatCube"
import type { ForgeResponse } from "@/smartforge/types"

export const Route = createFileRoute("/_layout/ask-ai")({
  component: ForgeAiPage,
  head: () => ({ meta: [{ title: "ForgeAI - Smart Forge" }] }),
})

function ForgeAiPage() {
  // Shared session store — the same chats the agent bubble uses.
  const [{ ids, active }, setSessions] = useState(() => ensureForgeSession())
  const [cube, setCube] = useState<CubeState>("idle")
  // Bumped on chat activity so history titles re-read from localStorage.
  const [, setTick] = useState(0)

  useEffect(() => {
    saveForgeIndex(ids)
  }, [ids])

  const select = (id: string) => {
    setForgeActive(id)
    setSessions((s) => ({ ...s, active: id }))
  }

  const onActivity = (s: CubeState) => {
    setCube(s)
    setTick((t) => t + 1)
    if (s === "answer") window.setTimeout(() => setCube("idle"), 1600)
  }

  const newChat = () => {
    const id = createForgeSession()
    setSessions((s) => ({ ids: [id, ...s.ids], active: id }))
  }

  const deleteChat = (id: string) => {
    try {
      localStorage.removeItem(forgeSessionKey(id))
    } catch {
      /* non-fatal */
    }
    setSessions((s) => {
      const next = s.ids.filter((x) => x !== id)
      if (next.length === 0) {
        const nid = createForgeSession()
        return { ids: [nid], active: nid }
      }
      const nextActive = s.active === id ? next[0] : s.active
      if (nextActive !== s.active) setForgeActive(nextActive)
      return { ids: next, active: nextActive }
    })
  }

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col gap-4">
      <PageHeader
        icon={<Sparkles size={20} className="text-primary" />}
        title="ForgeAI"
        description="Live operations assistant — grounded in machines, the order tracker, SOPs and your Forge Facts."
      />

      <div className="flex min-h-0 flex-1 gap-4">
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <div className="h-28 shrink-0 overflow-hidden rounded-lg bg-gradient-to-b from-muted/40 to-background">
            <ForgeChatCube state={cube} />
          </div>
          <div className="min-h-0 flex-1">
            <ChatPanel
              key={active}
              placeholder="Ask about the factory…"
              suggestions={[
                "Which machine is most at risk?",
                "Show me the press",
                "Are there any active faults?",
                "Give me a fleet overview",
              ]}
              ask={(q) => sf.post<ForgeResponse>("/ask-ai/forge", { question: q })}
              persistKey={forgeSessionKey(active)}
              onActivity={onActivity}
            />
          </div>
        </div>

        {/* shared chat history (right rail, like Claude/ChatGPT) */}
        <aside className="hidden w-72 shrink-0 flex-col overflow-hidden rounded-lg bg-card lg:flex">
          <div className="flex items-center justify-between px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <span>Chat history</span>
            <button
              type="button"
              onClick={newChat}
              title="New chat"
              aria-label="New chat"
              className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <Plus size={15} />
            </button>
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-2">
            {ids.map((id) => (
              <div
                key={id}
                className={cn(
                  "group flex items-center gap-1 rounded-md px-2 py-2 text-sm transition-colors",
                  id === active ? "bg-accent" : "hover:bg-accent/50",
                )}
              >
                <button
                  type="button"
                  onClick={() => select(id)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                >
                  <MessageSquare size={14} className="shrink-0 text-muted-foreground" />
                  <span className="truncate">{forgeSessionTitle(id)}</span>
                </button>
                <button
                  type="button"
                  onClick={() => deleteChat(id)}
                  title="Delete chat"
                  aria-label="Delete chat"
                  className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  )
}
