"""The web board's local server: 127.0.0.1 only, token-guarded.

  server.py ensure <data dir> [port]   start one if none of ours answers; print the URL
  server.py serve  <data dir> [port]   run in the foreground (what ensure starts)

Every /api route needs the X-Token header (the token file is 0600 in the data
dir); Host must be this address and a present Origin this origin, so a web
page elsewhere can neither read nor change anything. /api/open takes a session
id from the last scan and builds the claude:// URL itself.
"""
import fcntl, hmac, json, os, re, subprocess, sys, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import history  # noqa: E402
import outbox  # noqa: E402
import scan as scanner  # noqa: E402
import store  # noqa: E402

VERSION = "0.8.2"
PORT = 47811
WEB = os.path.join(os.path.dirname(HERE), "web", "index.html")
ID = re.compile(r"^[A-Za-z0-9_-]{4,120}$")


def health(port, tok):
    """Our server's health answer, {"foreign": True} when another copy holds the port, or None."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health", headers={"X-Token": tok, "Host": f"127.0.0.1:{port}"})
        with urllib.request.urlopen(req, timeout=1.5) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"foreign": True} if e.code in (401, 421) else None
    except Exception:
        return None


def ensure(data_dir, port):
    tok = store.token(data_dir)
    h = health(port, tok)
    if h and h.get("foreign"):
        print(json.dumps({"error": f"Another copy of Session Board already runs a board on port {port}. Remove the other copy (or restart the Claude app) and try again."}))
        sys.exit(1)
    if h and h.get("version") != VERSION:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"{}", method="POST",
                                         headers={"X-Token": tok, "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=1.5).read()
        except Exception:
            pass
        time.sleep(0.6)
        h = None
    if not h:
        log = open(os.path.join(data_dir, "server.log"), "a")
        subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "serve", data_dir, str(port)],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True)
        for _ in range(40):
            time.sleep(0.15)
            h = health(port, tok)
            if h:
                break
    if not h:
        print(json.dumps({"error": f"The board server did not start (port {port} may be in use). Details: {data_dir}/server.log"}))
        sys.exit(1)
    print(json.dumps({"url": f"http://127.0.0.1:{port}/#t={tok}", "version": h.get("version")}))


class State:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.lock = threading.Lock()
        self.sessions, self.at, self.busy = [], 0, False

    def _scan(self):
        try:
            sessions, _ = scanner.scan(self.data_dir)
            with self.lock:
                self.sessions, self.at = sessions, time.time()
        finally:
            with self.lock:
                self.busy = False

    def sessions_fresh(self, max_age=4.0):
        """The last scan; a stale one is refreshed in the background so no request waits on it."""
        with self.lock:
            fresh = time.time() - self.at <= max_age
            first = self.at == 0
            start = not fresh and not self.busy
            if start:
                self.busy = True
        if start and first:
            self._scan()  # nothing to show yet: the very first scan is waited for
        elif start:
            threading.Thread(target=self._scan, daemon=True).start()
        with self.lock:
            return self.sessions


def serve(data_dir, port):
    # One server per data dir: the lifetime lock is held until the process ends.
    lf = os.open(os.path.join(data_dir, "server.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    tok = store.token(data_dir)
    st = State(data_dir)
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{h}" for h in hosts}

    class H(BaseHTTPRequestHandler):
        server_version = "session-board"

        def log_message(self, *a):  # no request logs: URLs could carry the token
            pass

        def send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if ctype.startswith("text/html"):
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def guard(self, api):
            if self.headers.get("Host") not in hosts:
                return self.send(421, {"error": "host"}) or False
            o = self.headers.get("Origin")
            if o is not None and o not in origins:
                return self.send(403, {"error": "origin"}) or False
            if api and not hmac.compare_digest(self.headers.get("X-Token", ""), tok):
                return self.send(401, {"error": "token"}) or False
            return True

        def body(self):
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return None
            n = int(self.headers.get("Content-Length") or 0)
            if n > 200000:
                return None
            try:
                d = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return None
            return d if isinstance(d, dict) else None

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                if not self.guard(False):
                    return
                with open(WEB, "rb") as fh:
                    return self.send(200, fh.read(), "text/html; charset=utf-8")
            if not self.guard(True):
                return
            if path == "/api/health":
                return self.send(200, {"ok": True, "version": VERSION})
            if path == "/api/sent":
                r = outbox.result(data_dir, self.path.partition("key=")[2].split("&")[0])
                return self.send(200 if r else 400, r or {"error": "unknown send"})
            if path == "/api/msgs":
                # read on demand from the session's own transcript; nothing is kept
                sid = self.path.partition("id=")[2].split("&")[0]
                hit = next((x for x in st.sessions_fresh(60) if x["id"] == sid), None) if ID.match(sid) else None
                if not hit:
                    return self.send(400, {"error": "unknown session"})
                try:
                    return self.send(200, {"msgs": history.last_messages(hit.get("cli") or [])})
                except Exception as e:
                    return self.send(500, {"error": f"Could not read messages: {e}"})
            if path == "/api/state":
                try:
                    sessions = st.sessions_fresh()
                    m = store.load(data_dir)
                    return self.send(200, {"sessions": sessions, "marks": m["marks"], "rev": m["rev"], "projects": m.get("projects", []), "now": int(time.time() * 1000)})
                except Exception as e:
                    return self.send(500, {"error": f"Could not read sessions: {e}"})
            self.send(404, {"error": "not found"})

        def do_POST(self):
            if not self.guard(True):
                return
            b = self.body()
            if b is None:
                return self.send(415, {"error": "json"})
            path = self.path.split("?")[0]
            if path == "/api/mark":
                try:
                    d = store.apply(data_dir, b.get("ops") or [], int(time.time() * 1000))
                except Exception as e:
                    return self.send(400, {"error": f"Could not save: {e}"})
                return self.send(200, {"marks": d["marks"], "rev": d["rev"], "projects": d.get("projects", [])})
            if path == "/api/send":
                sid, text = str(b.get("id") or ""), str(b.get("text") or "").strip()
                hit = next((x for x in st.sessions_fresh(60) if x["id"] == sid), None) if ID.match(sid) else None
                if not hit or not hit.get("cli"):
                    return self.send(400, {"error": "unknown session"})
                if not text or len(text) > 8000:
                    return self.send(400, {"error": "message is empty or too long"})
                return self.send(200, {"key": outbox.queue(data_dir, sid, hit["cli"], hit.get("title") or "", text)})
            if path == "/api/open":
                sid = str(b.get("id") or "")
                if not ID.match(sid) or sid not in {s["id"] for s in st.sessions_fresh(60)}:
                    return self.send(400, {"error": "unknown session"})
                r = subprocess.run(["open", f"claude://claude.ai/epitaxy/{sid}"], capture_output=True, timeout=10)
                return self.send(200 if r.returncode == 0 else 500, {"ok": r.returncode == 0})
            if path == "/api/shutdown":
                self.send(200, {"ok": True})
                threading.Thread(target=httpd.shutdown, daemon=True).start()
                return
            self.send(404, {"error": "not found"})

    httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
    httpd.daemon_threads = True
    httpd.serve_forever()


if __name__ == "__main__":
    cmd, data_dir = sys.argv[1], sys.argv[2]
    port = int(sys.argv[3]) if len(sys.argv) > 3 else PORT
    os.makedirs(data_dir, mode=0o700, exist_ok=True)
    if cmd == "ensure":
        ensure(data_dir, port)
    elif cmd == "serve":
        serve(data_dir, port)
