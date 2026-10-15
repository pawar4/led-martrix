#!/usr/bin/env python3
"""HTTP front end for natural-language control of the matrix (for Home Assistant, curl, scripts).

  python serve.py                                             # 127.0.0.1:8099, edits matrix.json (asks Claude via the Claude Code CLI)
  MATRIX_TOKEN=secret python serve.py --host 0.0.0.0          # reachable from the LAN / a container

  POST /ask   {"query": "show the weather", "dry_run": false}  -> {reply, changed, applied, model}
  POST /undo                                                   -> same shape, restores the previous model
  GET  /model                                                  -> the current global model
  GET  /health                                                 -> {"ok": true}

  python serve.py --once "show the weather" [--apply]   # one request, print the result, exit

If MATRIX_TOKEN is set, every request needs `Authorization: Bearer <token>`. Run `run.py` alongside; it reloads
the model file this service writes. See matrix_ui/assistant.py.
"""
import argparse
import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from matrix_ui.assistant import Assistant, AskError

log = logging.getLogger("serve")
MAX_BODY = 16 * 1024


def make_handler(assistant, token=None):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self):
            if not token:
                return True
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied, f"Bearer {token}")

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
            if self.path == "/health":
                return self._send(200, {"ok": True})
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            if self.path == "/model":
                return self._send(200, assistant.read())
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            try:
                body = self._body()
                if self.path == "/ask":
                    query = body.get("query")
                    if not isinstance(query, str) or not query.strip():
                        return self._send(400, {"error": "\"query\" must be a non-empty string"})
                    result = assistant.ask(query.strip(), dry_run=bool(body.get("dry_run")))
                    log.info("ask %r -> %s", query, result["reply"])
                    return self._send(200, result)
                if self.path == "/undo":
                    return self._send(200, assistant.undo())
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except AskError as e:
                return self._send(422, {"error": str(e)})
            self._send(404, {"error": "not found"})

        def log_message(self, fmt, *args):
            log.debug("%s " + fmt, self.address_string(), *args)

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="matrix.json", help="global model file the runner watches (default: matrix.json)")
    ap.add_argument("--screens", default="screens")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--model", help="Claude model id (default: $MATRIX_AI_MODEL or claude-opus-5-5)")
    ap.add_argument("--once", metavar="QUERY", help="run one request, print the result and exit (a dry run unless --apply)")
    ap.add_argument("--apply", action="store_true", help="with --once, write the model file")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)

    token = os.environ.get("MATRIX_TOKEN")
    if not token and args.host not in ("127.0.0.1", "localhost", "::1"):
        ap.error("set MATRIX_TOKEN when listening on a non-loopback address")
    assistant = Assistant(args.config, args.screens, model=args.model)
    if args.once:
        try:
            result = assistant.ask(args.once, dry_run=not args.apply)
        except AskError as e:
            raise SystemExit(f"error: {e}")
        print(json.dumps(result, indent=2))
        return
    server = ThreadingHTTPServer((args.host, args.port), make_handler(assistant, token))
    log.info("listening on %s:%d, model %s", args.host, args.port, assistant.model_name)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
