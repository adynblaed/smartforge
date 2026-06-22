// Shared ForgeAI chat-session store (localStorage). Both the dedicated ForgeAI
// page and the site-wide agent bubble read/write the SAME sessions + the SAME
// "active" pointer, so conversations are unified: the bubble opens the last
// selected chat, and a chat started anywhere shows up in the page's history.

const INDEX_KEY = "forgeai-session-index"
const ACTIVE_KEY = "forgeai-active-session"

export const forgeSessionKey = (id: string) => `forgeai-session-${id}`
const titleKey = (id: string) => `forgeai-session-title-${id}`
export const newForgeId = () => `${Date.now()}-${Math.floor(Math.random() * 1e4)}`

// Optional custom title for a session (e.g. machine chats started from the
// console get a dated, named title instead of the first-message derivation).
export function setForgeTitle(id: string, title: string): void {
  try {
    localStorage.setItem(titleKey(id), title)
  } catch {
    /* non-fatal */
  }
}
function getForgeTitle(id: string): string | null {
  try {
    return localStorage.getItem(titleKey(id))
  } catch {
    return null
  }
}

// Whether a session has no messages yet (so empty chats can be discarded).
export function forgeSessionEmpty(id: string): boolean {
  try {
    const raw = localStorage.getItem(forgeSessionKey(id))
    if (!raw) return true
    const turns = JSON.parse(raw) as unknown[]
    return !Array.isArray(turns) || turns.length === 0
  } catch {
    return true
  }
}

// Remove a session entirely (messages, title, and index entry).
export function deleteForgeSession(id: string): void {
  try {
    localStorage.removeItem(forgeSessionKey(id))
    localStorage.removeItem(titleKey(id))
  } catch {
    /* non-fatal */
  }
  saveForgeIndex(loadForgeIndex().filter((x) => x !== id))
}

export function loadForgeIndex(): string[] {
  if (typeof window === "undefined") return []
  try {
    const raw = localStorage.getItem(INDEX_KEY)
    const arr = raw ? (JSON.parse(raw) as string[]) : []
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

export function saveForgeIndex(ids: string[]): void {
  try {
    localStorage.setItem(INDEX_KEY, JSON.stringify(ids))
  } catch {
    /* quota / private mode — non-fatal */
  }
}

export function getForgeActive(): string | null {
  try {
    return localStorage.getItem(ACTIVE_KEY)
  } catch {
    return null
  }
}

export function setForgeActive(id: string): void {
  try {
    localStorage.setItem(ACTIVE_KEY, id)
  } catch {
    /* non-fatal */
  }
}

// Title: an explicit custom title if set, otherwise derived from the first
// user message.
export function forgeSessionTitle(id: string): string {
  const custom = getForgeTitle(id)
  if (custom) return custom
  try {
    const raw = localStorage.getItem(forgeSessionKey(id))
    if (!raw) return "New chat"
    const turns = JSON.parse(raw) as { role: string; text: string }[]
    const first = turns.find((t) => t.role === "user")
    return first?.text.trim().slice(0, 42) || "New chat"
  } catch {
    return "New chat"
  }
}

// Guarantee a valid index + active pointer; returns the resolved pair.
export function ensureForgeSession(): { ids: string[]; active: string } {
  let ids = loadForgeIndex()
  if (ids.length === 0) {
    const id = newForgeId()
    ids = [id]
    saveForgeIndex(ids)
    setForgeActive(id)
    return { ids, active: id }
  }
  let active = getForgeActive()
  if (!active || !ids.includes(active)) {
    active = ids[0]
    setForgeActive(active)
  }
  return { ids, active }
}

// Create a new session, make it active, return its id. An optional title is
// stored as the session's custom title.
export function createForgeSession(title?: string): string {
  const id = newForgeId()
  saveForgeIndex([id, ...loadForgeIndex()])
  setForgeActive(id)
  if (title) setForgeTitle(id, title)
  return id
}
