#!/usr/bin/env python3
"""HTTP front end for controlling the matrix: a web page, and a JSON API for curl and scripts. Local network only.

  python serve.py                                             # 127.0.0.1:8099, edits matrix.json; open http://localhost:8099/
  python serve.py --host 0.0.0.0                              # reachable from the LAN (and a container), no password
  MATRIX_TOKEN=secret python serve.py --host 0.0.0.0          # same, but every request needs the token
  python serve.py --host 0.0.0.0 --port 8099 --port 80        # several ports: the first must bind, the rest are best-effort

  GET   /                                                      -> the web page (web/index.html); never needs the token
  PATCH /model {"brightness": 20, "screen": null}              -> {reply, changed, applied, model}; merges top-level keys, null removes one
  POST  /undo                                                  -> same shape, restores the previous model
  GET   /model                                                 -> the current global model
  GET   /screens                                               -> {screen name: its source specs}
  GET   /cron?at=<cron expr>&count=3                           -> {"next": ["Thu Oct 15 14:15", ...]} in the Pi's local time
  GET   /health                                                -> {"ok": true}

Local network only, whatever the bind address: a request is refused (403) unless it comes from a loopback, private or
link-local address, carries no proxy headers (a tunnel on the Pi itself), and its Host header is an IP address or a local
name (see `is_local_host`), so neither a port forward, a tunnel nor a web page you visit (DNS rebinding) can reach it.
There is no password unless MATRIX_TOKEN is set; then every request but the page and /health needs
`Authorization: Bearer <token>`. Writes (POST, PATCH) from a browser page on another origin are refused too. Run
`run.py` alongside; it reloads the model file this service writes. See matrix_ui/model_store.py.
"""
import argparse
import hmac
import ipaddress
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from matrix_ui.model_store import ModelError, ModelStore, describe_screens
from matrix_ui.cron import Cron

log = logging.getLogger("serve")
MAX_BODY = 16 * 1024
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")
LOCAL_SUFFIXES = (".local", ".lan", ".localdomain", ".home.arpa", ".internal")    # names a router or mDNS gives a LAN host
# Added by tunnels (cloudflared, ngrok, tailscale serve) and reverse proxies running on the Pi, whose connections
# arrive from 127.0.0.1. A local client has no reason to send them.
PROXY_HEADERS = ("Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP", "CF-Connecting-IP", "True-Client-IP")
# The page is one file with inline script and style. This lets it talk to this service only, and load nothing else.
PAGE_POLICY = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
               "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def is_local_address(addr):
    """True for a loopback, private (10/8, 172.16/12, 192.168/16, fc00::/7) or link-local address: one that can't be on
    the internet. Carrier-grade NAT space (100.64/10, which Tailscale uses) is not local."""
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])      # fe80::1%eth0 carries its interface
    except ValueError:
        return False
    ip = getattr(ip, "ipv4_mapped", None) or ip            # ::ffff:192.168.1.5 is the IPv4 address
    return ip.is_loopback or ip.is_private or ip.is_link_local


def is_local_host(host_header, extra=()):
    """True when the Host header is an IP address, `localhost`, a one-word name (`raspberrypi`), a name ending in a local
    suffix (`raspberrypi.local`), or one of `extra`. A page on the internet that rebinds its own domain to the Pi's
    address makes the browser send that domain here, so it fails this check."""
    try:
        name = urlsplit("//" + (host_header or "")).hostname
    except ValueError:
        return False
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    name = name.rstrip(".")
    return "." not in name or name.endswith(LOCAL_SUFFIXES) or name in extra


def next_firings(expr, count=3, now=None):
    """The next `count` firings of a cron expression as local-time labels. Raises ValueError for a bad expression."""
    cron, t, found = Cron(expr), now if now is not None else time.time(), []
    while len(found) < count and (t := cron.next(t)) is not None:
        found.append(time.localtime(t))
    fmt = "%a %b %d %H:%M:%S" if any(lt.tm_sec for lt in found) else "%a %b %d %H:%M"
    return [time.strftime(fmt, lt) for lt in found]


def make_handler(store, token=None, extra_hosts=()):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, content_type="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if content_type.startswith("text/html"):
                self.send_header("Content-Security-Policy", PAGE_POLICY)
            self.end_headers()
            self.wfile.write(data)

        def _remote(self):
            """Refuse (and say so) a request from outside the local network, through a proxy or tunnel, or addressed
            to a non-local name."""
            if not is_local_address(self.client_address[0]):
                log.warning("refused %s: not a local network address", self.client_address[0])
                self._send(403, {"error": "this service only answers the local network"})
                return True
            if any(self.headers.get(h) is not None for h in PROXY_HEADERS):
                log.warning("refused %s: the request came through a proxy or tunnel", self.client_address[0])
                self._send(403, {"error": "this service doesn't answer through a proxy or tunnel"})
                return True
            host = self.headers.get("Host")
            if not is_local_host(host, extra_hosts):
                log.warning("refused %s: host name %r isn't local", self.client_address[0], host)
                self._send(403, {"error": "this service only answers to an IP address or a local name "
                                          "(like raspberrypi.local); to allow another name, list it in MATRIX_ALLOWED_HOSTS"})
                return True
            return False

        def _authorized(self):
            if not token:
                return True
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied, f"Bearer {token}")

        def _same_origin(self):
            """False for a browser request made by a page on another origin. Requests without an Origin header
            (curl, scripts) are fine; so is the page this service serves."""
            origin = self.headers.get("Origin")
            return origin is None or urlsplit(origin).netloc.lower() == (self.headers.get("Host") or "").lower()

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("request body too large")
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            return body

        def do_GET(self):
            if self._remote():
                return
            url = urlsplit(self.path)
            if url.path == "/health":
                return self._send(200, {"ok": True})
            if url.path in ("/", "/index.html"):
                try:
                    with open(PAGE, "rb") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8")
                except OSError:
                    return self._send(404, {"error": "web/index.html is missing"})
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            if url.path == "/model":
                return self._send(200, store.read())
            if url.path == "/screens":
                return self._send(200, describe_screens(store.screens_dir))
            if url.path == "/cron":
                query = parse_qs(url.query)
                count = query.get("count", ["3"])[0]
                count = min(max(int(count), 1), 10) if count.isdigit() else 3
                try:
                    return self._send(200, {"next": next_firings(query.get("at", [""])[0], count)})
                except ValueError:
                    return self._send(400, {"error": "not a cron expression (5 fields, or 6 with leading seconds)"})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self._remote():
                return
            if not self._same_origin():
                return self._send(403, {"error": "cross-origin request refused"})
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            try:
                self._body()
                if self.path == "/undo":
                    return self._send(200, store.undo())
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except ModelError as e:
                return self._send(422, {"error": str(e)})
            self._send(404, {"error": "not found"})

        def do_PATCH(self):
            if self._remote():
                return
            if not self._same_origin():
                return self._send(403, {"error": "cross-origin request refused"})
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            if urlsplit(self.path).path != "/model":
                return self._send(404, {"error": "not found"})
            try:
                result = store.update(self._body())
                log.info("update -> %s", result["reply"])
                return self._send(200, result)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except ModelError as e:
                return self._send(422, {"error": str(e)})

        def log_message(self, fmt, *args):
            log.debug("%s " + fmt, self.address_string(), *args)

    return Handler


def listen(host, ports, handler):
    """Servers for `ports`: the first must bind (an OSError otherwise); the others are skipped with a warning if
    they can't, such as port 80 without permission or already in use."""
    servers = [ThreadingHTTPServer((host, ports[0]), handler)]
    for port in ports[1:]:
        try:
            servers.append(ThreadingHTTPServer((host, port), handler))
        except OSError as e:
            log.warning("not listening on port %d: %s", port, e)
    return servers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="matrix.json", help="global model file the runner watches (default: matrix.json)")
    ap.add_argument("--screens", default="screens")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, action="append",
                    help="port to listen on (default 8099); repeat for more: the first must bind, the others are best-effort")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)

    token = os.environ.get("MATRIX_TOKEN")      # optional: without it anyone on the local network can use it
    extra_hosts = tuple(h.strip().lower() for h in os.environ.get("MATRIX_ALLOWED_HOSTS", "").split(",") if h.strip())
    store = ModelStore(args.config, args.screens)
    server, *extras = listen(args.host, args.port or [8099], make_handler(store, token, extra_hosts))
    for extra in extras:
        threading.Thread(target=extra.serve_forever, daemon=True).start()
    log.info("listening on %s:%s", args.host, ", ".join(str(s.server_port) for s in [server, *extras]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
