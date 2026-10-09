"""Reviewed LAN HTTP routes for the harness-authored mobile interface."""

import base64
import ipaddress
import json
import os
import re
import secrets
import threading
import time
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from local_agent.config import load_config
from local_agent.mobile import validate_request
from local_agent.mobile.activity import record
from local_agent.mobile.feedback import answer_feedback
from local_agent.mobile.jobs import Jobs, publish
from local_agent.mobile.markdown import display_thread
from local_agent.mobile.models import Models
from local_agent.mobile.recovery import recover_review
from local_agent.mobile.threads import Threads
from local_agent.mobile.tokens import DEFAULT_BASELINE, job_usage, summary
from local_agent.storage.database import Store


class PhoneServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self, root, agent_path, host="127.0.0.1", port=8767, runner=None, verifier_path=None
    ):
        address = ipaddress.IPv4Address(host)
        networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
        if not any(address in ipaddress.IPv4Network(net) for net in networks):
            raise ValueError(
                "Bind to your LAN IPv4 address or loopback, not a public/wildcard address"
            )
        if not 0 <= port <= 65535:
            raise ValueError("invalid port")
        config = load_config(Path(agent_path))
        if config.instructions_version != "phone-v1" or config.tools:
            raise ValueError(
                "phone-web requires phone-v1 instructions and an empty model tool list"
            )
        self.root, self.config = Path(root), config
        static = Path(__file__).with_name("static")
        self.asset_paths = {
            "/": static / "index.html",
            "/thread-controls.js": static / "thread-controls.js",
        }
        # Match the browser assets to this loaded server; edits require a restart.
        self.assets = {route: path.read_bytes() for route, path in self.asset_paths.items()}
        self.models = Models(config, verifier_path)
        self.pairing_code = secrets.token_urlsafe(16)
        self.sessions = {}
        self.session_lock = threading.Lock()
        super().__init__((str(address), port), PhoneHandler)
        try:
            self.jobs = Jobs(self.root, agent_path, config, runner=runner, on_result=self.finish)
            self.threads = Threads(self.root)
            self.migrate()
        except BaseException:
            if hasattr(self, "jobs"):
                self.jobs.close()
            super().server_close()
            raise
        self.hosts = {f"{address}:{self.server_port}"}
        if str(address) == "127.0.0.1":
            self.hosts.add(f"localhost:{self.server_port}")

    def migrate(self):
        """Import old successful jobs once; recover answers committed before a restart."""
        paths = (p for p in self.jobs.directory.iterdir() if re.fullmatch(r"[0-9a-f]{32}", p.name))
        for path in sorted(paths, key=lambda p: (self.jobs.get(p.name) or {}).get("created", 0)):
            job = self.jobs.get(path.name)
            if job and job.get("run_id") and "token_usage" not in job:
                job["token_usage"] = job_usage(self.root, job)
                publish(path / "status.json", job)
            if not job or job["status"] != "completed":
                if job and job.get("token_usage") and job.get("thread_id"):
                    self.record_usage(job)
                    recover_review(self.root, job, self.threads)
                    publish(path / "status.json", job)
                continue
            if not job.get("thread_id"):
                from local_agent.circuits.agent import read_evidence

                try:
                    request = validate_request(
                        json.loads(
                            read_evidence(
                                self.jobs.directory, path.name + "/request.json", 6 * 1024 * 1024
                            )
                        )
                    )
                except (ValueError, OSError):
                    continue
                thread_id = self.threads.create(request["question"][:160])
                messages = [{**m, "kind": "imported"} for m in request.get("history", [])]
                self.threads.update(thread_id, messages=messages)
                if request.get("image"):
                    from local_agent.mobile import image_mime

                    self.threads.update_image(
                        thread_id, request["image"], image_mime(base64.b64decode(request["image"]))
                    )
                job.update(
                    thread_id=thread_id,
                    question=request["question"],
                    kind="answer",
                    has_image=bool(request.get("image")),
                    provider=self.config.provider,
                )
                publish(path / "status.json", job)
            self.finish(job, trace=False)
            self.record_usage(job)
            publish(path / "status.json", job)

    def usage_baseline(self):
        # Keep the comparison stable when users change the paid reviewer.
        return DEFAULT_BASELINE

    def record_usage(self, job):
        if job.get("token_usage") and job.get("thread_id") and not job.get("usage_activity_run"):
            activity = record(
                self.root,
                job["thread_id"],
                "phone.usage_recorded",
                {
                    "job_id": job["job_id"],
                    "source_run_id": job.get("run_id"),
                    "token_usage": job["token_usage"],
                },
            )
            job["usage_activity_run"] = activity
            thread = self.threads.get(job["thread_id"])
            self.threads.update(
                job["thread_id"], activity_runs=thread.get("activity_runs", []) + [activity]
            )

    def finish(self, job, trace=True):
        if not job.get("thread_id"):
            return
        if job.get("run_id") and "token_usage" not in job:
            job["token_usage"] = job_usage(
                self.root, job, job.get("usage_baseline_model", DEFAULT_BASELINE)
            )
        with self.threads._lock:
            thread_id = job["thread_id"]
            thread = self.threads.get(thread_id)
            if trace and thread.get("pending_job") not in (None, job["job_id"]):
                raise ValueError("Job does not match the thread's pending request")
            if job["status"] == "completed":
                self.threads.add_exchange(
                    thread_id,
                    job["question"],
                    job["answer"],
                    job["job_id"],
                    job.get("run_id"),
                    job["model"],
                    job.get("kind", "answer"),
                )
                thread = self.threads.get(thread_id)
                for m in thread["messages"]:
                    if m.get("job_id") == job["job_id"]:
                        m.update(
                            provider=job.get("provider"), has_image=job.get("has_image", False)
                        )
                if trace:
                    activity = record(
                        self.root,
                        thread_id,
                        "phone.turn_linked",
                        {
                            "job_id": job["job_id"],
                            "source_run_id": job.get("run_id"),
                            "model": job["model"],
                            "provider": job.get("provider"),
                            "kind": job.get("kind", "answer"),
                            "memory_messages": job.get("memory_messages", 0),
                            "source_run_ids": job.get("source_run_ids", []),
                            "token_usage": job.get("token_usage"),
                        },
                    )
                    thread.setdefault("activity_runs", []).append(activity)
                    if job.get("token_usage"):
                        job["usage_activity_run"] = activity
                self.threads.update(
                    thread_id,
                    messages=thread["messages"],
                    activity_runs=thread.get("activity_runs", []),
                )
            if trace:
                self.record_usage(job)
            thread = self.threads.get(thread_id)
            if thread.get("pending_job") == job["job_id"]:
                self.threads.update(thread_id, pending_job=None)

    def submit_thread(self, thread_id, payload, kind="answer"):
        allowed = {"question", "image", "model_id"} if kind == "answer" else {"model_id"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValueError("Unexpected thread request fields")
        if "image" in payload and (not isinstance(payload["image"], str) or not payload["image"]):
            raise ValueError("image must be a non-empty base64 string")
        with self.threads._lock:
            thread = self.threads.get(thread_id)
            pending = self.jobs.get(thread.get("pending_job"))
            if pending and pending["status"] in {"queued", "running"}:
                raise ValueError("This thread already has a pending question")
            if len(thread["messages"]) >= 200:
                raise ValueError("Thread is full; start a new chat")
            image = payload.get("image", thread.get("image"))
            history = self.threads.history(thread_id)
            if kind == "review":
                if not thread["messages"]:
                    raise ValueError("Ask a question before requesting a review")
                cfg = self.models.select_reviewer(payload.get("model_id"))
                if not os.environ.get(cfg.api_key_env):
                    raise ValueError("Set " + cfg.api_key_env + " in the server's launch terminal")
                question = (
                    "Independently review this circuit conversation and its latest answer/netlist. "
                    "Check the supplied schematic when available. List concrete errors, uncertain connections, "
                    "and corrections with evidence. Do not treat prior answers as truth. Distinguish schematic "
                    "transcription from electrical plausibility. Do not claim simulation or verified correctness. "
                    "This is an advisory review, not electrical verification."
                )
            elif kind == "netlist":
                if not any(
                    m.get("role") == "assistant"
                    and m.get("has_image")
                    and m.get("kind") == "answer"
                    for m in thread["messages"]
                ):
                    raise ValueError(
                        "Ask a vision model about the schematic before netlist inference"
                    )
                image = None
                cfg, _ = self.models.select(payload.get("model_id"), has_image=False)
                question = (
                    "Using only the schematic observations and conversation supplied, infer a partial "
                    "SPICE netlist in a code block. Identify the evidence for each component and connection. "
                    "Comment out uncertain connections or models; do not invent topology or values. "
                    "Include an uncertainty list and needed measurements. Mark this an UNVERIFIED DRAFT. "
                    "You cannot see the image in this stage; rely only on recorded observations."
                )
                observation = next(
                    m
                    for m in reversed(thread["messages"])
                    if m.get("role") == "assistant"
                    and m.get("has_image")
                    and m.get("kind") == "answer"
                )
                question += (
                    "\nRecorded VLM observations (untrusted, may contain errors):\n"
                    + observation["content"][:7000]
                )
            else:
                question = payload.get("question")
                cfg, _ = self.models.select(payload.get("model_id"), has_image=bool(image))
            request = {"question": question, "history": history}
            if image:
                request["image"] = image
            request = validate_request(request)
            if "image" in payload:
                from local_agent.mobile import image_mime

                self.threads.update_image(thread_id, image, image_mime(base64.b64decode(image)))
            reused = thread["messages"][-len(history) :] if history else []
            source_runs = [m["run_id"] for m in reused if m.get("run_id")]
            if kind == "netlist" and observation.get("run_id") not in source_runs:
                if observation.get("run_id"):
                    source_runs.append(observation["run_id"])
            job_id = self.jobs.submit(
                request,
                config=cfg,
                metadata={
                    "thread_id": thread_id,
                    "question": question,
                    "kind": kind,
                    "has_image": bool(image),
                    "memory_messages": len(history),
                    "source_run_ids": source_runs,
                    "usage_baseline_model": self.usage_baseline(),
                },
            )
            self.threads.update(thread_id, pending_job=job_id)
            return job_id

    def thread_events(self, thread_id):
        thread = self.threads.get(thread_id)
        ids = {m["run_id"] for m in thread["messages"] if m.get("run_id")}
        ids.update(thread.get("activity_runs", []))
        store = Store(self.root, readonly=True)
        try:
            events = []
            for run_id in ids:
                events.extend(e.model_dump(mode="json") for e in store.events(run_id))
            return sorted(events, key=lambda e: (e["timestamp_utc"], e["run_id"], e["run_seq"]))
        finally:
            store.close()

    def server_close(self):
        super().server_close()
        if hasattr(self, "jobs"):
            self.jobs.close()

    def restart_required(self):
        try:
            return any(
                path.read_bytes() != self.assets[route] for route, path in self.asset_paths.items()
            )
        except OSError:
            return True


class PhoneHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_):
        pass

    def respond(self, status, value, *, nonce="", mime="application/json", cookie=None):
        body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; connect-src 'self'; "
            "style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'; "
            f"base-uri 'none'; script-src 'nonce-{nonce}'",
        )
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(body)

    def error(self, status, message):
        self.respond(status, {"error": message})

    def boundary(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in self.server.hosts:
            self.error(403, "unexpected Host")
            return False
        origin = self.headers.get("Origin")
        if (
            (origin and origin != "http://" + hosts[0])
            or (self.command == "POST" and not origin)
            or self.headers.get("Sec-Fetch-Site") == "cross-site"
        ):
            self.error(403, "unexpected Origin or cross-site request")
            return False
        return True

    def authenticated(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookies.get("phone_session")
            if not token:
                return False
            with self.server.session_lock:
                sessions = list(self.server.sessions.items())
            return any(
                expiry > time.time()
                and secrets.compare_digest(token.value.encode(), valid.encode())
                for valid, expiry in sessions
            )
        except (ValueError, TypeError, CookieError):
            return False

    def do_GET(self):
        if not self.boundary():
            return
        path = urlparse(self.path).path
        if path == "/thread-controls.js":
            script = self.server.assets[path]
            self.respond(200, script, mime="application/javascript")
            return
        if path == "/":
            nonce = secrets.token_hex(16)
            html = self.server.assets[path].decode()
            self.respond(
                200, html.replace("NONCE_VALUE", nonce).encode(), nonce=nonce, mime="text/html"
            )
            return
        if not self.authenticated():
            self.error(401, "Pair with the code printed on the computer first.")
            return
        try:
            if path == "/api/info":
                self.respond(
                    200,
                    {
                        "model": self.server.config.model,
                        "provider": self.server.config.provider,
                        "auth": "pairing-code",
                        "owner": "local-owner",
                        "restart_required": self.server.restart_required(),
                    },
                )
            elif path == "/api/models":
                self.respond(200, self.server.models.catalog())
            elif path == "/api/threads":
                self.respond(200, self.server.threads.recent())
            elif path == "/api/usage":
                self.respond(200, summary(self.server.jobs.recent(limit=1000)))
            elif match := re.fullmatch(r"/api/threads/([0-9a-f]{32})/usage", path):
                self.server.threads.get(match[1])
                self.respond(200, summary(self.server.jobs.recent(limit=1000), match[1]))
            elif match := re.fullmatch(r"/api/threads/([0-9a-f]{32})(/events)?", path):
                self.respond(
                    200,
                    self.server.thread_events(match[1])
                    if match[2]
                    else display_thread(self.server.threads.get(match[1])),
                )
            elif path == "/api/jobs":
                self.respond(200, self.server.jobs.recent())
            elif match := re.fullmatch(r"/api/jobs/([0-9a-f]{32})(/events)?", path):
                job = self.server.jobs.get(match[1])
                if not job:
                    self.error(404, "Job not found")
                elif match[2]:
                    if not job.get("run_id"):
                        self.error(404, "No run trace is available for this job")
                        return
                    store = Store(self.server.root, readonly=True)
                    try:
                        store.run(job["run_id"])
                        self.respond(
                            200, [e.model_dump(mode="json") for e in store.events(job["run_id"])]
                        )
                    finally:
                        store.close()
                else:
                    self.respond(200, job)
            else:
                self.error(404, "Route not found")
        except (ValueError, OSError) as exc:
            self.error(404, str(exc))

    def do_POST(self):
        if not self.boundary():
            return
        path = urlparse(self.path).path
        if path != "/api/login" and not self.authenticated():
            self.error(401, "Pair with the code printed on the computer first.")
            return
        if self.headers.get("Transfer-Encoding"):
            self.error(400, "Transfer-Encoding is not supported")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if (
            len(lengths) != 1
            or len(lengths[0]) > 8
            or not lengths[0].isascii()
            or not lengths[0].isdigit()
        ):
            self.error(411, "A single numeric Content-Length is required")
            return
        length = int(lengths[0])
        if not 0 < length <= 6 * 1024 * 1024:
            self.error(413, "Request exceeds the 6 MiB limit")
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self.error(415, "Send application/json")
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete request body")
            request = json.loads(body)
            if path == "/api/login":
                if (
                    not isinstance(request, dict)
                    or set(request) != {"code"}
                    or not isinstance(request["code"], str)
                ):
                    raise ValueError("Login requires a pairing code")
                if not secrets.compare_digest(
                    request["code"].encode(), self.server.pairing_code.encode()
                ):
                    self.error(401, "Incorrect pairing code")
                    return
                token = secrets.token_urlsafe(32)
                with self.server.session_lock:
                    if len(self.server.sessions) >= 16:
                        self.server.sessions.pop(next(iter(self.server.sessions)))
                    self.server.sessions[token] = time.time() + 86400
                self.respond(
                    200,
                    {"ok": True},
                    cookie=f"phone_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400",
                )
            elif path == "/api/ask":
                request = validate_request(request)
                try:
                    job_id = self.server.jobs.submit(request)
                except RuntimeError as exc:
                    self.error(429, str(exc))
                    return
                self.respond(202, {"job_id": job_id})
            elif path == "/api/models/refresh":
                if request != {}:
                    raise ValueError("Model refresh takes no fields")
                self.respond(200, self.server.models.catalog(refresh=True))
            elif path == "/api/threads":
                if not isinstance(request, dict) or set(request) - {"title"}:
                    raise ValueError("Thread creation permits only title")
                thread_id = self.server.threads.create(request.get("title", "New chat"))
                self.respond(201, {"thread_id": thread_id})
            elif match := re.fullmatch(
                r"/api/threads/([0-9a-f]{32})/answers/([0-9a-f]{32})/feedback", path
            ):
                if not isinstance(request, dict) or set(request) != {"vote"}:
                    raise ValueError("Answer feedback requires only vote")
                thread = answer_feedback(
                    self.server.root, self.server.threads, match[1], match[2], request["vote"]
                )
                self.respond(200, display_thread(thread))
            elif match := re.fullmatch(
                r"/api/threads/([0-9a-f]{32})/(ask|netlist|review|feedback)", path
            ):
                thread_id, operation = match.groups()
                if operation == "feedback":
                    if not isinstance(request, dict) or set(request) != {"vote"}:
                        raise ValueError("Feedback requires vote")
                    vote = request["vote"]
                    if vote not in (None, "up", "down"):
                        raise ValueError("Feedback must be up, down or null")
                    with self.server.threads._lock:
                        thread = self.server.threads.get(thread_id)
                        if thread.get("feedback") == vote:
                            self.respond(200, thread)
                            return
                        run_id = record(
                            self.server.root,
                            thread_id,
                            "phone.feedback",
                            {
                                "vote": vote,
                                "owner": thread["owner"],
                                "source_run_ids": [
                                    m["run_id"] for m in thread["messages"] if m.get("run_id")
                                ],
                            },
                        )
                        thread = self.server.threads.update(
                            thread_id,
                            feedback=vote,
                            activity_runs=thread.get("activity_runs", []) + [run_id],
                        )
                    self.respond(200, thread)
                else:
                    try:
                        job_id = self.server.submit_thread(
                            thread_id, request, "answer" if operation == "ask" else operation
                        )
                    except RuntimeError as exc:
                        self.error(429, str(exc))
                        return
                    self.respond(202, {"job_id": job_id, "thread_id": thread_id})
            else:
                self.error(404, "Route not found")
        except (ValueError, OSError) as exc:
            self.error(400, str(exc))


def serve(root, agent_path, host="127.0.0.1", port=8767, verifier_path=None):
    with PhoneServer(root, agent_path, host, port, verifier_path=verifier_path) as server:
        print(
            f"Phone interface: http://{host}:{server.server_port}\nPairing code: {server.pairing_code}",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print(
                "Stopping phone interface; waiting for the active question to finish...", flush=True
            )
