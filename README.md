# Session Board

A side pane and a full local board for your **Claude Code sessions in the Claude desktop app**.
See what is waiting on you, sort chats into your own projects, keep notes and checklists that
Claude reads when you come back, read the latest messages of any chat, send a message into a
running session, and jump into a session with one click.

Everything runs on your own computer. Nothing is sent anywhere.

## What you get

**Side pane** (`/board`): a quick view next to the chat.

- **Waiting on you**: steps Claude asked you to do by hand. Tick them off.
- **Up next** and **In progress**: your sessions by status, one line each.
- **Go →** opens a session in the Claude app; a title opens its card on the full board.

**Full board** ("Open full board ↗"): a local web page with a Trello-like layout.

- **Columns** To do, In progress, Needs decision, To check, Redo, Done. Drag cards between them.
- **All chats list** on the left, grouped by Today / This week / This month / Older. Drag a chat
  onto a project chip or a column.
- **Projects** are only the ones you create (`+ Project`). Rename with a double-click, reorder by
  dragging, remove by clearing the name. Each project has its own checklist and a weekly or monthly
  report you can copy and send to a client.
- **Card**: Claude's summary, the **latest 4 messages**, a box to **send a message into the
  session**, what Claude needs from you, a checklist, notes, project, status and token usage.
- **Notes reach Claude**: a session's status, notes and open checklist items (and its project's)
  are added to Claude's context in that session, so it knows where things stand after a break.

## Install

Requirements: macOS, the Claude desktop app with Claude Code sessions, and `python3`
(it comes with Apple's Command Line Tools: run `xcode-select --install` if `python3` is missing).

At the prompt of a Claude Code terminal session:

```
/plugin install session-board --marketplace mirackacmazcom/claude-session-board
```

From a shell:

```bash
claude plugin install session-board --marketplace mirackacmazcom/claude-session-board
```

In the desktop app: click **+** next to the prompt box, then **Plugins**, **Add marketplace** with
`mirackacmazcom/claude-session-board`, then **Add plugin**.

Then type `/board` in a session to open the pane.

## How it works

- `hooks/register.tsx` is the Claude Code mod: the side pane, the `/board` command, the notes it
  adds to Claude's context, and delivery of messages sent from the board.
- `scripts/server.py` is a small Python (standard library only) web server on `127.0.0.1:47811`
  that serves `web/index.html`, the full board.
- `scripts/scan.py` reads the desktop app's session list and per-session token totals.
- `scripts/store.py` keeps your statuses, notes, checklists and projects in one JSON file, written
  under a lock so the pane and the board never overwrite each other.
- `scripts/history.py` reads a session's latest messages from its transcript when you open a card.
- `scripts/outbox.py` queues messages you send from the board; a running session with this plugin
  delivers them.

### Privacy

- The plugin reads the Claude desktop app's session files
  (`~/Library/Application Support/Claude/claude-code-sessions`) and Claude Code transcripts
  (`~/.claude/projects`). It never changes them.
- Message text is read only when you open a card and is never stored.
- Your own data (statuses, notes, checklists, projects) lives in the plugin's data folder, in
  `marks.json`.
- No network access other than your own computer.

### Security

- The server listens on `127.0.0.1` only and checks the `Host` and `Origin` headers, so other
  websites cannot reach it.
- Every API call needs a random token stored in the plugin's data folder (file mode `0600`). The
  pane opens the board with the token in the URL fragment; the page then removes it from the
  address bar.
- `Go to session` and `Send` accept only session ids from the latest scan.
- The board assumes a single-user computer: while the board opens, the token is briefly visible in
  the process list to other accounts on the same Mac.

## Limits

- **macOS only** for now (it reads the macOS desktop app's files and uses `open`).
- The desktop app's session files are not a documented format. If an update changes them, the
  board may show fewer details until the plugin is updated.
- **Sending a message** works only for sessions that are running right now, and needs at least one
  other session running this plugin (a session cannot message itself). The message arrives framed
  as coming from another session, so Claude may ask you before doing anything destructive.
- Statuses you do not set are guessed from the session title and Claude's summary (for example
  "done", "check", "again" in a title). Set a status yourself to override the guess.

## Development

Type-check with `tsc -p .` after the plugin has been loaded once by Claude Code: `tsconfig.json`
extends the type files the engine writes to `.claude-plugin/types/` (not part of this repository).
Run the tests with `claude plugin test .`.

## License

MIT, see [LICENSE](LICENSE).
