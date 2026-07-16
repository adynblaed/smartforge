import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  Bold,
  BookOpen,
  Code,
  Columns2,
  Eye,
  Heading1,
  Heading2,
  Italic,
  Link2,
  List,
  ListOrdered,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  SquareCode,
  Table2,
  Trash2,
} from "lucide-react"
import { useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { Loading, PageHeader } from "@/smartforge/components"
import { Markdown } from "@/smartforge/markdown"
import type { KnowledgeBase, Page } from "@/smartforge/types"

export const Route = createFileRoute("/_layout/knowledge-bases")({
  component: KnowledgeBasesPage,
  head: () => ({ meta: [{ title: "Forge Facts - Smart Forge" }] }),
})

/* -------------------------------------------------------------------- page */

interface Draft {
  id: string | null
  name: string
  description: string
  content: string
}

const EMPTY: Draft = { id: null, name: "", description: "", content: "" }

const TABLE_SNIPPET =
  "\n| Column A | Column B |\n|----------|----------|\n| value | value |\n"
const CODE_SNIPPET = "\n```\ncode\n```\n"

type ViewMode = "edit" | "split" | "preview"

function KnowledgeBasesPage() {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [view, setView] = useState<ViewMode>("split")
  const taRef = useRef<HTMLTextAreaElement>(null)

  const { data, isLoading } = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: () => sf.get<Page<KnowledgeBase>>("/ask-ai/knowledge-bases"),
  })
  const kbs = data?.data ?? []

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["knowledge-bases"] })
  }

  const save = useMutation({
    mutationFn: async (d: Draft) => {
      const body = {
        name: d.name,
        description: d.description,
        content: d.content,
      }
      return d.id
        ? sf.patch<KnowledgeBase>(`/ask-ai/knowledge-bases/${d.id}`, body)
        : sf.post<KnowledgeBase>("/ask-ai/knowledge-bases", body)
    },
    onSuccess: (kb) => {
      invalidate()
      setDraft({
        id: kb.id,
        name: kb.name,
        description: kb.description ?? "",
        content: kb.content,
      })
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => sf.del(`/ask-ai/knowledge-bases/${id}`),
    onSuccess: () => {
      invalidate()
      setDraft(EMPTY)
    },
  })

  // Rebuild the full RAG vector index (SOPs + Forge Facts) for semantic search.
  const resync = useMutation({
    mutationFn: () =>
      sf.post<{ message: string }>("/ask-ai/knowledge-bases/sync"),
  })

  // Markdown toolbar — wraps/prefixes the current textarea selection.
  const surround = (before: string, after = before) => {
    const ta = taRef.current
    if (!ta) return
    const { selectionStart: s, selectionEnd: e, value } = ta
    const sel = value.slice(s, e) || "text"
    const next = value.slice(0, s) + before + sel + after + value.slice(e)
    setDraft((d) => ({ ...d, content: next }))
    requestAnimationFrame(() => {
      ta.focus()
      ta.setSelectionRange(s + before.length, s + before.length + sel.length)
    })
  }
  const prefixLine = (prefix: string) => {
    const ta = taRef.current
    if (!ta) return
    const { selectionStart: s, value } = ta
    const lineStart = value.lastIndexOf("\n", s - 1) + 1
    const next = value.slice(0, lineStart) + prefix + value.slice(lineStart)
    setDraft((d) => ({ ...d, content: next }))
    requestAnimationFrame(() => ta.focus())
  }
  const insert = (text: string) => {
    const ta = taRef.current
    if (!ta) return
    const { selectionStart: s, value } = ta
    const next = value.slice(0, s) + text + value.slice(s)
    setDraft((d) => ({ ...d, content: next }))
    requestAnimationFrame(() => {
      ta.focus()
      ta.setSelectionRange(s + text.length, s + text.length)
    })
  }

  const canSave = draft.name.trim().length > 0 && !save.isPending
  const words = draft.content.trim()
    ? draft.content.trim().split(/\s+/).length
    : 0

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Forge Facts"
        description="Author knowledge once — secondary notes, memos and specs that augment every ForgeAI response. SOPs always rank first; Forge Facts add to (and never override) them."
        actions={
          <div className="flex flex-col items-end gap-1">
            <Button
              variant="outline"
              onClick={() => resync.mutate()}
              disabled={resync.isPending}
            >
              <RefreshCw
                size={15}
                className={cn(resync.isPending && "animate-spin")}
              />
              {resync.isPending ? "Re-indexing…" : "Re-sync RAG index"}
            </Button>
            {resync.data?.message && (
              <span className="max-w-[260px] text-right text-[11px] text-muted-foreground">
                {resync.data.message}
              </span>
            )}
          </div>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        {/* KB list */}
        <div className="flex flex-col gap-2">
          <Button
            onClick={() => setDraft(EMPTY)}
            variant="outline"
            className="justify-start"
          >
            <Plus size={16} /> New Forge Fact
          </Button>
          {isLoading && <Loading label="Loading…" />}
          {kbs.map((kb) => (
            <button
              key={kb.id}
              type="button"
              onClick={() =>
                setDraft({
                  id: kb.id,
                  name: kb.name,
                  description: kb.description ?? "",
                  content: kb.content,
                })
              }
              className={cn(
                "rounded-lg border px-3 py-2 text-left transition-colors",
                draft.id === kb.id
                  ? "border-primary bg-primary/5"
                  : "hover:bg-accent",
              )}
            >
              <div className="flex items-center gap-2 text-sm font-medium">
                <BookOpen size={14} className="text-muted-foreground" />
                <span className="truncate">{kb.name}</span>
              </div>
              {kb.description && (
                <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                  {kb.description}
                </p>
              )}
            </button>
          ))}
          {!isLoading && kbs.length === 0 && (
            <p className="px-1 text-sm text-muted-foreground">
              No Forge Facts yet.
            </p>
          )}
        </div>

        {/* editor */}
        <div className="flex flex-col gap-3 rounded-xl border bg-card p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              placeholder="Forge Fact name (e.g. Coolant spec note)"
              value={draft.name}
              onChange={(e) =>
                setDraft((d) => ({ ...d, name: e.target.value }))
              }
            />
            <Input
              placeholder="Short description (optional)"
              value={draft.description}
              onChange={(e) =>
                setDraft((d) => ({ ...d, description: e.target.value }))
              }
            />
          </div>

          {/* toolbar */}
          <div className="flex flex-wrap items-center gap-1 rounded-md border bg-muted/40 p-1">
            <ToolBtn label="Heading 1" onClick={() => prefixLine("# ")}>
              <Heading1 size={15} />
            </ToolBtn>
            <ToolBtn label="Heading 2" onClick={() => prefixLine("## ")}>
              <Heading2 size={15} />
            </ToolBtn>
            <Sep />
            <ToolBtn label="Bold" onClick={() => surround("**")}>
              <Bold size={15} />
            </ToolBtn>
            <ToolBtn label="Italic" onClick={() => surround("*")}>
              <Italic size={15} />
            </ToolBtn>
            <ToolBtn label="Inline code" onClick={() => surround("`")}>
              <Code size={15} />
            </ToolBtn>
            <Sep />
            <ToolBtn label="Bulleted list" onClick={() => prefixLine("- ")}>
              <List size={15} />
            </ToolBtn>
            <ToolBtn label="Numbered list" onClick={() => prefixLine("1. ")}>
              <ListOrdered size={15} />
            </ToolBtn>
            <ToolBtn label="Link" onClick={() => surround("[", "](https://)")}>
              <Link2 size={15} />
            </ToolBtn>
            <ToolBtn label="Table" onClick={() => insert(TABLE_SNIPPET)}>
              <Table2 size={15} />
            </ToolBtn>
            <ToolBtn label="Code block" onClick={() => insert(CODE_SNIPPET)}>
              <SquareCode size={15} />
            </ToolBtn>

            <div className="ml-auto flex items-center gap-0.5 rounded-md bg-background p-0.5">
              <ViewBtn
                active={view === "edit"}
                onClick={() => setView("edit")}
                label="Edit"
              >
                <Pencil size={13} />
              </ViewBtn>
              <ViewBtn
                active={view === "split"}
                onClick={() => setView("split")}
                label="Split"
              >
                <Columns2 size={13} />
              </ViewBtn>
              <ViewBtn
                active={view === "preview"}
                onClick={() => setView("preview")}
                label="Preview"
              >
                <Eye size={13} />
              </ViewBtn>
            </div>
          </div>

          {/* editor / preview (respects the view toggle) */}
          <div
            className={cn("grid gap-3", view === "split" && "md:grid-cols-2")}
          >
            {view !== "preview" && (
              <textarea
                ref={taRef}
                value={draft.content}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, content: e.target.value }))
                }
                placeholder="# Title&#10;&#10;Write SOPs, manuals, specs, etc… ForgeAI will remember this everywhere."
                className="min-h-[460px] w-full resize-y rounded-md border bg-muted/50 p-3 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                spellCheck
              />
            )}
            {view !== "edit" && (
              <div className="min-h-[460px] overflow-auto rounded-md border bg-background p-4 text-sm">
                {draft.content.trim() ? (
                  <Markdown content={draft.content} />
                ) : (
                  <p className="text-muted-foreground">
                    Live preview appears here.
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {save.isSuccess && !save.isPending ? "Saved · " : ""}
              {draft.id ? "Editing existing" : "New Forge Fact"} ·{" "}
              {draft.content.length.toLocaleString()} chars ·{" "}
              {words.toLocaleString()} words
            </span>
            <div className="flex gap-2">
              {draft.id && (
                <Button
                  variant="outline"
                  onClick={() => remove.mutate(draft.id!)}
                  disabled={remove.isPending}
                >
                  <Trash2 size={16} /> Delete
                </Button>
              )}
              <Button onClick={() => save.mutate(draft)} disabled={!canSave}>
                <Save size={16} /> {save.isPending ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ToolBtn({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="rounded p-1.5 text-muted-foreground hover:bg-background hover:text-foreground"
    >
      {children}
    </button>
  )
}

function Sep() {
  return <span className="mx-0.5 h-5 w-px bg-border" />
}

function ViewBtn({
  active,
  onClick,
  label,
  children,
}: {
  active: boolean
  onClick: () => void
  label: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        "flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors",
        active
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-accent",
      )}
    >
      {children}
    </button>
  )
}
