# Docker executor (M1)

Provision dependencies outside the agent loop, then pin the produced image ID:

```bash
export PATH="$HOME/.local/bin:$PATH"
uv sync --locked
uv run --locked local-agent build-sandbox
uv run --locked local-agent doctor
uv run --locked pytest --docker-image "$(python3 -c 'import json;print(json.load(open("config/sandbox.json"))["image"])')"
```

The build records the base registry digest, final local image digest, and trusted
worker hash in `config/sandbox.json`. Rebuild when the worker changes. The base is
the official Python 3.12 slim image served through Google's registry mirror.
The development interpreter is Python 3.14, selected through `.python-version`.

The controller accepts only the exact bytes of a committed execution request.
It creates a short-lived invocation container, inspects its effective configuration,
and captures an attestation before starting it. No sandbox receives the Docker
socket, protected state, model-server credentials, or host environment. Containers
use the current non-root UID/GID, network `none`, no GPU/devices, read-only root,
128 MiB `/tmp` tmpfs, no new privileges, dropped capabilities, default seccomp,
4 CPU equivalents, 4 GiB RAM, no swap, and 128 processes. The worker checks actual
cgroup and process protections before any operation and refuses unsupported hosts.

Only the selected run workspace is mounted. Imports reject symlinks and special
files, exclude Git state and interpreter caches, and cap imported bytes. Agent
operations run in an isolated interpreter at a fixed image path. Filesystem tools
walk directory descriptors with `O_NOFOLLOW`; edits require an exact prior hash or
exclusive creation. Commands use argv and run inside the container. Arbitrary
commands have the granted container authority; command strings are not a security
policy. Fixed Git diff disables external diff and textconv.

The controller drains both output streams concurrently with a combined 10 MiB
capture cap and 16 KiB preview. Crossing the cap kills the whole invocation.
Timeout and cancellation also kill the container, including descendants.
Stopped containers remain until SQLite commits the result; a protected fsynced
result marker supports later reconciliation. Docker's own retained logs are bounded.

Workspace disk protection is a **soft monitor** (1 GiB / 100,000 entries), checked
while the invocation runs. It is not a filesystem quota and can overshoot between
checks. M1's tests exercise resource settings, the seven tools, symlinks and special
files, import shadowing, missing images/protections, network/socket/host sentinel
absence, output floods, and descendant termination.

Docker shares the host kernel. This profile provides isolation, not a claim that
deliberately hostile code can never escape. Keep stronger isolation behind the
executor interface if later tasks require it.
