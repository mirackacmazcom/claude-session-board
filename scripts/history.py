"""The last few messages of a session, read on demand and never stored.

Only the conversation itself: the person's typed messages and Claude's text
replies. Tool calls, tool results, thinking, meta and injected blocks are
skipped. Consecutive Claude texts within one turn become one reply. The
transcript is read from its end in chunks, so long sessions stay fast.
"""
import glob, json, os, re

PROJ = os.path.join(os.path.expanduser("~"), ".claude/projects")
CHUNK = 1 << 20
LIMIT = 4000
# blocks the app or hooks wrap around a typed message: hyphenated or ide_ tags, with or without attributes
INJECTED = re.compile(
    r"<(system-reminder|artifact-view-context|pasted_content|user-prompt-submit-hook|command-[a-z-]+|local-command-[a-z-]+|ide_[a-z_]+)(?:\s[^>]*)?>.*?</\1>",
    re.S,
)


def _path(cli):
    hits = glob.glob(os.path.join(PROJ, "*", glob.escape(cli) + ".jsonl"))
    return hits[0] if hits else None


def _lines_from_end(path):
    """Yield complete lines, newest first."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos, rest = fh.tell(), b""
        while pos > 0:
            step = min(CHUNK, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + rest
            parts = buf.split(b"\n")
            rest = parts.pop(0) if pos > 0 else b""
            for line in reversed(parts):
                if line.strip():
                    yield line
        if rest.strip():
            yield rest


def _user_text(content):
    if isinstance(content, str):
        text, images = content, 0
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        images = sum(1 for b in content if isinstance(b, dict) and b.get("type") == "image")
    else:
        return None
    text = INJECTED.sub("", text).strip()
    if text.startswith("This session is being continued from a previous conversation") or text.startswith("[Request interrupted"):
        return None
    if images:
        text = (f"[{images} images] " if images > 1 else "[image] ") + text
    return text.strip() or None


BOARD = re.compile(r"<cross-session-message\b[^>]*>(.*?)</cross-session-message>", re.S)
PREFIXES = (
    "[Session Board] The user sent this message to this session from the web board:",
)


def _from_board(content):
    """A message this board sent in, shown as the person's own."""
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    pre = next((x for x in PREFIXES if isinstance(content, str) and x in content), None)
    if not pre:
        return None
    hit = BOARD.search(content)
    body = hit.group(1) if hit else content
    return body.split(pre, 1)[-1].strip() or None


def _entries(path):
    """Yield (role, text, timestamp, message id) newest first."""
    for raw in _lines_from_end(path):
        if b'"message"' not in raw:
            continue
        try:
            o = json.loads(raw)
        except Exception:
            continue
        m = o.get("message")
        if not isinstance(m, dict):
            continue
        if o.get("isMeta") and o.get("type") == "user":
            t = _from_board(m.get("content"))
            if t:
                yield "board", t, o.get("timestamp") or "", o.get("uuid")
            continue
        if o.get("isSidechain") or o.get("isMeta") or o.get("isCompactSummary"):
            continue
        if o.get("type") == "user":
            t = _user_text(m.get("content"))
            if t:
                yield "user", t, o.get("timestamp") or "", o.get("uuid")
        elif o.get("type") == "assistant":
            c = m.get("content")
            if isinstance(c, list):
                t = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text").strip()
                if t:
                    yield "assistant", t, o.get("timestamp") or "", m.get("id") or o.get("uuid")


def last_messages(cli_ids, n=4):
    found = []
    for cli in cli_ids:
        p = _path(cli)
        if not p:
            continue
        got, seen = [], set()
        for role, text, ts, mid in _entries(p):
            if mid in seen:
                continue
            seen.add(mid)
            # newest first: a Claude text joins the reply that follows it in the same turn
            if got and role == "assistant" and got[-1]["role"] == "assistant":
                got[-1]["text"] = text + "\n\n" + got[-1]["text"]
                continue
            if len(got) == n:
                break
            got.append({"role": role, "text": text, "at": ts})
        found += got
    found.sort(key=lambda x: x["at"])
    out = found[-n:]
    for x in out:
        if len(x["text"]) > LIMIT:
            x["text"] = x["text"][:LIMIT].rstrip() + " …"
    return out
