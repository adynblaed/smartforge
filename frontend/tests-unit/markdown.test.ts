import { describe, expect, it } from "vitest"

import { renderMarkdown } from "@/smartforge/markdown"

describe("renderMarkdown", () => {
  it("renders headings", () => {
    expect(renderMarkdown("# Title")).toContain("<h1>Title</h1>")
    expect(renderMarkdown("### Sub")).toContain("<h3>Sub</h3>")
  })

  it("renders bold, italic and inline code", () => {
    const html = renderMarkdown("**b** and *i* and `c`")
    expect(html).toContain("<strong>b</strong>")
    expect(html).toContain("<em>i</em>")
    expect(html).toContain("<code>c</code>")
  })

  it("renders unordered and ordered lists", () => {
    const ul = renderMarkdown("- one\n- two")
    expect(ul).toContain("<ul>")
    expect(ul).toContain("<li>one</li>")
    const ol = renderMarkdown("1. first\n2. second")
    expect(ol).toContain("<ol>")
    expect(ol).toContain("<li>first</li>")
  })

  it("renders GFM tables", () => {
    const md = "| A | B |\n|---|---|\n| 1 | 2 |"
    const html = renderMarkdown(md)
    expect(html).toContain("<table>")
    expect(html).toContain("<th>A</th>")
    expect(html).toContain("<td>1</td>")
    expect(html).toContain("<td>2</td>")
  })

  it("renders fenced code blocks", () => {
    const html = renderMarkdown("```\ncode line\n```")
    expect(html).toContain("<pre><code>")
    expect(html).toContain("code line")
  })

  it("escapes HTML to prevent injection", () => {
    const html = renderMarkdown("<script>alert(1)</script>")
    expect(html).not.toContain("<script>")
    expect(html).toContain("&lt;script&gt;")
  })

  it("turns links into anchors", () => {
    const html = renderMarkdown("[site](https://example.com)")
    expect(html).toContain('href="https://example.com"')
    expect(html).toContain("site</a>")
  })
})
