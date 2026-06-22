import { cn } from "@/lib/utils"

// Lightweight, dependency-free Markdown renderer covering the subset the AI
// assistants emit: headings, bold/italic/inline-code, code fences, ordered &
// unordered lists, links, and GitHub-flavored tables. Input is HTML-escaped
// before any transform, so rendering it is safe.

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
}

function inline(s: string): string {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
    .replace(/\b_([^_]+)_\b/g, "<em>$1</em>")
    .replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
    )
}

function splitRow(line: string): string[] {
  let s = line.trim()
  if (s.startsWith("|")) s = s.slice(1)
  if (s.endsWith("|")) s = s.slice(0, -1)
  return s.split("|").map((c) => c.trim())
}

export function renderMarkdown(md: string): string {
  const lines = escapeHtml(md).replace(/\r\n/g, "\n").split("\n")
  const out: string[] = []
  let i = 0
  let inUL = false
  let inOL = false
  let inCode = false

  const closeLists = () => {
    if (inUL) {
      out.push("</ul>")
      inUL = false
    }
    if (inOL) {
      out.push("</ol>")
      inOL = false
    }
  }

  while (i < lines.length) {
    const line = lines[i]

    if (line.trim().startsWith("```")) {
      if (inCode) {
        out.push("</code></pre>")
        inCode = false
      } else {
        closeLists()
        out.push("<pre><code>")
        inCode = true
      }
      i++
      continue
    }
    if (inCode) {
      out.push(line)
      i++
      continue
    }

    // GFM table: a header row, then a separator row of dashes/pipes/colons.
    const next = lines[i + 1] ?? ""
    if (
      line.includes("|") &&
      /^[\s|:-]+$/.test(next) &&
      next.includes("-") &&
      next.includes("|")
    ) {
      closeLists()
      const header = splitRow(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(splitRow(lines[i]))
        i++
      }
      out.push(
        "<table><thead><tr>" +
          header.map((h) => `<th>${inline(h)}</th>`).join("") +
          "</tr></thead><tbody>" +
          rows
            .map(
              (r) =>
                "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>",
            )
            .join("") +
          "</tbody></table>",
      )
      continue
    }

    if (/^#{1,6}\s/.test(line)) {
      closeLists()
      const level = Math.min(line.match(/^#+/)![0].length, 6)
      out.push(`<h${level}>${inline(line.replace(/^#+\s/, ""))}</h${level}>`)
      i++
      continue
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      if (inUL) {
        out.push("</ul>")
        inUL = false
      }
      if (!inOL) {
        out.push("<ol>")
        inOL = true
      }
      out.push(`<li>${inline(line.replace(/^\s*\d+\.\s+/, ""))}</li>`)
      i++
      continue
    }

    if (/^\s*[-*]\s+/.test(line)) {
      if (inOL) {
        out.push("</ol>")
        inOL = false
      }
      if (!inUL) {
        out.push("<ul>")
        inUL = true
      }
      out.push(`<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`)
      i++
      continue
    }

    if (line.trim() === "") {
      closeLists()
      i++
      continue
    }

    closeLists()
    out.push(`<p>${inline(line)}</p>`)
    i++
  }

  closeLists()
  if (inCode) out.push("</code></pre>")
  return out.join("\n")
}

const PROSE = cn(
  "[&_a]:text-primary [&_a]:underline",
  "[&_code]:rounded [&_code]:bg-black/20 [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.85em]",
  "[&_pre]:my-2 [&_pre]:overflow-auto [&_pre]:rounded [&_pre]:bg-black/30 [&_pre]:p-2 [&_pre]:text-xs",
  "[&_h1]:mb-1.5 [&_h1]:mt-2 [&_h1]:text-base [&_h1]:font-semibold",
  "[&_h2]:mb-1 [&_h2]:mt-2 [&_h2]:text-sm [&_h2]:font-semibold",
  "[&_h3]:mb-1 [&_h3]:mt-2 [&_h3]:text-sm [&_h3]:font-semibold",
  "[&_p]:my-1 [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:my-0.5",
  "[&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:text-[11px]",
  "[&_th]:border [&_th]:border-border [&_th]:bg-muted/60 [&_th]:px-1.5 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold",
  "[&_td]:border [&_td]:border-border [&_td]:px-1.5 [&_td]:py-1",
)

export function Markdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("overflow-x-auto", PROSE, className)}>
      {/* content is HTML-escaped inside renderMarkdown before any transform */}
      <div dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }} />
    </div>
  )
}
