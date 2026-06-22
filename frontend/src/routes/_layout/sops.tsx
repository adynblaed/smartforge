import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import {
  Bold,
  Code,
  Cpu,
  Heading2,
  Italic,
  List,
  ListOrdered,
  Pencil,
  Save,
  ScrollText,
  X,
} from "lucide-react"
import { type ReactNode, useEffect, useRef, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { Loading, PageHeader } from "@/smartforge/components"
import { Markdown } from "@/smartforge/markdown"
import type { Page, Sop, SopDetail } from "@/smartforge/types"

export const Route = createFileRoute("/_layout/sops")({
  validateSearch: (
    search: Record<string, unknown>,
  ): { sop?: string; section?: string; machine?: string } => ({
    sop: typeof search.sop === "string" ? search.sop : undefined,
    section: typeof search.section === "string" ? search.section : undefined,
    machine: typeof search.machine === "string" ? search.machine : undefined,
  }),
  component: SopsPage,
  head: () => ({ meta: [{ title: "SOPs - Smart Forge" }] }),
})

const CATEGORY_STYLE: Record<string, string> = {
  operation: "bg-sky-500/10 text-sky-400 border-sky-500/30",
  maintenance: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  troubleshooting: "bg-rose-500/10 text-rose-400 border-rose-500/30",
  process: "bg-violet-500/10 text-violet-400 border-violet-500/30",
  safety: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
}

interface Draft {
  title: string
  summary: string
  sections: Record<string, { title: string; body: string }>
}

function SopsPage() {
  const { sop: sopParam, section, machine } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const qc = useQueryClient()

  const { data: list } = useQuery({
    queryKey: ["sops", machine ?? null],
    queryFn: () =>
      sf.get<Page<Sop>>(`/sops/${machine ? `?machine=${machine}` : ""}`),
  })

  const activeCode = sopParam ?? list?.data[0]?.code
  const { data: detail, isLoading } = useQuery({
    queryKey: ["sop", activeCode],
    queryFn: () => sf.get<SopDetail>(`/sops/${activeCode}`),
    enabled: !!activeCode,
  })

  // ---- inline WYSIWYG editing ----
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const taRefs = useRef<Record<string, HTMLTextAreaElement | null>>({})
  const focused = useRef<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      sf.patch<SopDetail>(`/sops/${activeCode}`, {
        title: draft?.title,
        summary: draft?.summary,
        sections: Object.entries(draft?.sections ?? {}).map(([anchor, v]) => ({
          anchor,
          title: v.title,
          body: v.body,
        })),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sop", activeCode] })
      qc.invalidateQueries({ queryKey: ["sops"] })
      setEditing(false)
      setDraft(null)
    },
  })

  const startEdit = () => {
    if (!detail) return
    const sections: Draft["sections"] = {}
    for (const s of detail.sections) sections[s.anchor] = { title: s.title, body: s.body }
    setDraft({ title: detail.title, summary: detail.summary, sections })
    setEditing(true)
  }
  const cancelEdit = () => {
    setEditing(false)
    setDraft(null)
  }

  const setBody = (anchor: string, body: string) =>
    setDraft((d) =>
      d ? { ...d, sections: { ...d.sections, [anchor]: { ...d.sections[anchor], body } } } : d,
    )
  const setTitle = (anchor: string, title: string) =>
    setDraft((d) =>
      d ? { ...d, sections: { ...d.sections, [anchor]: { ...d.sections[anchor], title } } } : d,
    )

  // Markdown toolbar — operates on the currently-focused section textarea.
  const surround = (before: string, after = before) => {
    const a = focused.current
    const ta = a ? taRefs.current[a] : null
    if (!a || !ta) return
    const { selectionStart: s, selectionEnd: e, value } = ta
    const sel = value.slice(s, e) || "text"
    setBody(a, value.slice(0, s) + before + sel + after + value.slice(e))
    requestAnimationFrame(() => {
      ta.focus()
      ta.setSelectionRange(s + before.length, s + before.length + sel.length)
    })
  }
  const prefixLine = (prefix: string) => {
    const a = focused.current
    const ta = a ? taRefs.current[a] : null
    if (!a || !ta) return
    const { selectionStart: s, value } = ta
    const ls = value.lastIndexOf("\n", s - 1) + 1
    setBody(a, value.slice(0, ls) + prefix + value.slice(ls))
    requestAnimationFrame(() => ta.focus())
  }

  // Deep-link scroll.
  useEffect(() => {
    if (!detail || !section || editing) return
    const el = document.getElementById(`sop-sec-${section}`)
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
  }, [detail, section, editing])

  const goSection = (anchor: string) => {
    navigate({ search: { sop: activeCode, section: anchor, machine } })
    const el = document.getElementById(`sop-sec-${anchor}`)
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon={<ScrollText size={22} />}
        title="Standard Operating Procedures"
        description="Strict, chaptered operating guidelines for factory entities — operation, maintenance, troubleshooting and process. Distinct from Forge Facts."
      />

      {machine && (
        <div className="flex items-center gap-2 rounded-lg bg-muted/30 px-3 py-2 text-sm">
          <Cpu size={15} className="text-muted-foreground" />
          <span>
            Showing SOPs for <span className="font-medium">{machine}</span>
          </span>
          <button
            type="button"
            onClick={() => navigate({ search: { sop: undefined, section: undefined, machine: undefined } })}
            className="ml-auto text-xs font-medium text-primary hover:underline"
          >
            Show all SOPs
          </button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        {/* SOP library */}
        <aside className="space-y-2">
          {list?.data.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                cancelEdit()
                navigate({ search: { sop: s.code, section: undefined, machine } })
              }}
              className={cn(
                "w-full rounded-lg p-3 text-left transition-colors hover:bg-accent",
                s.code === activeCode ? "bg-accent" : "",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-muted-foreground">{s.code}</span>
                <Badge
                  variant="outline"
                  className={cn("text-[10px] capitalize", CATEGORY_STYLE[s.category])}
                >
                  {s.category}
                </Badge>
              </div>
              <p className="mt-1 text-sm font-medium leading-tight">{s.title}</p>
            </button>
          ))}
          {!list && <Loading />}
        </aside>

        {/* SOP detail */}
        <section className="min-w-0">
          {isLoading || !detail ? (
            <Loading />
          ) : (
            <div className="grid gap-6 md:grid-cols-[180px_minmax(0,1fr)]">
              {/* chapter nav */}
              <nav className="md:sticky md:top-20 md:self-start">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Chapters
                </p>
                <ol className="space-y-0.5">
                  {detail.sections.map((sec, i) => (
                    <li key={sec.id}>
                      <button
                        type="button"
                        onClick={() => goSection(sec.anchor)}
                        className={cn(
                          "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-[13px] leading-snug transition-colors hover:bg-accent",
                          sec.anchor === section
                            ? "bg-success/10 font-medium text-success"
                            : "text-muted-foreground",
                        )}
                      >
                        <span className="tabular-nums opacity-60">{i + 1}.</span>
                        <span>{sec.title}</span>
                      </button>
                    </li>
                  ))}
                </ol>
              </nav>

              {/* content */}
              <article className="min-w-0 max-w-3xl space-y-5">
                <header className="border-b pb-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-muted-foreground">
                      {detail.code}
                    </span>
                    <Badge
                      variant="outline"
                      className={cn("capitalize", CATEGORY_STYLE[detail.category])}
                    >
                      {detail.category}
                    </Badge>
                    <Badge variant="outline" className="text-[10px]">
                      Rev {detail.revision}
                    </Badge>
                    {detail.machine_code && (
                      <span className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Cpu size={12} /> {detail.machine_code}
                      </span>
                    )}
                    <div className="ml-auto flex items-center gap-2">
                      {editing ? (
                        <>
                          <Button size="sm" variant="outline" onClick={cancelEdit}>
                            <X size={14} /> Cancel
                          </Button>
                          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
                            <Save size={14} /> {save.isPending ? "Saving…" : "Save"}
                          </Button>
                        </>
                      ) : (
                        <Button size="sm" variant="outline" onClick={startEdit}>
                          <Pencil size={14} /> Edit
                        </Button>
                      )}
                    </div>
                  </div>

                  {editing && draft ? (
                    <div className="mt-3 space-y-2">
                      <Input
                        value={draft.title}
                        onChange={(e) => setDraft((d) => (d ? { ...d, title: e.target.value } : d))}
                        className="text-base font-semibold"
                      />
                      <textarea
                        value={draft.summary}
                        onChange={(e) => setDraft((d) => (d ? { ...d, summary: e.target.value } : d))}
                        rows={2}
                        placeholder="Summary"
                        className="w-full resize-y rounded-md bg-muted/50 p-2 text-sm outline-none focus:ring-1 focus:ring-primary"
                      />
                      {/* WYSIWYG toolbar (acts on the focused chapter) */}
                      <div className="flex flex-wrap items-center gap-1 rounded-md bg-muted/40 p-1">
                        <ToolBtn label="Heading" onClick={() => prefixLine("## ")}>
                          <Heading2 size={15} />
                        </ToolBtn>
                        <ToolBtn label="Bold" onClick={() => surround("**")}>
                          <Bold size={15} />
                        </ToolBtn>
                        <ToolBtn label="Italic" onClick={() => surround("*")}>
                          <Italic size={15} />
                        </ToolBtn>
                        <ToolBtn label="Code" onClick={() => surround("`")}>
                          <Code size={15} />
                        </ToolBtn>
                        <ToolBtn label="Bulleted list" onClick={() => prefixLine("- ")}>
                          <List size={15} />
                        </ToolBtn>
                        <ToolBtn label="Numbered list" onClick={() => prefixLine("1. ")}>
                          <ListOrdered size={15} />
                        </ToolBtn>
                      </div>
                    </div>
                  ) : (
                    <>
                      <h2 className="mt-2 text-2xl font-semibold tracking-tight">{detail.title}</h2>
                      <p className="mt-1.5 max-w-2xl text-[0.95rem] leading-relaxed text-muted-foreground">
                        {detail.summary}
                      </p>
                    </>
                  )}
                </header>

                {detail.sections.map((sec, i) =>
                  editing && draft ? (
                    <div key={sec.id} className="rounded-lg bg-card/60 p-4">
                      <Input
                        value={draft.sections[sec.anchor]?.title ?? sec.title}
                        onChange={(e) => setTitle(sec.anchor, e.target.value)}
                        className="mb-2 font-semibold"
                      />
                      <textarea
                        ref={(el) => {
                          taRefs.current[sec.anchor] = el
                        }}
                        value={draft.sections[sec.anchor]?.body ?? sec.body}
                        onFocus={() => {
                          focused.current = sec.anchor
                        }}
                        onChange={(e) => setBody(sec.anchor, e.target.value)}
                        rows={6}
                        className="w-full resize-y rounded-md bg-muted/50 p-3 font-mono text-sm outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>
                  ) : (
                    // biome-ignore lint/a11y/useKeyWithClickEvents: chapter card selects on click
                    <div
                      key={sec.id}
                      id={`sop-sec-${sec.anchor}`}
                      onClick={() => goSection(sec.anchor)}
                      className={cn(
                        "scroll-mt-24 cursor-pointer rounded-lg p-5 transition-colors",
                        sec.anchor === section
                          ? "bg-success/5 ring-2 ring-success/50"
                          : "hover:bg-accent/40",
                      )}
                    >
                      <h3 className="mb-2.5 flex items-center gap-2 text-lg font-semibold tracking-tight">
                        <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs tabular-nums text-muted-foreground">
                          {i + 1}
                        </span>
                        {sec.title}
                      </h3>
                      <Markdown content={sec.body} className="text-[0.95rem] leading-relaxed" />
                    </div>
                  ),
                )}
              </article>
            </div>
          )}
        </section>
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
  children: ReactNode
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
