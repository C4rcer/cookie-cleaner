"""Local test server for Dustpan's E2E test and screenshots (stdlib only).

Answers on any Host name, so Firefox can reach it as mail.example.com,
shop.example.co.uk, ... through the network.dns.localDomains pref. Every
request is logged with its host, path and Cookie header, which is how the
tests see whether a site still knows the browser.

Routes:
  /                a page that signs the browser in. It sets
                     sid_ZQXNAME=ZQXVALUE7731-<host>   HttpOnly, one day
                     sess=1                            session cookie
                     wide=1; Domain=<d>                only with ?d=<domain>
                     js=1                              from a script, one day
                   and says "Signed in" when the request already carried sid
  /embed?w=<host>  sets top=1 and embeds http://<host>:<port>/frame in an iframe
  /frame           sets fhttp=1 (HttpOnly) and, from a script, fjs=1
  /go?to=<url>     302 to <url>
  /plain           a page that sets nothing
  /demo/...        the pages used for the listing screenshots (tests/demo/*.html);
                   they set a few cookies too
  anything else    404
"""
import http.server
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DEMO = Path(__file__).resolve().parent / "demo"
SECRET_NAME = "sid_ZQXNAME"
SECRET_VALUE = "ZQXVALUE7731"
DAY = 86400


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.log = []

    def reset(self):
        with self.lock:
            self.log = []

    def requests(self, host=None, path=None):
        with self.lock:
            out = list(self.log)
        if host is not None:
            out = [r for r in out if r["host"] == host]
        if path is not None:
            out = [r for r in out if r["path"] == path]
        return out


STATE = State()


def page(title, body):
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{title}</title>"
            "<style>body{font:16px system-ui,sans-serif;margin:40px}</style></head>"
            f"<body>{body}</body></html>")


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def send(self, code, body="", cookies=(), headers=None):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for c in cookies:
            self.send_header("Set-Cookie", c)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        port = self.server.server_address[1]
        cookie = self.headers.get("Cookie") or ""
        with STATE.lock:
            STATE.log.append({"t": time.time(), "host": host, "path": u.path, "cookie": cookie})
        p = u.path
        if p == "/":
            known = SECRET_NAME + "=" in cookie
            cookies = [
                f"{SECRET_NAME}={SECRET_VALUE}-{host}; Max-Age={DAY}; Path=/; HttpOnly",
                "sess=1; Path=/",
            ]
            if q.get("d"):
                cookies.append(f"wide=1; Domain={q['d']}; Max-Age={DAY}; Path=/")
            state = "Signed in" if known else "Signed out"
            self.send(200, page(host, f"<h1>{host}</h1><p id=who>{state}</p>"
                                      f"<script>document.cookie='js=1; max-age={DAY}; path=/';</script>"), cookies)
        elif p == "/embed":
            w = q.get("w", "widget.tracker.test")
            self.send(200, page(host, f"<h1>{host}</h1><p>with an embedded widget</p>"
                                      f"<iframe id=w src='http://{w}:{port}/frame' width=300 height=80></iframe>"),
                      [f"top=1; Max-Age={DAY}; Path=/"])
        elif p == "/frame":
            self.send(200, page("frame", f"<p>widget on {host}</p><script>document.cookie='fjs=1; max-age={DAY}; path=/';</script>"),
                      [f"fhttp=1; Max-Age={DAY}; Path=/; HttpOnly"])
        elif p == "/go":
            self.send(302, "", headers={"Location": q.get("to", "/")})
        elif p == "/plain":
            self.send(200, page(host, f"<h1>{host}</h1><p>no cookies here</p>"))
        elif p.startswith("/demo/"):
            f = (DEMO / p[len("/demo/"):]).resolve()
            if f.is_file() and DEMO in f.parents:
                n = int(q.get("n", "6"))
                cookies = [f"session_id=demo-{host}; Max-Age={DAY}; Path=/; HttpOnly"]
                cookies += [f"pref{i}=v{i}; Max-Age={DAY}; Path=/" for i in range(max(0, n - 1))]
                self.send(200, f.read_text(encoding="utf-8").replace("{{host}}", host), cookies)
            else:
                self.send(404, page("Not found", "<h1>Not found</h1>"))
        else:
            self.send(404, page("Not found", "<h1>Not found</h1>"))


def start(port):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
