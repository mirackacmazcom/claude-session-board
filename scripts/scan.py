"""Read the Claude desktop app's session list and per-session token totals.

Run as a script it prints {"sessions": [...], "marks": {...}, "rev": n,
"scannedAt": ms}. Token totals are cached by transcript path, size and mtime in
<data dir>/token-cache.json so only changed transcripts are re-read. The
session files are the app's own, undocumented: a record that does not parse is
skipped, never fatal.
"""
import glob, json, os, re, sys, time

HOME = os.path.expanduser("~")
META = os.path.join(HOME, "Library/Application Support/Claude/claude-code-sessions/*/*/local_*.json")
PROJ = os.path.join(HOME, ".claude/projects")
DAY = 86400000


def auto_status(title, needs, last, now):
    t = title.lower()
    if "karar bekliyor" in t or "needs decision" in t:
        return "karar"
    if "again" in t and "look-up" not in t:
        return "tekrar"
    if "check" in t or "look-up" in t or "kontrol" in t:
        return "kontrol"
    if re.search(r"\(done|\bdone\b|\(bitti", t):
        return "bitti"
    if needs and now - last < 3 * DAY:
        return "karar"
    return "devam"


def scan(data_dir):
    cache_path = os.path.join(data_dir, "token-cache.json")
    try:
        cache = json.load(open(cache_path))
    except Exception:
        cache = {}
    transcripts = {os.path.basename(p)[:-6]: p for p in glob.glob(os.path.join(PROJ, "*", "*.jsonl"))}

    def tokens(path):
        st = os.stat(path)
        key = f"{st.st_size}:{int(st.st_mtime)}"
        hit = cache.get(path)
        if hit and hit.get("key") == key:
            return hit["t"]
        seen, t = set(), {"in": 0, "cw": 0, "cr": 0, "out": 0}
        with open(path, errors="ignore") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                m = o.get("message")
                if o.get("type") != "assistant" or not isinstance(m, dict) or not m.get("usage"):
                    continue
                mid = m.get("id") or o.get("uuid")
                if mid in seen:
                    continue
                seen.add(mid)
                u = m["usage"]
                t["in"] += u.get("input_tokens") or 0
                t["cw"] += u.get("cache_creation_input_tokens") or 0
                t["cr"] += u.get("cache_read_input_tokens") or 0
                t["out"] += u.get("output_tokens") or 0
        cache[path] = {"key": key, "t": t}
        return t

    now = int(time.time() * 1000)
    out = []
    for f in glob.glob(META):
        try:
            d = json.load(open(f))
            if not isinstance(d, dict) or d.get("isArchived") or not d.get("sessionId"):
                continue
            cli = d.get("lastAssistantCliSessionId") or d.get("cliSessionId")
            t = None
            for sid in {cli, d.get("cliSessionId")} - {None}:
                p = transcripts.get(sid)
                if p:
                    x = tokens(p)
                    t = x if t is None else {k: t[k] + x[k] for k in t}
            pts = d.get("postTurnSummary") or {}
            cwd = d.get("cwd") or ""
            title = d.get("title") or "Untitled session"
            folder = os.path.basename(cwd.rstrip("/"))
            scratch = "/scratch-workspaces/" in cwd
            last = d.get("lastActivityAt") or d.get("createdAt") or 0
            needs = pts.get("needs_action") or ""
            out.append({
                "id": d["sessionId"],
                "title": title,
                "folder": folder,
                "scratch": scratch,
                "last": last,
                "pinned": bool(d.get("isStarred")),
                "summary": pts.get("status_detail") or "",
                "needs": needs,
                "category": pts.get("status_category") or "",
                "cli": [x for x in dict.fromkeys([cli, d.get("cliSessionId")]) if x],  # newest first
                "tokens": t,
                "project": "",  # projects are only the ones the person makes
                "auto": auto_status(title, needs, last, now),
            })
        except Exception:
            continue
    try:
        tmp = f"{cache_path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump(cache, fh)
        os.replace(tmp, cache_path)
    except Exception:
        pass
    out.sort(key=lambda r: -r["last"])
    return out, now


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import store

    data_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/session-board"
    os.makedirs(data_dir, exist_ok=True)
    sessions, now = scan(data_dir)
    m = store.load(data_dir)
    json.dump({"sessions": sessions, "marks": m["marks"], "rev": m["rev"], "migrated": m.get("migrated", False), "scannedAt": now}, sys.stdout, ensure_ascii=False)
