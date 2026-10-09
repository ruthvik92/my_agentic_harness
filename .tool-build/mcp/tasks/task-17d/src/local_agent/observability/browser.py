"""Loopback-only, read-only browser traces. No model/executor dispatch routes."""

import json
import re
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from local_agent.observability.audit import audit
from local_agent.observability.sources import SourceCatalog
from local_agent.storage.bundles import roots
from local_agent.storage.database import Store

MAX_BODY = 8192


class TraceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, port=8765):
        self.data_root = Path(root).expanduser().resolve()
        self.catalog = SourceCatalog(root)
        super().__init__(("127.0.0.1", port), TraceHandler)


class TraceHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, data, mime="application/json", nonce=None):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; connect-src 'self'; style-src 'unsafe-inline'; "
            f"script-src 'nonce-{nonce or ''}'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _allowed_hosts(self):
        port = self.server.server_port
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _check_access(self, require_origin=False):
        """Shared Host/Origin/Sec-Fetch-Site checks. Returns True if allowed."""
        hosts = self._allowed_hosts()
        if self.headers.get("Host") not in hosts:
            self.respond(403, {"error": "unexpected Host"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in hosts}:
            self.respond(403, {"error": "unexpected Origin"})
            return False
        if require_origin and not origin:
            self.respond(403, {"error": "missing Origin"})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.respond(403, {"error": "cross-site access denied"})
            return False
        return True

    def _resolve_source(self, query):
        """Resolve ?source=SOURCE_ID to a catalog entry, or default to data_root."""
        catalog = self.server.catalog
        sources = catalog.sources()
        source_id = None
        if query:
            parsed = parse_qs(query)
            values = parsed.get("source")
            if values:
                source_id = values[0]
        if source_id is None:
            for source in sources:
                if Path(source["root"]) == self.server.data_root:
                    return source
            return sources[0] if sources else None
        for source in sources:
            if source["id"] == source_id:
                return source
        return None

    def do_GET(self):
        if not self._check_access():
            return
        path = urlparse(self.path).path
        if path == "/":
            nonce = secrets.token_hex(16)
            html = (
                Path(__file__).with_name("trace_ui.html").read_text().replace("NONCE_VALUE", nonce)
            )
            self.respond(200, html.encode(), "text/html", nonce)
            return
        if path == "/api/sources":
            try:
                self.respond(200, self.server.catalog.sources())
            except (ValueError, OSError, sqlite3.Error) as exc:
                self.respond(500, {"error": str(exc)})
            return
        if path == "/api/runs":
            try:
                self.respond(200, self.server.catalog.list_runs())
            except (ValueError, OSError, sqlite3.Error) as exc:
                self.respond(500, {"error": str(exc)})
            return
        match = re.fullmatch(
            r"/api/runs/(run_[0-9a-f]{32})(?:/(audit|evidence/[0-9a-f]{64}))?", path
        )
        if not match:
            self.respond(404, {"error": "route not found"})
            return
        run_id, action = match.groups()
        source = self._resolve_source(urlparse(self.path).query)
        if source is None:
            self.respond(404, {"error": "unknown source"})
            return
        store = None
        try:
            store = Store(Path(source["root"]), readonly=True)
            store.run(run_id)
            if action == "audit":
                self.respond(200, audit(store, run_id))
            elif action and action.startswith("evidence/"):
                ref = "blob://" + action.split("/")[1]
                refs, _ = roots(store, run_id)
                if ref not in refs:
                    self.respond(403, {"error": "evidence is not part of this run"})
                    return
                raw = store.blobs.read(ref)
                # Always text/JSON, never render captured HTML/scripts.
                self.respond(
                    200, {"ref": ref, "bytes": len(raw), "content": raw.decode(errors="replace")}
                )
            else:
                self.respond(
                    200,
                    {
                        "run": dict(store.run(run_id)),
                        "events": [e.model_dump(mode="json") for e in store.events(run_id)],
                    },
                )
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.respond(404, {"error": str(exc)})
        finally:
            if store:
                store.close()

    def do_POST(self):
        if not self._check_access(require_origin=True):
            return
        path = urlparse(self.path).path
        if path != "/api/sources":
            self.respond(404, {"error": "route not found"})
            return
        ctype = self.headers.get("Content-Type", "")
        base = ctype.split(";")[0].strip().lower()
        if base != "application/json":
            self.respond(400, {"error": "Content-Type must be application/json"})
            return
        length_raw = self.headers.get("Content-Length")
        try:
            length = int(length_raw)
        except (TypeError, ValueError):
            self.respond(400, {"error": "invalid Content-Length"})
            return
        if length < 1:
            self.respond(400, {"error": "invalid Content-Length"})
            return
        if length > MAX_BODY:
            self.respond(413, {"error": "body too large"})
            return
        try:
            body = self.rfile.read(length)
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.respond(400, {"error": f"malformed JSON: {exc}"})
            return
        if not isinstance(payload, dict):
            self.respond(400, {"error": "body must be a JSON object"})
            return
        location = payload.get("location")
        if not isinstance(location, str) or not location:
            self.respond(400, {"error": "location must be a non-empty string"})
            return
        project = payload.get("project", "")
        if not isinstance(project, str):
            self.respond(400, {"error": "project must be a string"})
            return
        try:
            source = self.server.catalog.add(location, project)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.respond(400, {"error": str(exc)})
            return
        self.respond(201, source)


def serve(root, port=8765):
    with TraceServer(root, port) as server:
        print(f"Trace viewer: http://127.0.0.1:{server.server_port} (read-only)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
