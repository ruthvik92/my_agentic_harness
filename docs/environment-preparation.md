# Model-requested Docker environments

Coding profiles can expose `environment_inventory` and `prepare_environment`.
The inventory is probed from the selected image before the first coding turn and
included in subsequent model context. Optional tools are discovered without
failing imports. No project code is run on the host.

The checked-in coder profile enables both tools and grants preparation downloads:

```yaml
tools: [read_file, write_file, patch_file, list_files, search_files, run_command,
        git_diff, register_tool, execute_tool, environment_inventory, prepare_environment]
environment:
  allow_network: true
  timeout_seconds: 600
  max_preparations: 4
```

Other profiles default to `allow_network: false`; a cached image can still be
selected without downloads. The execution policy remains offline. The preparation
grant never permits the model to change mounts, privileges, image IDs, resource
limits, host commands, or execution networking.

For real clicks, keyboard input and persistence checks, see
[browser verification and capability recovery](browser-verification.md). The
`browser_interaction` capability requires a passing interaction self-test; the
older `headless_browser` capability continues to provide the DOM-dump launcher.

## Requests

For a browser game, the model can call:

```json
{
  "reason": "Test the actual JavaScript and browser UI",
  "runtimes": ["node"],
  "capabilities": ["headless_browser"]
}
```

The headless capability installs Debian's Chromium headless shell and the
`harness-browser` launcher. The launcher restricts CPU affinity and supplies
container-compatible flags, retaining the sandbox's 128-task limit and Docker
isolation. Inventory returns the actual versions and an example browser command:

```text
harness-browser --dump-dom file:///workspace/project/index.html
```

Registry packages can be requested declaratively, without the harness anticipating
every use case:

```json
{
  "reason": "Need a Python JavaScript engine and build tooling",
  "python_packages": ["quickjs"],
  "system_packages": ["build-essential"]
}
```

Names and version constraints are validated; paths, URLs, command fragments and
installer options are rejected. Versions should be pinned when reproducibility
is important. The cached resulting image is always identified by immutable ID.

Existing project dependencies can instead use named manifests:

```json
{
  "reason": "Install locked frontend dependencies",
  "dependency_manifests": ["project/package.json", "project/package-lock.json"]
}
```

Python accepts `pyproject.toml` and `uv.lock` together. Both Python and npm pairs
must be in the same directory; subdirectories are supported. Only specified
regular files enter the build context; symlink traversal is rejected. Local/Git
dependency sources require a dedicated operator recipe. npm preparation uses
`--ignore-scripts`; any needed project install/build scripts must subsequently run
inside the offline execution container. It does not generate a missing lockfile.

Python lock export and installers execute inside the preparation container.
The trusted UV binary is included for Python lock export, not executed against
project files on the host. npm dependencies are installed in the image and copied
into each execution/check/review workspace's `node_modules` before use. Those
generated dependencies are excluded from source snapshots and candidate commits.

## Lifecycle and evidence

Preparation is a separate Docker build with network access only when granted.
Recipes and package installers run in Docker. Ordinary coding and inventory
containers remain offline, non-root, with a read-only root and dropped
capabilities. Manifest bytes, Dockerfile, commands, streamed output chunks,
complete bounded stdout/stderr, duration, exit status, and image selection are
recorded in durable evidence. The output cap is 10 MiB per command; overruns
terminate the command and report the limitation. Run exports retain this evidence.

Cache keys include the base image, recipe version, requested capabilities/packages,
and manifest content hashes. Reason wording is not a cache input. Missing cached
images are rebuilt when permitted. Changing a dependency manifest invalidates
the key. An identical failed request reuses its failure within the run, rather
than repeatedly downloading or tripping the command-failure guard.

A completed request returns `status: ready` or `status: environment_blocked`.
The outer tool operation can succeed in reporting a blockage; that does **not**
mean installation or tests passed. A blocked response includes a reason, and the
previous image remains selected. An agent should revise requirements or report
the setup limitation instead of repeating the same request.

On success, an old persistent keeper is stopped and the executor switches to the
new immutable image. Project source files survive; shell state, `/tmp`, and
background processes do not. Installed npm dependency directories are refreshed.
New requirements extend the run's prior environment specification.

Independent completion checks, workspace review, and continuation inherit the
environment from the originating coding run. Review of an older candidate uses
its source run, not the workspace's latest mutable state. Resume restores recorded
selection and published results; an interrupted preparation without a result
requires reconciliation and is never automatically rebuilt/replayed.

The initial adapters target the pinned Debian/Python sandbox: Python registry
packages/UV locks, Node/npm locks, and Chromium headless. Runtime/capability package
mappings in `environments/service.py` are operator-owned extension points. Custom
OS images, private authenticated registries, local dependency trees, and other
package managers need additional adapters; unsupported requests are not silently
treated as prepared environments.
