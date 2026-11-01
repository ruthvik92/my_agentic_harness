"""Declarative, recorded preparation. Project/install code never runs on the host."""

import asyncio
import io
import json
import os
import re
import shutil
import signal
import tarfile
import tempfile
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from local_agent.contracts import ExecutionResult, PrepareEnvironmentArgs
from local_agent.executor.docker import DockerExecutor
from local_agent.executor.lifecycle import lease, publish
from local_agent.storage.blobs import canonical, digest, private_directory
from local_agent.storage.database import AuditUnavailable
from local_agent.workspace.git import read_literal

RECIPE_VERSION = 4
CAP = 10 * 1024 * 1024
IMAGE = re.compile(r"sha256:[a-f0-9]{64}")
# Host-controlled capability adapters. New capabilities do not change dispatch/lifecycle.
RUNTIME_PACKAGES = {"python": (), "node": ("nodejs", "npm")}
CAPABILITY_PACKAGES = {"headless_browser": ("chromium-headless-shell",),
                       "browser_interaction": ("chromium-headless-shell",)}
BROWSER = Path(__file__).with_name('browser_launcher.py').read_text()
PROBE = '''import importlib.metadata,json,shutil,subprocess,sys
tools={}
for name in ('python','node','npm','chromium','chromium-headless-shell','harness-browser','git'):
 path=shutil.which(name)
 item={'available':bool(path),'path':path}
 if path:
  try:
   result=subprocess.run([path,'--version'],capture_output=True,text=True,timeout=10)
   item.update(version=(result.stdout+result.stderr).strip()[:300],exit_code=result.returncode)
  except Exception as exc:item['error']=type(exc).__name__
 tools[name]=item
packages=sorted(({'name':p.metadata.get('Name','?'),'version':p.version} for p in importlib.metadata.distributions()),key=lambda p:p['name'])
print(json.dumps({'python':sys.version,'tools':tools,'python_packages':packages[:100],'packages_truncated':len(packages)>100}))
'''
HYDRATE = '''import json,pathlib,shutil,sys
for item in json.loads(sys.argv[1]):
 source=pathlib.Path('/opt/local-agent/node-deps')/str(item['slot'])/'node_modules'
 target=pathlib.Path('/workspace')/item['path']/'node_modules'
 staged=pathlib.Path('/workspace/tools')/('node-stage-'+str(item['slot']))
 if staged.exists():shutil.rmtree(staged)
 if source.exists():shutil.copytree(source,staged,symlinks=True)
 backup=pathlib.Path('/workspace/tools')/('node-backup-'+str(item['slot']))
 if backup.is_symlink():backup.unlink()
 elif backup.exists():shutil.rmtree(backup)
 if target.is_symlink() or target.exists():target.rename(backup)
 try:
  if staged.exists():staged.rename(target)
 except BaseException:
  if backup.exists() or backup.is_symlink():backup.rename(target)
  raise
 if backup.is_symlink():backup.unlink()
 elif backup.exists():shutil.rmtree(backup)
'''


class Blocked(RuntimeError):
    pass


class Commands:
    """Bounded subprocess capture; the only executable is the trusted Docker CLI."""

    def __init__(self, agent, execution_id):
        self.agent, self.execution_id = agent, execution_id
        self.deadline = min(agent.deadline, time.monotonic() + agent.config.environment.timeout_seconds)

    async def run(self, args, *, timeout=None):
        name = None
        if args[0] == "run":
            name = "local-agent-env-" + self.execution_id + "-" + str(time.monotonic_ns())
            args = ["run", "--name", name, "--label", "local-agent.environment-run=" + self.agent.run_id, *args[1:]]
        argv = ["docker", *map(str, args)]
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise Blocked("Environment preparation deadline reached")
        started = time.monotonic()
        self.agent.event("environment.command_started", "environment", {
            "execution_id": self.execution_id, "command": argv,
            "started_at": datetime.now(UTC).isoformat(),
        })
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            self.agent.event("environment.command_finished", "environment", {
                "execution_id": self.execution_id, "command": argv, "status": "spawn_failed",
                "exit_code": None, "stdout_ref": self.agent.store.blobs.put(b""),
                "stderr_ref": self.agent.store.blobs.put(str(exc).encode()),
                "duration_seconds": time.monotonic() - started,
            })
            raise Blocked("Docker could not start: " + str(exc)) from exc
        buffers, status, total = [bytearray(), bytearray()], "completed", 0

        async def read(stream, index):
            nonlocal total
            while chunk := await stream.read(65536):
                if total + len(chunk) > CAP:
                    buffers[index].extend(chunk[:max(0, CAP - total)])
                    raise Blocked("Preparation output exceeded the 10 MiB capture limit")
                buffers[index].extend(chunk)
                total += len(chunk)
                self.agent.event("environment.command_output", "environment", {
                    "execution_id": self.execution_id, "stream": "stdout" if index == 0 else "stderr",
                    "output_ref": self.agent.store.blobs.put(chunk),
                })

        failure = None
        tasks = [asyncio.create_task(read(proc.stdout, 0)),
                 asyncio.create_task(read(proc.stderr, 1)), asyncio.create_task(proc.wait())]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), min(remaining, timeout or remaining))
        except BaseException as exc:
            status = "timeout" if isinstance(exc, TimeoutError) else "interrupted"
            failure = exc
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        stdout, stderr = (bytes(value) for value in buffers)
        self.agent.event("environment.command_finished", "environment", {
            "execution_id": self.execution_id, "command": argv, "status": status,
            "exit_code": proc.returncode, "duration_seconds": time.monotonic() - started,
            "stdout_ref": self.agent.store.blobs.put(stdout),
            "stderr_ref": self.agent.store.blobs.put(stderr),
        })
        if name and failure:
            # A killed Docker CLI does not necessarily terminate its container.
            previous_deadline = self.deadline
            self.deadline = time.monotonic() + 30
            try:
                await self.run(["rm", "-f", name], timeout=30)
            except Blocked:
                pass
            finally:
                self.deadline = previous_deadline
        if isinstance(failure, asyncio.CancelledError):
            raise failure
        if failure or proc.returncode:
            detail = (stderr or stdout)[-3000:].decode(errors="replace")
            raise Blocked(str(failure or "Docker command failed") + ": " + detail)
        return stdout


def capture(project_root, request):
    """Capture only named regular manifests, without traversing directory symlinks."""
    return {
        path: read_literal(project_root, Path(path), 8 * 1024 * 1024)[0]
        for path in request["dependency_manifests"]
    }


def specification(arguments, sandbox):
    previous = sandbox.get("prepared_environment", {}).get("request", {})
    return {
        name: sorted(set(previous.get(name, ())) | set(arguments.get(name, ())))
        for name in ("runtimes", "capabilities", "dependency_manifests", "system_packages", "python_packages")
    }


def recipe(spec, manifests, base_tag, context):
    """Small adapters produce controller-owned Dockerfile steps and runtime metadata."""
    steps = ["FROM " + base_tag, "USER root"]
    packages = set(spec["system_packages"])
    runtimes = set(spec["runtimes"])
    if any(p.endswith("package.json") or p.endswith("package-lock.json") for p in manifests):
        runtimes.add("node")
    for runtime in runtimes:
        packages.update(RUNTIME_PACKAGES[runtime])
    for capability in spec["capabilities"]:
        packages.update(CAPABILITY_PACKAGES[capability])
    if packages:
        steps += ["RUN apt-get update", "RUN " + json.dumps([
            "apt-get", "install", "-y", "--no-install-recommends", *sorted(packages),
        ]), "RUN rm -rf /var/lib/apt/lists/*"]
    if set(spec["capabilities"]) & {"headless_browser", "browser_interaction"}:
        (context / "harness-browser").write_text(BROWSER)
        (context / "harness-browser").chmod(0o755)
        steps.append("COPY harness-browser /usr/local/bin/harness-browser")
    if spec["python_packages"]:
        steps.append("RUN " + json.dumps([
            "python", "-m", "pip", "--isolated", "install", "--no-cache-dir",
            "--index-url", "https://pypi.org/simple", *spec["python_packages"],
        ]))
    groups = {}
    for path, data in manifests.items():
        groups.setdefault(str(Path(path).parent), {})[Path(path).name] = data
    node_roots = []
    for slot, (directory, files) in enumerate(sorted(groups.items())):
        staged = context / ("spec" + str(slot))
        staged.mkdir()
        for name, data in files.items():
            (staged / name).write_bytes(data)
        if "package.json" in files or "package-lock.json" in files:
            if not {"package.json", "package-lock.json"} <= set(files):
                raise Blocked("npm requires package.json and package-lock.json from the same directory")
            for name in ("package.json", "package-lock.json"):
                data = files[name]
                document = json.loads(data)
                if not isinstance(document, dict):
                    raise Blocked("Invalid npm manifest: " + name)
                # External/local sources need a dedicated operator adapter, not host file access.
                encoded = json.dumps(document)
                if re.search(r'file:|git\+|"link"\s*:\s*true', encoded):
                    raise Blocked("Local/Git npm dependencies require an operator-provided recipe")
            target = "/opt/local-agent/node-deps/" + str(slot)
            steps += ["COPY spec" + str(slot) + "/ " + target + "/",
                      "RUN " + json.dumps(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefix", target])]
            node_roots.append({"slot": slot, "path": directory})
        if "pyproject.toml" in files or "uv.lock" in files:
            if not {"pyproject.toml", "uv.lock"} <= set(files):
                raise Blocked("Python manifests require pyproject.toml and uv.lock from the same directory")
            metadata = tomllib.loads(files["pyproject.toml"].decode())
            lock = tomllib.loads(files["uv.lock"].decode())
            for package in lock.get("package", []):
                source = package.get("source", {})
                if not (set(source) == {"registry"} or source in ({"virtual": "."}, {"editable": "."})):
                    raise Blocked("Local/Git Python dependencies require an operator-provided recipe")
            backend = metadata.get("build-system", {}).get("requires", ["setuptools>=77", "wheel"])
            PrepareEnvironmentArgs.model_validate_json(canonical({"reason": "validate backend", "python_packages": backend}))
            uv = shutil.which("uv") or "/home/ruthvik/.local/bin/uv"
            shutil.copyfile(uv, context / "uv")
            (context / "uv").chmod(0o755)
            target = "/opt/local-agent/python-spec/" + str(slot)
            requirements = "/tmp/requirements" + str(slot) + ".txt"
            steps += ["COPY uv /usr/local/bin/uv", "COPY spec" + str(slot) + "/ " + target + "/",
                      "RUN " + json.dumps(["uv", "export", "--frozen", "--no-emit-project", "--no-header", "--no-annotate", "--project", target, "--output-file", requirements]),
                      "RUN " + json.dumps(["python", "-m", "pip", "--isolated", "install", "--no-cache-dir", *backend]),
                      "RUN " + json.dumps(["python", "-m", "pip", "--isolated", "install", "--no-cache-dir", "--require-hashes", "-r", requirements])]
    steps += ["USER " + str(os.getuid()) + ":" + str(os.getgid())]
    (context / "Dockerfile").write_text("\n".join(steps) + "\n")
    return node_roots


async def probe(agent, runner, sandbox):
    # No project or host-control mount: this probes the actual selected image only.
    output = await runner.run([
        "run", "--rm", "--network", "none", "--read-only", "--user", f"{os.getuid()}:{os.getgid()}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", str(agent.config.execution.container_pids_limit),
        "--memory", "512m", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m",
        "--entrypoint", "python", sandbox["image"], "-I", "-c", PROBE,
    ], timeout=60)
    info = json.loads(output)
    info.update(image=sandbox["image"], downloads_allowed=agent.config.environment.allow_network,
                execution_network="none", processes_survive_preparation=False,
                container_pids_limit=agent.config.execution.container_pids_limit)
    if info["tools"].get("harness-browser", {}).get("available"):
        info["browser_command"] = ["harness-browser", "--dump-dom", "file:///workspace/project/index.html"]
        info["browser_lifecycle"] = (
            "Use harness-browser rather than the raw Chromium shell wrapper. For CDP, use a unique "
            "profile and port (or --remote-debugging-port=0), wait for readiness, and terminate and "
            "await the launcher in a finally block. The launcher cleans up its browser process group."
        )
    from local_agent.environments.browser_support import probe_interactions

    info["capabilities"] = {
        "browser_interaction": await probe_interactions(agent, runner, sandbox),
        "browser_dom_dump": {"available": bool(info["tools"].get("harness-browser", {}).get("available")),
                             "tested": False},
    }
    return info


async def verify_worker(runner, sandbox):
    """Check protected files from the image without executing its interpreter."""
    expected = {name: sandbox[key] for name, key in (
        ("worker.py", "worker_hash"), ("verify.py", "verifier_hash"), ("pdf_extract.py", "pdf_helper_hash")
    ) if key in sandbox}
    expected.update({"toolkit/" + name: value for name, value in sandbox.get("toolkit_hashes", {}).items()})
    if not expected:
        return
    container = (await runner.run(["create", "--network", "none", "--read-only", sandbox["image"]])).decode().strip()
    try:
        for name, fingerprint in expected.items():
            data = await runner.run(["cp", container + ":/opt/local-agent/" + name, "-"])
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                files = [member for member in archive.getmembers() if member.isfile()]
                if len(files) != 1 or digest(archive.extractfile(files[0]).read()) != fingerprint:
                    raise Blocked("Installer changed a protected sandbox file: " + name)
    finally:
        await runner.run(["rm", "-f", container])


async def stop_keeper(agent):
    manager = agent.executor.make_manager(lambda kind, data: agent.event(kind, "environment", data))
    # Attest using the keeper's recorded settings/image, including a continuation's old image.
    from local_agent.executor.maintenance import cleanup_attestor

    manager.attest = cleanup_attestor(agent.store, agent.workspaces)
    await manager.stop(agent.workspace_id)


async def hydrate(agent, runner, sandbox):
    roots = sandbox.get("prepared_environment", {}).get("node_roots", [])
    if not roots:
        return
    # create_args grants exactly the same workspace and limits as ordinary tool execution.
    await runner.run([
        "run", "--rm", *agent.executor.create_args(agent.path), "--entrypoint", "python",
        sandbox["image"], "-I", "-c", HYDRATE, json.dumps(roots),
    ])


def selected(store, run_id):
    """Bind an immutable image to its originating run, never a mutable workspace pointer."""
    row = store.db.execute("SELECT manifest_ref FROM runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        # Imported/legacy candidates can predate run-scoped environment records.
        return {}
    events = [e for e in store.events(run_id) if e.event_type == "environment.selected"]
    if events:
        return store.blobs.json(events[-1].data["metadata_ref"])
    manifest = store.blobs.json(row[0])
    return store.blobs.json(manifest["config_ref"]).get("sandbox", {})


async def activate(agent, sandbox, runner=None):
    if not IMAGE.fullmatch(sandbox["image"]):
        raise Blocked("Prepared environment has no immutable image identity")
    await stop_keeper(agent)
    executor = DockerExecutor(agent.store, agent.workspaces, sandbox["image"], settings=agent.config.execution)
    executor.fault_hook = agent.fault
    if runner is not None:
        await hydrate(agent, runner, sandbox)
    agent.sandbox, agent.executor = sandbox, executor
    agent.environment_inventory = sandbox.get("prepared_environment", {}).get("inventory")
    if agent.environment_inventory:
        agent.environment_inventory = {**agent.environment_inventory,
                                       "container_pids_limit": agent.config.execution.container_pids_limit}


async def execute(agent, request):
    row = agent.store.db.execute("SELECT state,request_ref FROM execution_attempts WHERE id=?", (request.execution_id,)).fetchone()
    if row is None or row[0] != "started" or agent.store.blobs.read(row[1]) != canonical(request):
        raise ValueError("Environment tool requires an exact durable started request")
    start = time.monotonic()
    runner = Commands(agent, request.execution_id)
    key, failure_file = None, None
    sandbox = None
    try:
        if request.tool == "environment_inventory":
            inventory = await probe(agent, runner, agent.sandbox)
            agent.environment_inventory = inventory
            agent.event("environment.inventory", "environment", {"metadata_ref": agent.store.blobs.put_json(inventory)})
            output = {"status": "ready", "inventory": inventory}
        else:
            spec = specification(request.arguments, agent.sandbox)
            # Capture a coherent manifest snapshot while any keeper is paused.
            async with agent.frozen_workspace():
                manifests = capture(agent.path, spec)
            hashes = {name: digest(data) for name, data in manifests.items()}
            prepared = agent.sandbox.get("prepared_environment", {})
            base = prepared.get("base_image", agent.sandbox["image"])
            if prepared and prepared.get("image") != agent.sandbox["image"]:
                # Python's existing automatic preparation may have added a dependency layer.
                base = agent.sandbox["image"]
            key = digest(canonical({"version": RECIPE_VERSION, "base": base, "spec": spec, "manifests": hashes}))
            agent.event("environment.preparing", "environment", {"execution_id": request.execution_id,
                "metadata_ref": agent.store.blobs.put_json({"request": spec, "base_image": base, "key": key,
                    "manifest_refs": {name: agent.store.blobs.put(data) for name, data in manifests.items()}})})
            directory = agent.store.control / "environments"
            private_directory(directory)
            failure_file = directory / "failures" / agent.run_id / (key[7:] + ".json")
            if failure_file.exists():
                output = json.loads(failure_file.read_text())
                output["reused_failure"] = True
            else:
                cache = directory / "images" / key[7:]
                private_directory(cache)
                async with lease(directory / (key[7:] + ".lock")):
                    record = cache / "environment.json"
                    if record.exists():
                        sandbox = json.loads(record.read_text())
                        if not IMAGE.fullmatch(sandbox["image"]):
                            raise Blocked("Invalid cached environment image")
                        try:
                            await runner.run(["image", "inspect", "--format", "{{.Id}}", sandbox["image"]], timeout=30)
                        except Blocked:
                            sandbox = None
                    cache_hit = sandbox is not None
                    if sandbox is None:
                        if not agent.config.environment.allow_network:
                            raise Blocked("Environment is not cached. Operator must enable environment.allow_network for downloads")
                        attempts = sum(e.event_type == "environment.command_started" and e.data.get("command", [])[:2] == ["docker", "build"] for e in agent.store.events(agent.run_id))
                        if attempts >= agent.config.environment.max_preparations:
                            raise Blocked("Environment preparation limit reached for this run")
                        tag = "local-agent-environment-base:" + base[7:]
                        await runner.run(["tag", base, tag], timeout=30)
                        with tempfile.TemporaryDirectory(dir=cache) as temporary:
                            context = Path(temporary)
                            node_roots = recipe(spec, manifests, tag, context)
                            agent.event("environment.recipe", "environment", {"execution_id": request.execution_id,
                                "input_ref": agent.store.blobs.put((context / "Dockerfile").read_bytes())})
                            iid = context / "image-id"
                            await runner.run(["build", "--progress=plain", "--pull=false", "--network=default", "--iidfile", iid, context])
                            image = iid.read_text().strip()
                        if not IMAGE.fullmatch(image):
                            raise Blocked("Builder did not return an immutable Docker image ID")
                        sandbox = {**agent.sandbox, "image": image, "prepared_environment": {
                            "image": image, "base_image": base, "key": key, "request": spec,
                            "manifest_hashes": hashes, "node_roots": node_roots,
                        }}
                        await verify_worker(runner, sandbox)
                        inventory = await probe(agent, runner, sandbox)
                        for runtime in spec["runtimes"]:
                            if not inventory["tools"][runtime]["available"]:
                                raise Blocked("Prepared image is missing requested runtime: " + runtime)
                        if "headless_browser" in spec["capabilities"] and not inventory["tools"].get("harness-browser", {}).get("available"):
                            raise Blocked("Prepared image is missing its Chromium headless launcher")
                        if "browser_interaction" in spec["capabilities"] and not inventory["capabilities"]["browser_interaction"]["available"]:
                            raise Blocked("Prepared image failed interactive browser self-test; inspect inventory evidence")
                        sandbox["prepared_environment"]["inventory"] = inventory
                        publish(record, sandbox)
                if cache_hit:
                    # Images are reusable; readiness evidence is specific to runner + resource grant.
                    inventory = await probe(agent, runner, sandbox)
                    if "browser_interaction" in spec["capabilities"] and not inventory["capabilities"]["browser_interaction"]["available"]:
                        raise Blocked("Cached image failed interactive browser self-test under current settings")
                    sandbox["prepared_environment"]["inventory"] = inventory
                # Stop background processes before final manifest validation and activation.
                await stop_keeper(agent)
                if {p: digest(d) for p, d in capture(agent.path, spec).items()} != hashes:
                    raise Blocked("Dependency manifests changed during preparation; submit an updated request")
                await activate(agent, sandbox, runner)
                output = {"status": "ready", "image": sandbox["image"], "cache_hit": cache_hit,
                          "inventory": agent.environment_inventory,
                          "processes_restarted": True}
                agent.event("environment.selected", "environment", {
                    "execution_id": request.execution_id, "metadata_ref": agent.store.blobs.put_json(sandbox),
                })
    except AuditUnavailable:
        raise
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        output = {"status": "environment_blocked", "error": str(exc)[:4000],
                  "image": agent.sandbox["image"], "request_key": key}
        if failure_file:
            publish(failure_file, output)
        agent.event("environment.blocked", "environment", {"execution_id": request.execution_id,
                    "metadata_ref": agent.store.blobs.put_json(output)})
    commands = [e.data for e in agent.store.events(agent.run_id)
                if e.event_type == "environment.command_finished"
                and e.data.get("execution_id") == request.execution_id]
    output["setup_commands"] = len(commands)
    output["setup_evidence"] = [{k: item.get(k) for k in ("stdout_ref", "stderr_ref", "exit_code", "status")}
                                for item in commands[-10:]]
    data = canonical(output)
    result = ExecutionResult(
        execution_id=request.execution_id, status="succeeded", exit_code=0,
        output_ref=agent.store.blobs.put(data), stdout_ref=agent.store.blobs.put(data),
        preview=data.decode()[:16384], truncated=len(data) > 16384,
        captured_bytes=len(data), duration_seconds=time.monotonic() - start,
        side_effect_status="applied" if output["status"] == "ready" and request.tool == "prepare_environment" else "none",
        run_id=agent.run_id, workspace_id=agent.workspace_id, tool_call_id=request.call_id,
    )
    # Same durable result marker protocol as Docker execution. Recovery never reruns a build.
    publish(agent.store.control / "attempts" / (request.execution_id + ".json"), {
        "execution_id": request.execution_id, "result_ref": agent.store.blobs.put_json(result),
    })
    agent.fault("after_environment_result_publication")
    return result
