import { atom, read, update } from 'claude-code'
import type { CoreEngineInterface, Register } from 'claude-code'

import type { Mark, Row, View } from '../types'

// The side pane is the quick view: what waits on you, what is next, one press
// into a session. Editing lives on the web board (scripts/server.py), which
// shares the same marks file; both write it only through scripts/marks.py.

const PANE = 'session-board'
const rowsA = atom({ plugin: 'session-board', key: 'rows' } as const, [] as Row[], { shape: 'rows-3' })
const marksA = atom({ plugin: 'session-board', key: 'marks' } as const, {} as Record<string, Mark>, { shape: 'marks-2' })
const viewA = atom(
  { plugin: 'session-board', key: 'view' } as const,
  { error: '', scanning: false, scannedAt: 0, q: '', open: null, more: false } as View,
  { shape: 'view-5' },
)

const DAY = 86400000
const STATUSES = [
  { k: 'tekrar', label: 'Redo', color: 'error' },
  { k: 'karar', label: 'Needs decision', color: 'warning' },
  { k: 'kontrol', label: 'To check', color: 'suggestion' },
  { k: 'yapilacak', label: 'To do', color: 'subtle' },
  { k: 'devam', label: 'In progress', color: 'claude' },
  { k: 'bitti', label: 'Done', color: 'success' },
] as const
const S = Object.fromEntries(STATUSES.map((s, i) => [s.k, { ...s, rank: i }])) as Record<string, { k: string; label: string; color: string; rank: number }>
const info = (k: string) => S[k] ?? S['devam']!
const NEXT = ['tekrar', 'karar', 'kontrol', 'yapilacak']
const LABELS = ['#4bce97', '#e2b203', '#faa53d', '#f87168', '#9f8fef', '#579dff', '#6cc3e0', '#94c748']
const labelOf = (name: string) => LABELS[[...name].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % LABELS.length]!

const statusOf = (r: Row, m: Record<string, Mark>) => {
  const v = m[r.id]?.status
  return v && S[v] ? v : S[r.auto] ? r.auto : 'devam'
}
const isOpen = (r: Row, m: Record<string, Mark>, now: number) =>
  statusOf(r, m) !== 'bitti' && (!!m[r.id]?.status || r.pinned || now - r.last < 7 * DAY)
const waits = (r: Row, m: Record<string, Mark>) => !!r.needs && m[r.id]?.handled !== r.needs
const clip = (t: string, n: number) => (t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t)
const short = (t: string) => t.replace(/\s*\([^)]*\)\s*$/, '')
function ago(ms: number, now: number): string {
  const m = Math.round((now - ms) / 60000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.round(h / 24)
  return d === 1 ? 'yesterday' : `${d}d`
}
function day(ms: number): string {
  const d = new Date(ms)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

type Host = CoreEngineInterface
type Op = { op: string; id: string; value?: string | null; t?: string; at?: number; marks?: Record<string, Mark> }

async function paths($: Host) {
  let env: { CLAUDE_PLUGIN_ROOT?: string; CLAUDE_PLUGIN_DATA?: string } = {}
  try {
    env = await $.process.hookEnv()
  } catch {}
  const root = env.CLAUDE_PLUGIN_ROOT ?? '.'
  return { root, data: env.CLAUDE_PLUGIN_DATA ?? '/tmp/session-board' }
}

async function refresh($: Host) {
  await update($, viewA, v => ({ ...v, scanning: true }))
  try {
    const p = await paths($)
    const r = await $.process.run(['python3', '-I', `${p.root}/scripts/scan.py`, p.data], { timeoutMs: 600000 })
    if (r.exitCode !== 0) throw new Error(r.stderr.trim().split('\n').pop() || `exit code ${r.exitCode}`)
    const d = JSON.parse(r.stdout) as { sessions: Row[]; marks: Record<string, Mark>; scannedAt: number }
    await update($, rowsA, () => d.sessions)
    await update($, marksA, () => d.marks)
    await update($, viewA, v => ({ ...v, scanning: false, error: '', scannedAt: d.scannedAt }))
  } catch (err) {
    await update($, viewA, v => ({ ...v, scanning: false, error: String((err as Error)?.message ?? err) }))
  }
}

// Re-read only the marks, so edits made on the web board show up here.
async function reloadMarks($: Host) {
  try {
    const p = await paths($)
    const r = await $.process.run(['python3', '-I', `${p.root}/scripts/marks.py`, p.data], { timeoutMs: 20000 })
    if (r.exitCode === 0) {
      const d = JSON.parse(r.stdout) as { marks: Record<string, Mark> }
      const cur = await read($, marksA)
      if (JSON.stringify(cur) !== JSON.stringify(d.marks)) await update($, marksA, () => d.marks)
    }
  } catch {}
}

async function markOps($: Host, ops: Op[]) {
  // Shown at once; the file's answer replaces it.
  await update($, marksA, all => {
    const next = { ...all }
    for (const o of ops) {
      const m: Mark = { notes: [], ...(next[o.id] ?? {}) }
      if (o.op === 'status') o.value ? (m.status = o.value) : delete m.status
      else if (o.op === 'handled') o.value ? (m.handled = o.value) : delete m.handled
      else continue
      next[o.id] = m
    }
    return next
  })
  try {
    const p = await paths($)
    const r = await $.process.run(['python3', '-I', `${p.root}/scripts/marks.py`, p.data], { stdin: JSON.stringify(ops), timeoutMs: 20000 })
    if (r.exitCode !== 0) throw new Error(r.stderr.trim().split('\n').pop() || 'could not save')
    const d = JSON.parse(r.stdout) as { marks: Record<string, Mark> }
    await update($, marksA, () => d.marks)
  } catch (err) {
    $.ui.toast(`Could not save: ${String((err as Error)?.message ?? err)}`)
  }
}

async function openBoard($: Host, extra = '') {
  try {
    const p = await paths($)
    const r = await $.process.run(['python3', '-I', `${p.root}/scripts/server.py`, 'ensure', p.data], { timeoutMs: 20000 })
    const d = JSON.parse(r.stdout || '{}') as { url?: string; error?: string }
    if (!d.url) throw new Error(d.error || r.stderr.trim().split('\n').pop() || 'the server did not start')
    const o = await $.process.run(['open', d.url + extra])
    if (o.exitCode !== 0) throw new Error('could not open the browser')
  } catch (err) {
    $.ui.toast(`Could not open the board: ${String((err as Error)?.message ?? err)}`)
  }
}

async function goSession($: Host, id: string) {
  const r = await $.process.run(['open', `claude://claude.ai/epitaxy/${id}`])
  if (r.exitCode !== 0) $.ui.toast('Could not open the session')
}

// Messages typed on the web board wait in the outbox until a running session
// with this plugin claims one (scripts/outbox.py) and hands it to the engine.
const NOT_RUNNING = 'This session is not running. Open it in the Claude app (Go to session), then send again.'
const SELF = 'This is the session that runs the board; a session cannot message itself. Write in that chat directly.'
// The engine's reasons are written for the model; say them plainly.
const plain = (why: string) =>
  /itself|yourself/i.test(why) ? SELF
  : /not reachable|no live session|not running|exited/i.test(why) ? NOT_RUNNING
  : /several|more than one|ambiguous/i.test(why) ? 'Several open sessions have this name; rename one of them and try again.'
  : why
let pumping = false
async function pump($: Host) {
  if (pumping) return
  pumping = true
  try {
    const p = await paths($)
    // a session cannot message itself: jobs for this one are left to another session
    const self = await $.session.id().catch(() => '')
    if (!self) return // without our own id we could claim a job meant for this very session
    for (let i = 0; i < 5; i++) {
      const r = await $.process.run(['python3', '-I', `${p.root}/scripts/outbox.py`, 'claim', p.data, self], { timeoutMs: 10000 })
      if (r.exitCode !== 0 || !r.stdout.trim()) break
      const job = JSON.parse(r.stdout) as { key: string; cli: string[]; title?: string; text: string }
      // A live desktop session answers to its name as ListAgents lists it; its
      // transcript id is tried first in case the engine knows it by that.
      const targets: ({ sessionId: string } | string)[] = [...job.cli.map(sessionId => ({ sessionId })), ...(job.title ? [job.title] : [])]
      let res: { ok: boolean; reason: string } = { ok: false, reason: NOT_RUNNING }
      for (const to of targets) {
        try {
          const sent = await $.session.send({ to, text: `[Session Board] The user sent this message to this session from the web board:\n\n${job.text}` })
          if (sent.isDelivered) { res = { ok: true, reason: '' }; break }
          res = { ok: false, reason: plain(sent.reason) }
        } catch (err) {
          res = { ok: false, reason: String((err as Error)?.message ?? err) }
        }
      }
      await $.process.run(['python3', '-I', `${p.root}/scripts/outbox.py`, 'done', p.data, job.key], { stdin: JSON.stringify(res), timeoutMs: 10000 })
    }
  } catch {
  } finally {
    pumping = false
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'board', description: 'Open the session board' })
    void refresh($)
    $.clock.every(12000, () => void reloadMarks($))
    $.clock.every(3000, () => void pump($))
    return next(e)
  })

  on('command.run', { command: 'board' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Sessions' })
    void refresh($)
    return { text: 'Session board opened.' }
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    void refresh($)
    return done
  })

  // The person's status, notes and open checklist items for this session and
  // its project reach Claude, so it knows where things stand after a break.
  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    try {
      const cli = await $.session.id()
      const rows = await read($, rowsA)
      const marks = await read($, marksA)
      const r = rows.find(x => x.cli.includes(cli))
      if (!r) return composed
      const m = marks[r.id] ?? { notes: [] }
      const own = (m.todos ?? []).filter(t => !t.done)
      const pname = m.project || ''
      const proj = pname ? (marks[`proj:${pname}`]?.todos ?? []).filter(t => !t.done) : []
      if (!m.status && m.notes.length === 0 && own.length === 0 && proj.length === 0) return composed
      const lines = [
        'Session Board (what the user keeps for this session):',
        m.status ? `- Status set by the user: ${info(m.status).label}` : '',
        ...m.notes.map(n => `- User note (${day(n.at)}): ${n.t}`),
        ...own.map(t => `- Open checklist item for this session: ${t.t}`),
        ...proj.map(t => `- Open checklist item for project ${pname}: ${t.t}`),
        'Take these into account when the user asks where you left off or when you continue the work.',
      ].filter(Boolean)
      return { ...composed, sections: [...composed.sections, { id: 'session-board-notes', text: lines.join('\n'), scope: 'session' as const }] }
    } catch {
      return composed
    }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Input } = $.ui.resolve(e)
    const marks = await read($, marksA)
    // Projects are only the ones the person made on the web board.
    const rows = (await read($, rowsA)).map(r => ({ ...r, project: marks[r.id]?.project || '' }))
    const view = await read($, viewA)
    const now = await $.clock.now()
    const setView = (fn: (v: View) => View) => update($, viewA, fn)

    const st = (r: Row) => statusOf(r, marks)
    const byRecent = (a: Row, b: Row) => b.last - a.last
    const asks = rows.filter(r => waits(r, marks)).sort(byRecent)
    const nextUp = rows.filter(r => NEXT.includes(st(r))).sort((a, b) => info(st(a)).rank - info(st(b)).rank || b.last - a.last)
    const doing = rows.filter(r => st(r) === 'devam' && isOpen(r, marks, now)).sort(byRecent)
    const q = view.q.trim().toLocaleLowerCase()
    const found = q
      ? rows.filter(r =>
          [r.title, r.summary, r.needs, r.project, ...(marks[r.id]?.notes ?? []).map(n => n.t), ...(marks[r.id]?.todos ?? []).map(t => t.t)]
            .join(' ')
            .toLocaleLowerCase()
            .includes(q),
        )
      : []

    const Chip = (name: string, k: string) => (
      <Text key={k} size="caption" weight="semibold" color="#1d2125" backgroundColor={labelOf(name)}>{` ${name} `}</Text>
    )

    const Heading = (title: string, n: number, k: string, more?: { label: string; extra: string }) => (
      <Box key={k} flexDirection="row" alignItems="center" gap="sm" paddingX="sm" marginTop="md">
        <Text size="caption" weight="semibold" dimColor>{title}</Text>
        <Text size="caption" dimColor tabular>{n}</Text>
        <Box flexGrow={1} />
        {more ? (
          <Button key={`${k}-more`} plain dimColor onPress={() => openBoard($, more.extra)}>
            <Text size="caption">{more.label}</Text>
          </Button>
        ) : null}
      </Box>
    )

    // Something Claude asked you to do: a box to tick, the ask, where it came from.
    const Ask = (r: Row) => {
      const scope = `ask-${r.id}`
      return (
        <Box key={scope} flexDirection="row" gap="sm" alignItems="flex-start" borderStyle="round" borderColor="inactive" borderDimColor paddingX="sm" paddingY="xs" hover={{ scope, borderColor: 'warning', borderDimColor: false }}>
          <Button key={`ask-ok-${r.id}`} plain dimColor onPress={() => markOps($, [{ op: 'handled', id: r.id, value: r.needs }])}>☐</Button>
          <Box flexDirection="column" gap="xs" flexGrow={1} flexShrink={1} minWidth={0}>
            <Button key={`ask-open-${r.id}`} plain onPress={() => openBoard($, `&card=${r.id}`)}>
              <Text size="footnote">{clip(r.needs, 120)}</Text>
            </Button>
            <Box flexDirection="row" gap="sm" alignItems="center">
              {r.project ? Chip(r.project, `ask-chip-${r.id}`) : null}
              <Box flexShrink={1} minWidth={0}><Text size="caption" dimColor wrap="truncate-end">{short(r.title)}</Text></Box>
              <Text size="caption" dimColor>{ago(r.last, now)}</Text>
            </Box>
          </Box>
          <Box display="none" hover={{ scope, display: 'flex' }}>
            <Button key={`ask-go-${r.id}`} plain onPress={() => goSession($, r.id)}>Go →</Button>
          </Box>
        </Box>
      )
    }

    // A session on one line: status dot, title, project, age; actions on hover.
    const Line = (r: Row) => {
      const s = info(st(r))
      const scope = `ln-${r.id}`
      const todos = marks[r.id]?.todos ?? []
      const done = todos.filter(t => t.done).length
      return (
        <Box key={scope} flexDirection="row" alignItems="center" gap="sm" paddingX="sm" paddingY="xs" hover={{ scope, backgroundColor: '#8080801c' }}>
          <Text color={s.color}>●</Text>
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Button key={`ln-open-${r.id}`} plain onPress={() => openBoard($, `&card=${r.id}`)}>
              <Text size="footnote" wrap="truncate-end">{short(r.title)}</Text>
            </Button>
          </Box>
          {todos.length ? <Text size="caption" dimColor tabular>☑ {done}/{todos.length}</Text> : null}
          <Box flexDirection="row" gap="xs" display="none" hover={{ scope, display: 'flex' }}>
            {s.k !== 'bitti' ? (
              <Button key={`ln-done-${r.id}`} plain dimColor onPress={() => markOps($, [{ op: 'status', id: r.id, value: 'bitti' }])}>✓</Button>
            ) : null}
            <Button key={`ln-go-${r.id}`} plain onPress={() => goSession($, r.id)}>Go →</Button>
          </Box>
          <Box width={12} flexShrink={0} alignItems="flex-end">
            <Text size="caption" dimColor wrap="truncate-end">{r.project}</Text>
          </Box>
          <Box width={6} flexShrink={0} alignItems="flex-end">
            <Text size="caption" dimColor tabular>{ago(r.last, now)}</Text>
          </Box>
        </Box>
      )
    }

    const status = view.scanning && !view.scannedAt ? 'reading…' : `${nextUp.length + doing.length} open · ${asks.length} waiting on you`
    const ASK_N = view.more ? 30 : 4

    return (
      <Box flexDirection="column" gap="sm" paddingX="sm" paddingY="sm">
        <Box flexDirection="row" alignItems="center" gap="sm" paddingX="sm">
          <Box flexDirection="column" flexGrow={1}>
            <Text weight="semibold">Sessions</Text>
            <Text size="caption" dimColor>{status}</Text>
          </Box>
          <Button key="refresh" plain dimColor onPress={() => refresh($)}>{view.scanning ? '…' : '↻'}</Button>
        </Box>

        <Box flexDirection="row" gap="sm" paddingX="sm" alignItems="center">
          <Button key="board" variant="primary" onPress={() => openBoard($)}>Open full board ↗</Button>
          <Box flexGrow={1} minWidth={0}>
            <Input key="search" placeholder="Search" value={view.q} onInput={v => setView(x => ({ ...x, q: v }))} onSubmit={v => setView(x => ({ ...x, q: v }))} />
          </Box>
        </Box>

        {view.error ? (
          <Box paddingX="sm"><Text size="footnote" color="error">Could not read sessions: {view.error}</Text></Box>
        ) : null}
        {rows.length === 0 && !view.error ? <Box paddingX="sm" paddingY="md"><Text dimColor>Reading sessions…</Text></Box> : null}

        {q ? (
          <Box flexDirection="column">
            {Heading('RESULTS', found.length, 'h-found')}
            {found.length ? found.slice(0, 25).map(r => Line(r)) : <Box paddingX="sm" paddingY="sm"><Text size="footnote" dimColor>No matching sessions.</Text></Box>}
          </Box>
        ) : rows.length ? (
          <Box flexDirection="column" gap="xs">
            {Heading('WAITING ON YOU', asks.length, 'h-ask', asks.length > ASK_N ? { label: 'all →', extra: '&view=inbox' } : undefined)}
            {asks.length === 0 ? (
              <Box paddingX="sm"><Text size="footnote" dimColor>Nothing is waiting on you. ✓</Text></Box>
            ) : (
              <Box flexDirection="column" gap="xs">{asks.slice(0, ASK_N).map(r => Ask(r))}</Box>
            )}

            {Heading('UP NEXT', nextUp.length, 'h-next')}
            {nextUp.length === 0 ? (
              <Box paddingX="sm"><Text size="footnote" dimColor>Nothing up next.</Text></Box>
            ) : (
              <Box flexDirection="column">{nextUp.slice(0, 8).map(r => Line(r))}</Box>
            )}

            {Heading('IN PROGRESS', doing.length, 'h-doing', doing.length > 8 ? { label: 'see on board →', extra: '&view=pano' } : undefined)}
            <Box flexDirection="column">{doing.slice(0, 8).map(r => Line(r))}</Box>
          </Box>
        ) : null}
      </Box>
    )
  })
}
