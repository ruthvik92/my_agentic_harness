import argparse
import asyncio
import json
import sqlite3
from pathlib import Path

from local_agent.observability.audit import audit
from local_agent.runtime.loop import simulate
from local_agent.runtime.replay import recorded_replay
from local_agent.storage.database import Store

DEFAULT_ROOT = Path.home() / ".local" / "share" / "local-agent"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Local coding agent: Docker execution and protected audit"
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("simulate", help="run fixed scripted scenario; no real tools or inference")
    doctor_parser = sub.add_parser(
        "doctor", help="check local storage and Docker prerequisites without loosening protection"
    )
    doctor_parser.add_argument("--agent", type=Path, default=Path("config/coder.yaml"))
    browser = sub.add_parser(
        "trace-web", help="serve read-only traces on loopback for your browser"
    )
    browser.add_argument("--port", type=int, default=8765)
    browser = sub.add_parser(
        "browser-web",
        aliases=["phone-web"],
        help="serve the paired browser interface",
    )
    browser.add_argument("--host", default="127.0.0.1")
    browser.add_argument("--port", type=int, default=8767)
    browser.add_argument("--agent", type=Path, default=Path("config/browser.yaml"))
    browser.add_argument("--verifier-agent", type=Path, default=Path("config/phone-verifier.yaml"))
    browser.add_argument("--config-dir", type=Path, default=None)
    browser.add_argument("--allow-root", type=Path, action="append", default=None)
    browser_run = sub.add_parser(
        "browser-run", help="run a paired browser request against a stored run"
    )
    browser_run.add_argument("--agent", type=Path, required=True)
    browser_run.add_argument("--request", type=Path, required=True)
    browser_run.add_argument("--allow-root", type=Path, action="append", default=None)
    screenshot = sub.add_parser(
        "screenshot", help="answer a screenshot question with retained traces"
    )
    screenshot.add_argument("--request", type=Path, required=True)
    screenshot.add_argument("--agent", type=Path, default=Path("config/phone.yaml"))
    build = sub.add_parser(
        "build-sandbox", help="provision the trusted Docker image outside the agent loop"
    )
    build.add_argument("--base", default="mirror.gcr.io/library/python:3.12-slim-bookworm")
    live = sub.add_parser(
        "run", help="run the offline coding agent against a copied local repository"
    )
    live.add_argument("--agent", type=Path, default=Path("config/coder.yaml"))
    live.add_argument("--repo", type=Path, required=True)
    live.add_argument("--task-file", type=Path, required=True)
    live.add_argument(
        "--verify-fixture",
        action="store_true",
        help="verify the calculator fixture using protected image tests",
    )
    live.add_argument("--verifier", choices=("calculator", "mean", "clamp"))
    circuit = sub.add_parser(
        "circuit", help="extract PDF images and analyze a draft circuit netlist"
    )
    circuit.add_argument("--case", type=Path, required=True)
    circuit.add_argument("--pdf", required=True, help="PDF path relative to the case directory")
    circuit.add_argument("--page", type=int, required=True)
    circuit.add_argument("--context-page", type=int)
    circuit.add_argument("--region", type=float, nargs=4)
    circuit.add_argument("--dpi", type=int, default=300)
    circuit.add_argument("--question", default="Explain what happens in this schematic.")
    circuit.add_argument("--agent", type=Path, default=Path("config/analog.yaml"))
    resume = sub.add_parser(
        "resume", help="reconcile committed history and continue a nonterminal run"
    )
    resume.add_argument("run_id")
    stop = sub.add_parser(
        "cancel", help="durably request cancellation; active controller handles cleanup"
    )
    stop.add_argument("run_id")
    export = sub.add_parser(
        "export", help="export metadata by default; evidence requires explicit inclusion"
    )
    export.add_argument("run_id")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--include-evidence", action="store_true")
    backup = sub.add_parser("backup", help="consistent private ledger and evidence backup")
    backup.add_argument("--output", type=Path, required=True)
    bundle = sub.add_parser("verify-bundle", help="check a bundle checksum manifest")
    bundle.add_argument("output", type=Path)
    evaluation = sub.add_parser(
        "evaluate", help="run protected held-out tasks and compare context profiles"
    )
    evaluation.add_argument("--agent", type=Path, default=Path("config/coder.yaml"))
    evaluation.add_argument("--windows", type=int, nargs="+", default=[8192, 16384])
    evaluation.add_argument("--rounds", type=int, default=1)
    for name in ("trace", "audit", "replay", "export-events", "report"):
        child = sub.add_parser(name)
        child.add_argument("run_id")
        if name == "trace":
            child.add_argument("--json", action="store_true", help="show full audit envelopes")
            child.add_argument(
                "--evidence", action="store_true", help="include retained local payloads"
            )
        if name == "replay":
            child.add_argument("--recorded-only", action="store_true", required=True)
    containers = sub.add_parser("containers", help="inspect or clean host-owned persistent sessions")
    containers.add_argument("action", choices=("list", "cleanup", "stop"))
    containers.add_argument("--workspace")
    containers.add_argument("--agent", type=Path, default=Path("config/coder.yaml"))
    args = parser.parse_args(argv)
    store = None
    try:
        if args.command in {"browser-web", "phone-web"}:
            from local_agent.mobile.web import serve

            serve(
                args.data_root,
                args.agent,
                args.host,
                args.port,
                args.verifier_agent,
                config_dir=args.config_dir,
                allowed_roots=args.allow_root,
            )
            return 0
        if args.command == "trace-web":
            from local_agent.observability.browser import serve

            if not 0 <= args.port <= 65535:
                raise ValueError("invalid port")
            serve(args.data_root, args.port)
            return 0
        if args.command == "verify-bundle":
            from local_agent.storage.bundles import verify_bundle

            print(json.dumps(verify_bundle(args.output), indent=2))
            return 0
        if args.command == "build-sandbox":
            from local_agent.executor.build import build_image

            print(json.dumps(asyncio.run(build_image(args.base)), indent=2))
            return 0
        readonly = args.command in {"trace", "audit", "replay", "report"}
        store = Store(args.data_root, readonly=readonly)
        if args.command == "containers":
            from local_agent.config import load_config
            from local_agent.doctor import sandbox_config
            from local_agent.executor.docker import DockerExecutor
            from local_agent.executor.maintenance import sweep
            from local_agent.workspace.manager import Workspaces

            config = load_config(args.agent)
            image = sandbox_config()["image"]
            if args.action == "list":
                manager = DockerExecutor(
                    store, Workspaces(store.root), image, settings=config.execution
                ).make_manager(lambda *_: None)
                records = []
                for path in sorted(manager.directory.glob("ws_*.json")):
                    record = manager.load(path.stem)
                    records.append({key: record.get(key) for key in (
                        "workspace_id", "container_id", "state", "last_used_at",
                        "idle_timeout", "active_execution_id",
                    )})
                print(json.dumps(records, indent=2))
            else:
                if args.action == "stop" and not args.workspace:
                    raise ValueError("containers stop requires --workspace")
                result = asyncio.run(sweep(
                    store.root, image, config.execution,
                    workspace_id=args.workspace if args.action == "stop" else None,
                ))
                print(json.dumps(result, indent=2))
            return 0
        if args.command == "screenshot":
            from tempfile import TemporaryDirectory

            from local_agent.circuits.agent import read_evidence
            from local_agent.config import load_config
            from local_agent.doctor import sandbox_config
            from local_agent.mobile import ScreenshotAgent, validate_request

            request_path = args.request.absolute()
            request = validate_request(
                json.loads(read_evidence(request_path.parent, request_path.name, 6 * 1024 * 1024))
            )
            config = load_config(args.agent)
            with TemporaryDirectory(prefix="local-agent-screenshot-") as source:
                result = asyncio.run(
                    ScreenshotAgent(store, config, sandbox_config(), request=request).run(
                        Path(source), request["question"]
                    )
                )
            result["model"] = config.model
            if (
                store.healthy
                and store.db.execute(
                    "SELECT 1 FROM runs WHERE id=?", (result["run_id"],)
                ).fetchone()
            ):
                result["audit"] = audit(store, result["run_id"])
                store.export_jsonl(result["run_id"])
            print(json.dumps(result, indent=2))
            return (
                0
                if result["status"] == "completed_unverified" and result.get("audit", {}).get("ok")
                else 1
            )
        if args.command == "browser-run":
            from local_agent.circuits.agent import read_evidence
            from local_agent.config import load_config
            from local_agent.doctor import sandbox_config
            from local_agent.mobile.browser_requests import validate_browser_request
            from local_agent.mobile.browser_runtime import run_browser

            request_path = args.request.absolute()
            request = json.loads(
                read_evidence(request_path.parent, request_path.name, 6 * 1024 * 1024)
            )
            if not isinstance(request, dict):
                raise ValueError("browser-run request must be a JSON object")
            request.pop("mode", None)
            config = load_config(args.agent)
            normalized = validate_browser_request(
                request, config, args.allow_root or [Path.cwd()]
            )
            result = asyncio.run(run_browser(store, config, normalized, sandbox_config()))
            print(json.dumps(result, indent=2))
            return (
                0
                if result["status"] == "completed_unverified" and result.get("audit", {}).get("ok")
                else 1
            )
        if args.command in {"backup", "export"}:
            from local_agent.storage.bundles import backup, export_run

            result = (
                backup(store, args.output)
                if args.command == "backup"
                else export_run(
                    store, args.run_id, args.output, include_evidence=args.include_evidence
                )
            )
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "evaluate":
            import sys

            from local_agent.config import load_config
            from local_agent.evaluation.suite import evaluate

            if (
                not 1 <= args.rounds <= 10
                or not args.windows
                or len(set(args.windows)) != len(args.windows)
            ):
                raise ValueError("evaluation requires 1–10 rounds and distinct context windows")
            if any(w < 8192 or w > 32768 for w in args.windows):
                raise ValueError("evaluation windows must be between 8192 and 32768")

            def progress(item):
                print(
                    json.dumps(
                        {
                            k: item[k]
                            for k in (
                                "run_id",
                                "task",
                                "window_tokens",
                                "status",
                                "total_wall_seconds",
                            )
                        }
                    ),
                    file=sys.stderr,
                    flush=True,
                )

            result = asyncio.run(
                evaluate(store, load_config(args.agent), tuple(args.windows), args.rounds, progress)
            )
            print(json.dumps(result, indent=2))
            return 0 if all(r["audit"]["ok"] for r in result["runs"]) else 1
        if args.command == "report":
            from local_agent.evaluation.report import report

            print(json.dumps(report(store, args.run_id), indent=2))
            return 0
        if args.command == "cancel":
            from local_agent.runtime.cancellation import cancel

            print(json.dumps(asyncio.run(cancel(store, args.run_id)), indent=2))
            return 0
        if args.command == "resume":
            from local_agent.contracts import AgentConfig
            from local_agent.runtime.agent import Agent
            from local_agent.storage.blobs import canonical

            row = store.run(args.run_id)
            manifest = store.blobs.json(row["manifest_ref"])
            if manifest["mode"] != "live":
                raise ValueError("resume requires a live run")
            resolved = store.blobs.json(manifest["config_ref"])
            config = AgentConfig.model_validate_json(canonical(resolved["agent"]))
            runtime = Agent
            if config.instructions_version == "browser-v1" or any(
                event.event_type == "browser.prepared" for event in store.events(args.run_id)
            ):
                from local_agent.mobile.browser_agent import BrowserAgent

                runtime = BrowserAgent
            elif config.instructions_version in {"analog-v1", "analog-v2"}:
                from local_agent.circuits.agent import CircuitAgent

                runtime = CircuitAgent
            elif config.instructions_version == "phone-v1":
                from local_agent.mobile import ScreenshotAgent

                runtime = ScreenshotAgent
            result = asyncio.run(
                runtime(store, config, resolved["sandbox"]).run(
                    None, resolved["task"], resume_run_id=args.run_id
                )
            )
            if store.healthy:
                store.export_jsonl(args.run_id)
                result["audit"] = audit(store, args.run_id)
            print(json.dumps(result, indent=2))
            return (
                0
                if result["status"] in {"verified", "completed_unverified"}
                and result["audit"]["ok"]
                else 1
            )
        if args.command == "circuit":
            from local_agent.circuits.agent import CircuitAgent
            from local_agent.config import load_config
            from local_agent.doctor import sandbox_config

            config = load_config(args.agent)
            agent = CircuitAgent(
                store,
                config,
                sandbox_config(),
                pdf=args.pdf,
                page=args.page,
                dpi=args.dpi,
                region=args.region,
                context_page=args.context_page,
            )
            result = asyncio.run(agent.run(args.case, args.question))
            if result["status"] == "completed_unverified":
                result["exported_case"] = agent.export_case(args.case, result)
            result["audit"] = audit(store, result["run_id"])
            store.export_jsonl(result["run_id"])
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "completed_unverified" and result["audit"]["ok"] else 1
        if args.command == "run":
            from local_agent.config import load_config
            from local_agent.doctor import sandbox_config
            from local_agent.models.capabilities import ensure_capabilities
            from local_agent.runtime.agent import Agent

            config = load_config(args.agent)
            task = args.task_file.read_text()
            if len(task.encode()) > 65536:
                raise ValueError("task exceeds size limit")

            async def execute_live():
                sandbox = sandbox_config()
                capability = await ensure_capabilities(store, config, sandbox)
                result = await Agent(store, config, sandbox, capability_report=capability).run(
                    args.repo, task, verify_fixture=args.verifier or args.verify_fixture
                )
                result["capability_probe"] = capability
                return result

            result = asyncio.run(execute_live())
            if store.healthy and "error" not in result:
                result["audit"] = audit(store, result["run_id"])
                store.export_jsonl(result["run_id"])
            print(json.dumps(result, indent=2))
            return (
                0
                if result["status"] in {"verified", "completed_unverified"}
                and result.get("audit", {}).get("ok")
                else 1
            )
        if args.command == "doctor":
            from local_agent.doctor import doctor

            result = asyncio.run(doctor(store, args.agent))
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.command == "simulate":
            result = asyncio.run(simulate(store))
            if result["status"] == "completed_unverified":
                result["audit"] = audit(store, result["run_id"])
                if not result["audit"]["ok"]:
                    print(json.dumps(result, indent=2))
                    return 1
            try:
                if store.healthy:
                    result["events_export"] = str(store.export_jsonl(result["run_id"]))
            except OSError as exc:
                result["export_error"] = str(exc)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "completed_unverified" else 1
        if args.command == "trace":
            print(f"{args.run_id} status={store.run(args.run_id)['status']}")
            for event in store.events(args.run_id):
                if args.json:
                    print(event.model_dump_json())
                else:
                    print(
                        f"{event.run_seq:04d} {event.event_type:28s} "
                        f"call={event.tool_call_id or '-'} {json.dumps(event.data)}"
                    )
            if args.evidence:
                from local_agent.storage.database import references

                pending = [store.run(args.run_id)["manifest_ref"]]
                pending.extend(
                    ref for event in store.events(args.run_id) for ref in references(event.data)
                )
                seen = set()
                while pending:
                    ref = pending.pop()
                    if ref in seen:
                        continue
                    seen.add(ref)
                    data = store.blobs.read(ref)
                    try:
                        payload = json.loads(data)
                        pending.extend(references(payload))
                    except (ValueError, UnicodeDecodeError):
                        payload = data.decode("utf-8", errors="replace")
                    print(json.dumps({"ref": ref, "payload": payload}))
            return 0
        if args.command == "audit":
            result = audit(store, args.run_id)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.command == "replay":
            report = audit(store, args.run_id)
            if not report["ok"]:
                print(json.dumps(report, indent=2))
                return 1
            print(json.dumps(recorded_replay(store, args.run_id), indent=2))
            return 0
        print(store.export_jsonl(args.run_id))
        return 0
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
