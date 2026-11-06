"""Real Firefox UI acceptance with synthetic controller results and no inference.

Run with uv run --locked python scripts/check_completion_loop_browser.py.
Uses a private temporary Git repository and browser state; does not touch user jobs.
"""

import asyncio
import json
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from local_agent.mobile.jobs import publish
from local_agent.mobile.web import BrowserServer
from local_agent.runtime.loop import simulate
from local_agent.storage.database import Store
from local_agent.workspace.git import GitWorktrees, git
from local_agent.workspace.manager import Workspaces, copy_tree


def main():
    with tempfile.TemporaryDirectory(dir=Path.home() / "snap/firefox/common") as temp:
        root = Path(temp)
        repository = root / "repo"
        repository.mkdir()
        (repository / "app.py").write_text("VALUE = 1\n")
        git("-C", repository, "init", "-b", "main")
        git("-C", repository, "add", ".")
        git("-C", repository, "commit", "-m", "Browser fixture")
        state_root = root / "state"
        store = Store(state_root)
        run_id = asyncio.run(simulate(store))["run_id"]
        store.close()
        spaces = Workspaces(state_root)
        ws, workspace = spaces.create_coding(repository, run_id)
        snapshot = root / "snapshot"
        copy_tree(workspace / "project", snapshot, exclude=(".git",))
        manager = GitWorktrees(spaces)
        manager.finalize(ws, snapshot)
        release = threading.Event()
        captured = []

        def runner(path):
            captured.append(
                (
                    json.loads(path.read_text()),
                    json.loads(path.with_name("config.json").read_text()),
                )
            )
            assert release.wait(20), "Browser did not release the bounded fixture job"
            if len(captured) == 1:
                return {"status": "failed", "run_id": run_id,
                        "error": "Synthetic controller timeout without workspace result"}
            return {
                "status": "completed_unverified",
                "answer": "Synthetic browser fixture result",
                "run_id": run_id,
                "workspace": str(workspace),
                "workspace_id": ws,
                "git_workspace": manager.public(ws),
                "audit": {"ok": True},
                "project_tests": {"status": "passed", "audit": {"ok": True}},
            }

        server = BrowserServer(
            state_root,
            Path("config/browser.yaml"),
            port=0,
            runner=runner,
            allowed_roots=[repository],
        )
        cfg = server.profiles.load("coder.yaml")
        server.models.catalog = lambda **_: {
            "models": [
                {
                    "id": "ollama:" + cfg.model,
                    "model": cfg.model,
                    "provider": "ollama",
                    "selectable": True,
                    "vision": False,
                    "capabilities": ["completion", "tools"],
                }
            ],
            "default_id": "ollama:" + cfg.model,
            "error": None,
            "verifier": {"enabled": False, "models": [], "reason": "Disabled in fixture"},
        }
        server.models.select_reviewer = lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("Paid selection forbidden")
        )
        tid = server.threads.create("Completion loop browser fixture")
        source_id = "f" * 32
        directory = server.jobs.directory / source_id
        directory.mkdir()
        publish(
            directory / "status.json",
            {
                "job_id": source_id,
                "thread_id": tid,
                "created": 0,
                "status": "completed",
                "run_id": run_id,
                "kind": "answer",
                "mode": "coding",
                "model": cfg.model,
                "provider": "ollama",
                "question": "Improve this fixture",
                "answer": "Candidate",
                "profile_name": "coder.yaml",
                "git_workspace": manager.public(ws),
            },
        )
        server.threads.add_exchange(
            tid, "Improve this fixture", "Candidate", source_id, run_id, cfg.model
        )
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        profile = root / "firefox"
        profile.mkdir()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        (profile / "user.js").write_text(f'user_pref("marionette.port", {port});\n')
        proc = subprocess.Popen(
            ["firefox", "--headless", "--no-remote", "--profile", str(profile), "--marionette"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        conn = None
        try:
            for _ in range(100):
                try:
                    conn = socket.create_connection(("127.0.0.1", port), timeout=1)
                    break
                except OSError:
                    time.sleep(0.1)
            assert conn, "Firefox did not start"
            conn.settimeout(20)

            def read():
                size = b""
                while not size.endswith(b":"):
                    block = conn.recv(1)
                    if not block:
                        raise RuntimeError("Firefox connection closed")
                    size += block
                remaining, data = int(size[:-1]), b""
                while remaining:
                    block = conn.recv(remaining)
                    if not block:
                        raise RuntimeError("Firefox connection closed")
                    data += block
                    remaining -= len(block)
                return json.loads(data)

            read()
            sequence = 0

            def command(name, args=None):
                nonlocal sequence
                sequence += 1
                raw = json.dumps([0, sequence, name, args or {}]).encode()
                conn.sendall(str(len(raw)).encode() + b":" + raw)
                response = read()
                if response[2]:
                    raise RuntimeError(str(response[2]))
                return response[3]

            def js(script):
                return command(
                    "WebDriver:ExecuteScript",
                    {"script": script, "args": [], "newSandbox": False, "sandbox": "default"},
                )["value"]

            def wait(script):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    value = js(script)
                    if value:
                        return value
                    time.sleep(0.1)
                raise AssertionError(
                    "Browser wait failed: "
                    + script
                    + "\n"
                    + str(js("return document.body.innerText"))
                )

            def click_text(text):
                element = js(
                    'return Array.from(document.querySelectorAll("button")).find(e=>e.textContent==='
                    + json.dumps(text)
                    + ");"
                )
                element_id = element["element-6066-11e4-a52e-4f735466cecf"]
                command("WebDriver:ElementClick", {"id": element_id})

            def fill(element_id, text):
                element = command(
                    "WebDriver:FindElement", {"using": "css selector", "value": "#" + element_id}
                )
                ident = element.get("value", element)["element-6066-11e4-a52e-4f735466cecf"]
                command("WebDriver:ElementClear", {"id": ident})
                command(
                    "WebDriver:ElementSendKeys", {"id": ident, "text": text, "value": list(text)}
                )

            command("WebDriver:NewSession", {"capabilities": {}})
            command("WebDriver:SetWindowRect", {"width": 1280, "height": 1000})
            command("WebDriver:Navigate", {"url": f"http://127.0.0.1:{server.server_port}"})
            fill("pairing-code", server.pairing_code)
            click_text("Login")
            wait('return document.querySelectorAll("#history-list button").length>0;')
            js(
                'document.getElementById("config-select").value="coder.yaml";document.getElementById("config-select").dispatchEvent(new Event("change"));return true;'
            )
            click_text("Completion loop browser fixture")
            wait(
                'return Array.from(document.querySelectorAll("button")).some(e=>e.textContent==="Loop until complete…");'
            )
            assert js(
                'return document.getElementById("run-limit-minutes").value==="" && document.getElementById("run-limit-minutes").placeholder.includes("Profile default");'
            )
            fill("run-limit-minutes", "3")
            assert js('return document.getElementById("n-last-chats").value === "8";')
            fill("n-last-chats", "3")
            click_text("Loop until complete…")
            assert js(
                'return document.getElementById("loop-paid").hidden && document.getElementById("loop-consent").parentElement.hidden;'
            )
            click_text("Start local completion loop")
            wait('return document.getElementById("loop-status").textContent.includes("Elapsed:");')
            assert len(captured) == 1 and captured[0][1]["limits"]["run_timeout_seconds"] <= 180
            assert captured[0][0]["task_context"]["original_task"] == "Improve this fixture"
            assert captured[0][0]["task_context"]["n_last_chats"] == 3
            click_text("Stop loop after current stage")
            wait(
                'return document.getElementById("loop-status").textContent.includes("interrupted");'
            )
            release.set()
            wait('return !document.getElementById("ask-btn").disabled;')
            wait('return document.body.textContent.includes("Synthetic controller timeout without workspace result");')
            assert js('return document.querySelector(".transcript-item.assistant[open]").textContent.includes("Previous task context attached");')
            click_text("Loop until complete…")
            click_text("Start local completion loop")
            wait(
                'return document.getElementById("loop-status").textContent.includes("Complete — checks passed; not reviewer-approved.");'
            )
            wait('return document.body.textContent.includes("Previous task context attached");')
            wait('return !document.getElementById("ask-btn").disabled;')
            context_summary = js(
                'return Array.from(document.querySelectorAll("summary")).reverse().find(e=>e.textContent==="Previous task context attached");'
            )
            command(
                "WebDriver:ElementClick",
                {"id": context_summary["element-6066-11e4-a52e-4f735466cecf"]},
            )
            assert js(
                'return Array.from(document.querySelectorAll("summary")).reverse().find(e=>e.textContent==="Previous task context attached").parentElement.open;'
            )
            assert (repository / "app.py").read_text() == "VALUE = 1\n"
            assert len(captured) == 2
            assert all(request["task_context"]["n_last_chats"] == 3 for request, _ in captured)
            assert all(state["n_last_chats"] == 3 for state in server.loops.recent(tid))
            assert all(s["paid_attempts"] == 0 for s in server.loops.recent(tid))
            command("WebDriver:SetWindowRect", {"width": 390, "height": 844})
            assert js("return document.documentElement.scrollWidth<=window.innerWidth;")
            print(
                "Firefox completion controls, runtime override, context, stop, completion label and mobile layout passed (synthetic controller, zero inference)."
            )
        finally:
            release.set()
            if conn:
                conn.close()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
