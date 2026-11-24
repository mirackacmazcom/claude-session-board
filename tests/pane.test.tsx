import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'session-board',
  component: 'Pane',
  requestId: 'session-board',
  surface: 'desktop',
  props: { title: 'Sessions', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} },
} as const
const NOW = Date.UTC(2026, 10, 24, 12)
const row = (id: string, title: string, auto: string, needs = '') => ({
  id, title, folder: 'x', scratch: false, last: NOW - 3600000, pinned: true, summary: '', needs, category: '', cli: [`cli-${id}`], tokens: null, project: '', auto,
})
const ok = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })

test('the pane ticks an ask, finishes a session and opens a card on the board', async ($, on) => {
  const calls: { argv: readonly string[]; stdin?: string }[] = []
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('clock.now', () => ({ value: NOW }))
  on('clock.every', () => ({ value: undefined }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => {
    calls.push({ argv: e.argv, stdin: e.init?.stdin })
    const script = String(e.argv[2] ?? e.argv[0])
    if (script.endsWith('scan.py'))
      return ok(JSON.stringify({ scannedAt: NOW, marks: {}, sessions: [row('a', 'CSS Fix', 'tekrar'), row('b', 'Domain', 'karar', 'Add Cloudflare')] }))
    if (script.endsWith('marks.py')) return ok(JSON.stringify({ marks: {}, rev: 1 }))
    if (script.endsWith('server.py')) return ok(JSON.stringify({ url: 'http://127.0.0.1:47811/#t=x' }))
    return ok('')
  })

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(PANE)
  await ui.press({ key: 'refresh' })

  const sent = () => calls.map(c => c.stdin ?? '').join('\n')
  await ui.press({ key: 'ask-ok-b' })
  expect(sent()).toContain('"op":"handled","id":"b","value":"Add Cloudflare"')

  await ui.press({ key: 'ln-done-a' })
  expect(sent()).toContain('"op":"status","id":"a","value":"bitti"')

  await ui.press({ key: 'ln-open-a' })
  expect(calls.map(c => c.argv.join(' '))).toContain('open http://127.0.0.1:47811/#t=x&card=a')
  await ui.unmount()
})
