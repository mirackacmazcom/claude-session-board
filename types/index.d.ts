export type Tokens = { in: number; cw: number; cr: number; out: number }
export type Row = {
  id: string
  title: string
  folder: string
  scratch: boolean
  last: number
  pinned: boolean
  summary: string
  needs: string
  category: string
  cli: string[]
  tokens: Tokens | null
  /** Project the scanner assigned. */
  project: string
  /** Status the scanner inferred when the person set none. */
  auto: string
}
export type Note = { t: string; at: number }
export type Todo = { t: string; done: boolean; at: number }
export type Mark = { status?: string; notes: Note[]; handled?: string; todos?: Todo[]; project?: string }
export type View = { error: string; scanning: boolean; scannedAt: number; q: string; open: string | null; more: boolean }

declare module 'claude-code' {
  interface PluginState {
    'session-board': {
      rows: Shaped<Row[]>
      marks: Shaped<Record<string, Mark>>
      view: Shaped<View>
    }
  }
}
