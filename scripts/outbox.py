"""Messages the web board asks to send into a running session.

The board cannot reach the engine, so the server queues each message as a
file and whichever open Claude Code session runs this plugin delivers it with
$.session.send. Claiming is an atomic rename, so two sessions never both send.

  outbox.py claim <data dir>          print one claimed job as JSON, or nothing
  outbox.py done  <data dir> <key>    stdin: {"ok": bool, "reason": str}
"""
import json, os, secrets, sys, time

KEY_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def box(data_dir):
    d = os.path.join(data_dir, "outbox")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def queue(data_dir, sid, cli, title, text):
    key = f"{int(time.time() * 1000)}-{secrets.token_hex(4)}"
    tmp = os.path.join(box(data_dir), key + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"key": key, "id": sid, "cli": cli, "title": title, "text": text}, fh, ensure_ascii=False)
    os.replace(tmp, os.path.join(box(data_dir), key + ".json"))
    return key


def result(data_dir, key):
    if not key or set(key) - KEY_OK:
        return None
    d = box(data_dir)
    try:
        with open(os.path.join(d, key + ".done")) as fh:
            return json.load(fh)
    except FileNotFoundError:
        pass
    c = os.path.join(d, key + ".claimed")
    try:  # taken by a session that never answered: it closed or crashed mid-send
        if time.time() - os.path.getmtime(c) > 60:
            os.remove(c)
            return {"ok": False, "reason": "The delivering session did not answer; the message may not have arrived. Open the session to check."}
        return {"pending": True}
    except FileNotFoundError:
        pass
    p = os.path.join(d, key + ".json")
    try:
        age = time.time() - os.path.getmtime(p)
    except FileNotFoundError:  # claimed this moment, or already answered
        return {"pending": True}
    # nobody picked it up: no other running session has this plugin
    if age > 20:
        try:
            os.remove(p)
        except FileNotFoundError:
            return {"pending": True}
        return {"ok": False, "reason": "No other running Claude session can deliver it (a session cannot message itself). Open another session in the Claude app and try again."}
    return {"pending": True}


def claim(data_dir, skip=""):
    """Take one pending job, leaving jobs for `skip` (the claiming session itself) to others."""
    d = box(data_dir)
    now = time.time()
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if name.endswith(".done") and now - os.path.getmtime(p) > 3600:
            os.remove(p)
        if not name.endswith(".json"):
            continue
        if skip:
            try:
                with open(p) as fh:
                    if skip in (json.load(fh).get("cli") or []):
                        continue
            except (FileNotFoundError, ValueError):
                continue
        mine = p[:-5] + ".claimed"
        try:
            os.rename(p, mine)
        except FileNotFoundError:
            continue
        with open(mine) as fh:
            job = json.load(fh)
        return job  # the .claimed file stays until done() answers it
    return None


def done(data_dir, key, res):
    if not key or set(key) - KEY_OK:
        return
    p = os.path.join(box(data_dir), key + ".done")
    fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"ok": bool(res.get("ok")), "reason": str(res.get("reason") or "")[:500]}, fh, ensure_ascii=False)
    os.replace(p + ".tmp", p)
    try:
        os.remove(os.path.join(box(data_dir), key + ".claimed"))
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    cmd, data_dir = sys.argv[1], sys.argv[2]
    if cmd == "claim":
        job = claim(data_dir, sys.argv[3] if len(sys.argv) > 3 else "")
        if job:
            json.dump(job, sys.stdout, ensure_ascii=False)
    elif cmd == "done":
        done(data_dir, sys.argv[3], json.loads(sys.stdin.read() or "{}"))
