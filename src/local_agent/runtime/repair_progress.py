"""Evidence-based local repair milestones and bounded recovery, independent of domain."""

import ast
import hashlib
import os
import re
import stat
from pathlib import Path

from local_agent.storage.blobs import canonical, digest
from local_agent.workspace.manager import IMPORT_EXCLUDES


class LocalStalled(RuntimeError):
    pass


def source_state(root, *, max_bytes=64 * 1024 * 1024, max_files=4096):
    """Hash regular project files without following symlinks, including parent components."""
    result, used, metadata = {}, 0, 0

    def walk(fd, prefix):
        nonlocal used, metadata
        for entry in sorted(os.scandir(fd), key=lambda item: item.name):
            if entry.name in IMPORT_EXCLUDES or entry.name.endswith((".pyc", ".egg-info")):
                continue
            name = prefix + entry.name
            if entry.is_symlink():
                raise ValueError("Cannot measure project symlink: " + name)
            child = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                mode = os.fstat(child).st_mode
                if stat.S_ISDIR(mode):
                    walk(child, name + "/")
                elif stat.S_ISREG(mode):
                    if len(result) >= max_files:
                        raise ValueError("Repair progress file-count limit exceeded")
                    hashed = hashlib.sha256()
                    while block := os.read(child, 65536):
                        used += len(block)
                        if used > max_bytes:
                            raise ValueError("Repair progress byte limit exceeded")
                        hashed.update(block)
                    result[name] = hashed.hexdigest()
                    metadata += len(canonical({name: result[name]}))
                    if metadata > 3 * 1024 * 1024:
                        raise ValueError("Repair progress metadata limit exceeded")
                else:
                    raise ValueError("Cannot measure special project file: " + name)
            finally:
                os.close(child)

    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(fd, "")
    finally:
        os.close(fd)
    return result


def command_kind(argv):
    """Conservative task signals, not authorization or proof of passing tests."""
    if not isinstance(argv, list) or not argv:
        return "command"
    name = Path(argv[0]).name
    text = " ".join(argv[1:])
    if any(flag in argv[1:] for flag in ("--version", "--help")) or name in {"which", "type"}:
        return "capability_probe"
    runtimes = {"python", "python3", "node", "nodejs", "bun", "deno"}
    runners = {"pytest", "py.test", "ctest", "jest", "vitest", "mocha"}
    if (name in runners
            or (name in {"npm", "pnpm", "yarn", "cargo", "go", "dotnet", "mvn", "gradle", "make"}
                and "test" in argv[1:])
            or (name == "npx" and len(argv) > 1 and argv[1] in runners)
            or (name in runtimes and ("--test" in argv[1:]
                or ("-m" in argv and any(value in {"pytest", "unittest"} for value in argv[1:]))
                or any(re.search(r"(?:^|/)(?:test_.*|.*[._]test|.*[._]spec)\.(?:py|[cm]?js|ts)$", value)
                       for value in argv[1:])))):
        return "validation_attempt"
    if name in {"python", "python3"} and "-c" in argv:
        try:
            code = ast.parse(argv[argv.index("-c") + 1])
            if any(isinstance(node, ast.Assert) for node in ast.walk(code)):
                return "validation_attempt"
        except (SyntaxError, IndexError):
            pass
    if name in {"node", "nodejs"} and re.search(r"\bassert(?:\s*\(|\.\w+\s*\()", text):
        return "validation_attempt"
    if (name in {"node", "nodejs", "python", "python3"}
            and any(flag in argv for flag in ("-e", "--eval", "-p", "-c"))
            and re.search(r"\b(?:typeof|hasattr|getattr|find_spec|which|require\.resolve|__version__|dir\s*\()", text)
            and not re.search(r"write|unlink|mkdir|remove|open\s*\(", text)):
        return "capability_probe"
    return "command"


def observations(store, run_id, after=0):
    calls, results, providers = {}, [], {}
    for event in store.events(run_id):
        if event.event_type == "tool.proposed":
            call = store.blobs.json(event.data["call_ref"])
            request_id = call["request_id"]
            if request_id not in providers:
                row = store.db.execute("SELECT request_ref FROM model_requests WHERE id=?",
                                       (request_id,)).fetchone()
                providers[request_id] = store.blobs.json(row[0])["provider"]
            if providers[request_id] != "harness":
                calls[call["call_id"]] = call
        if event.run_seq <= after:
            continue
        if event.event_type == "tool.skipped":
            for call_id in event.data.get("skipped_call_ids", []):
                if call_id in calls:
                    call = calls[call_id]
                    results.append({"sequence": event.run_seq, "tool": call["name"],
                                    "arguments": store.blobs.json(call["arguments_ref"]),
                                    "status": "rejected", "exit_code": None, "output_ref": None})
            continue
        if event.tool_call_id not in calls:
            continue
        call = calls[event.tool_call_id]
        if event.event_type == "execution.finished":
            result = store.blobs.json(event.data["result_ref"])
            status = result["status"]
            if call["name"] == "prepare_environment" and result.get("output_ref"):
                try:
                    if store.blobs.json(result["output_ref"]).get("status") == "environment_blocked":
                        status = "environment_blocked"
                except (ValueError, TypeError, AttributeError):
                    pass
            excerpt = None
            if (call["name"] == "run_command" and result["exit_code"] != 0
                    and result.get("output_ref")
                    and command_kind(store.blobs.json(call["arguments_ref"]).get("argv")) == "validation_attempt"):
                excerpt = store.blobs.read(result["output_ref"])[-1600:].decode("utf-8", errors="replace")
            results.append({"sequence": event.run_seq, "tool": call["name"],
                            "arguments": store.blobs.json(call["arguments_ref"]),
                            "status": status, "exit_code": result["exit_code"],
                            "output_ref": result["output_ref"], "failure_excerpt": excerpt})
        elif event.event_type in {"tool.rejected", "tool.skipped"}:
            results.append({"sequence": event.run_seq, "tool": call["name"],
                            "arguments": store.blobs.json(call["arguments_ref"]),
                            "status": "rejected", "exit_code": None, "output_ref": None})
    return results


class RepairProgress:
    def __init__(self, policy, files, findings, *, restored=None):
        self.policy = policy
        self.state = restored or {
            "version": 1, "sequence": 0, "actions": 0, "last_milestone": 0,
            "last_intervention": 0, "recoveries": 0, "stage": "investigation",
            "files": files, "initial_files": files, "seen_trees": [digest(canonical(files))],
            "seen_checks": [], "checks": [], "reads": [], "probes": 0,
            "seen_setups": [], "setup": [],
            "findings": findings, "last_action": None, "decision": "continue",
            "changed_paths": [], "monitor_error": None,
        }

    def observe(self, items, files, *, monitor_error=None):
        state = self.state
        state["monitor_error"] = monitor_error
        for item in items:
            if item["sequence"] <= state["sequence"]:
                continue
            state["sequence"] = item["sequence"]
            state["actions"] += 1
            args = item["arguments"]
            kind = command_kind(args.get("argv")) if item["tool"] == "run_command" else item["tool"]
            if kind == "environment_inventory":
                kind = "capability_probe"
            state["last_action"] = {"kind": kind, "status": item["status"],
                                    "output_ref": item["output_ref"]}
            if kind == "capability_probe":
                state["probes"] += 1
            if kind == "read_file" and item["status"] == "succeeded":
                path = str(args.get("path", ""))[:512]
                if path not in state["reads"]:
                    state["reads"] = [*state["reads"], path][-48:]
            if kind == "prepare_environment":
                key = digest(canonical({"arguments": args, "status": item["status"],
                                        "exit_code": item["exit_code"]}))
                if key not in state.setdefault("seen_setups", []):
                    state["seen_setups"] = [*state["seen_setups"], key][-16:]
                    state["setup"] = [*state.get("setup", []), {
                        "status": item["status"], "exit_code": item["exit_code"],
                        "output_ref": item["output_ref"],
                    }][-4:]
                    self.milestone("investigation" if item["status"] == "succeeded" else "blocked")
            if kind == "validation_attempt":
                key = digest(canonical({"argv": args.get("argv"), "cwd": args.get("cwd", "project"),
                                        "files": files}))
                check = {"argv": [str(arg)[:256] for arg in args.get("argv", [])[:12]],
                         "cwd": args.get("cwd", "project"),
                         "status": item["status"], "exit_code": item["exit_code"],
                         "output_ref": item["output_ref"], "independent": False}
                state["checks"] = [*state["checks"], check][-8:]
                # Keep failures visible when other suites pass or context is
                # trimmed. Only a passing rerun of this command resolves it.
                pending = state.setdefault("unresolved_checks", [])
                identity = {"argv": args.get("argv"), "cwd": args.get("cwd", "project")}
                check_key = digest(canonical(identity))
                pending = [c for c in pending if c["check_key"] != check_key]
                if item["exit_code"] != 0:
                    pending.append({**check, "check_key": check_key,
                                    "failure_excerpt": item.get("failure_excerpt")})
                state["unresolved_checks"] = pending[-16:]
                if key not in state["seen_checks"] and item["exit_code"] is not None:
                    state["seen_checks"] = [*state["seen_checks"], key][-128:]
                    self.milestone("validation" if item["exit_code"] == 0 else "reproduction")
        if files is not None:
            tree = digest(canonical(files))
            if tree not in state["seen_trees"]:
                state["seen_trees"] = [*state["seen_trees"], tree][-128:]
                self.milestone("repair")
            initial = state["initial_files"]
            state["changed_paths"] = sorted(k for k in initial.keys() | files.keys()
                                             if initial.get(k) != files.get(k))[:48]
            state["files"] = files
        gap = state["actions"] - state["last_milestone"]
        due = gap >= self.policy.inspection_allowance or state["probes"] >= self.policy.probe_allowance
        if state["recoveries"]:
            due = due and state["actions"] - state["last_intervention"] >= self.policy.recovery_allowance
        state["decision"] = "continue"
        if due:
            state["last_intervention"] = state["actions"]
            if state["recoveries"] >= self.policy.max_recoveries:
                state["decision"] = "local_stalled"
            else:
                state["recoveries"] += 1
                state["decision"] = "recover"
                state["warning"] = "Final recovery allowance before stopping stalled work." if state["recoveries"] == self.policy.max_recoveries else ""
        return state["decision"]

    def milestone(self, stage):
        self.state.update(stage=stage, last_milestone=self.state["actions"], probes=0)

    def public(self):
        value = {key: item for key, item in self.state.items()
                 if key not in {"files", "initial_files", "seen_trees", "seen_checks", "seen_setups"}}
        value["mode"] = self.policy.mode
        value["findings"] = [{**item, "observed": item["observed"][:500],
                              "expected": item["expected"][:300], "impact": item["impact"][:200],
                              "acceptance": [v[:200] for v in item["acceptance"][:4]]}
                             for item in value["findings"]]
        value["reads"] = value["reads"][-16:]
        value["unresolved_checks"] = value.get("unresolved_checks", [])[-4:]
        while len(canonical(value)) > 14000:
            if value["checks"]:
                value["checks"] = value["checks"][1:]
            elif len(value["unresolved_checks"]) > 1:
                value["unresolved_checks"] = value["unresolved_checks"][1:]
            elif value["reads"]:
                value["reads"] = value["reads"][1:]
            elif value["changed_paths"]:
                value["changed_paths"] = value["changed_paths"][1:]
            else:
                value["findings"] = [{"id": item["id"], "location": item["location"][:128],
                                      "observed": item["observed"][:200],
                                      "acceptance": item["acceptance"][:1]}
                                     for item in value["findings"]]
                break
        return value
