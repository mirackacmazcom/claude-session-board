"""The board's own data: the person's marks (status, notes, checklist, handled).

One JSON file in the plugin data dir, changed only through apply(): a separate
lock file is held across read, patch and atomic replace, so the side pane and
the web board never lose each other's edits. Every op names one field.
"""
import fcntl, json, os, secrets, tempfile
from contextlib import contextmanager

VERSION = 1
STATUSES = {"tekrar", "karar", "kontrol", "devam", "yapilacak", "bitti"}


def paths(data_dir):
    os.makedirs(data_dir, mode=0o700, exist_ok=True)
    return {
        "marks": os.path.join(data_dir, "marks.json"),
        "lock": os.path.join(data_dir, "marks.lock"),
        "token": os.path.join(data_dir, "token"),
    }


@contextmanager
def locked(data_dir):
    p = paths(data_dir)
    fd = os.open(p["lock"], os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield p
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read(p):
    try:
        with open(p["marks"]) as fh:
            d = json.load(fh)
        if isinstance(d, dict) and isinstance(d.get("marks"), dict):
            return d
    except FileNotFoundError:
        pass
    except Exception:
        # A damaged file is kept aside, never silently replaced.
        os.replace(p["marks"], p["marks"] + ".bad")
    return {"v": VERSION, "rev": 0, "migrated": False, "marks": {}}


def _write(p, d):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p["marks"]), prefix=".marks-")
    with os.fdopen(fd, "w") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p["marks"])


def load(data_dir):
    with locked(data_dir) as p:
        return _read(p)


def _clean(s, n):
    return str(s or "").strip()[:n]


def _mark(marks, key):
    m = marks.setdefault(key, {})
    m.setdefault("notes", [])
    return m


def _one(marks, op, now):
    kind, key = op.get("op"), _clean(op.get("id"), 300)
    if not key:
        return
    if kind == "import":  # one-time copy of the pane's older store
        if key == "*" and isinstance(op.get("marks"), dict):
            for k, v in op["marks"].items():
                if k not in marks and isinstance(v, dict):
                    marks[k] = v
        return
    m = _mark(marks, key)
    if kind == "status":
        v = op.get("value")
        if v in STATUSES:
            m["status"] = v
        elif v is None:
            m.pop("status", None)
    elif kind == "project":  # move one session into a project; None = back to the guessed one
        v = _clean(op.get("value"), 60)
        if v:
            m["project"] = v
        else:
            m.pop("project", None)
    elif kind == "handled":
        v = op.get("value")
        if v:
            m["handled"] = _clean(v, 4000)
        else:
            m.pop("handled", None)
    elif kind in ("note.add", "todo.add"):
        t = _clean(op.get("t"), 1000)
        if t:
            lst = m.setdefault("notes" if kind == "note.add" else "todos", [])
            try:
                at = int(op.get("at") or now)
            except (TypeError, ValueError):
                at = now
            while any(x.get("at") == at for x in lst):
                at += 1
            lst.append({"t": t, "at": at, **({"done": False} if kind == "todo.add" else {})})
    elif kind in ("note.del", "todo.del"):
        f = "notes" if kind == "note.del" else "todos"
        m[f] = [x for x in m.get(f, []) if x.get("at") != op.get("at")]
    elif kind == "todo.flip":
        for x in m.get("todos", []):
            if x.get("at") == op.get("at"):
                x["done"] = not x.get("done")
    elif kind == "todo.edit":
        t = _clean(op.get("t"), 1000)
        for x in m.get("todos", []):
            if x.get("at") == op.get("at") and t:
                x["t"] = t


def _names(d):
    lst = d.get("projects")
    if not isinstance(lst, list):
        lst = d["projects"] = []
    return lst


def _proj(d, op):
    """Board-level project list: names the person added and the chip order."""
    kind, lst = op.get("op"), _names(d)
    if kind == "proj.add":
        n = _clean(op.get("name"), 60)
        if n and n not in lst:
            lst.append(n)
    elif kind == "proj.order":
        names = [_clean(x, 60) for x in op.get("names") or [] if _clean(x, 60)]
        seen = []
        for n in names + lst:
            if n not in seen:
                seen.append(n)
        d["projects"] = seen[:200]
    elif kind == "proj.rename":
        a, b = _clean(op.get("from"), 60), _clean(op.get("to"), 60)
        if a and b and a != b:
            d["projects"] = [b if n == a else n for n in lst if n != b]
            if b not in d["projects"]:
                d["projects"].append(b)
            for m in d["marks"].values():
                if isinstance(m, dict) and m.get("project") == a:
                    m["project"] = b
            old = d["marks"].pop("proj:" + a, None)
            if isinstance(old, dict):  # merge the checklist and notes into the target
                new = d["marks"].setdefault("proj:" + b, {"notes": []})
                for f in ("todos", "notes"):
                    if old.get(f):
                        new[f] = (new.get(f) or []) + old[f]
    elif kind == "proj.del":
        n = _clean(op.get("name"), 60)
        d["projects"] = [x for x in lst if x != n]
        for m in d["marks"].values():
            if isinstance(m, dict) and m.get("project") == n:
                m.pop("project", None)


def apply(data_dir, ops, now):
    with locked(data_dir) as p:
        d = _read(p)
        for op in ops if isinstance(ops, list) else [ops]:
            if isinstance(op, dict):
                if op.get("op") == "import":
                    if d.get("migrated"):
                        continue
                    d["migrated"] = True
                if str(op.get("op", "")).startswith("proj."):
                    _proj(d, op)
                else:
                    _one(d["marks"], op, now)
        d["rev"] = int(d.get("rev", 0)) + 1
        _write(p, d)
        return d


def token(data_dir):
    p = paths(data_dir)["token"]
    try:
        with open(p) as fh:
            t = fh.read().strip()
        if len(t) >= 32:
            return t
    except FileNotFoundError:
        pass
    t = secrets.token_urlsafe(32)
    try:  # exclusive create: two first runs at once must agree on one token
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(p) as fh:
            got = fh.read().strip()
        if len(got) >= 32:
            return got
        fd = os.open(p, os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(t)
    return t
