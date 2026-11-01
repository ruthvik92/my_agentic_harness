# Project tests and offline environments

Coding with the shipped `coder.yaml` now enables `project_tests: true`. Models
receive a shared test helper and test-driven development instructions. They can
run `python /workspace/tools/test_project.py` through `run_command` to reproduce
failures before implementing a fix. Before accepting completion, the controller
runs the plan independently in a fresh snapshot. It sends failed results back
for up to two repair attempts and saves the actual report on the coding reply.
A candidate can remain unverified with failing or blocked checks; that never
counts as passing tests or grants merge approval.

Workspace review defaults to `auto` and uses the same resolver, dependency
preparation and runner. A paid reviewer receives the resulting execution evidence.
Environment preparation failure is recorded before paid inspection starts.
With browser tests set to `auto`, the paid reviewer also discovers and executes
relevant suites from project files, including JavaScript or mixed projects outside
the Python adapter. Its selected test commands must match successful captured
executions and pass replay in a fresh candidate copy before approval. No automatic
plan does not block inspection. An automatic environment blocker can be inspected
and explained, but still blocks approval; explicit override setup failures stop
before paid inspection. The browser report shows both controller checks and
reviewer-selected checks. No manual command is required.
Choosing a better model is still explicit; successful local checks do not
silently incur a paid review. Other coding profiles can enable `project_tests`
in their YAML. Profile details show whether controller tests are enabled.

## Automatic Python projects

For a normal Python project, the default command is `python -m pytest -q` in the
selected task directory. Packaged projects with a `build-system` in
`pyproject.toml` are installed into a workspace-local virtual environment; the
host's environment is never copied. Installation builds from a separate source
copy so metadata/build files do not modify the candidate. Project root and
`src/` imports are available in the test process. Plain modules need no package
installation. Tool-only pyproject files are supported without forcing packaging.

Runtime/dev/test dependencies come from a committed `uv.lock`; the export uses
UV's default dependency groups and an existing `test` group/extra when present.
Dependency changes without a lock are reported as environment-blocked, rather
than selecting arbitrary package versions or asking a model to fetch them.

Automatic checks also explicitly run newly changed `test_*.py` files from a
root task. This prevents pytest's default `norecursedirs` or `testpaths` settings
from hiding newly added tests. Python implementation changes need regression
test changes before controller checks can be reported as passing.

This is a Python adapter plus explicit command contracts, not a promise that
arbitrary frameworks, native builds, external services or datasets are available.
Unsupported tools/dependency sources fail visibly and need project environment
provisioning. A passing configured suite does not establish exhaustive correctness.

## Configure an exceptional project once

Commit `.local-agent-tests.json` at the project root or an existing task directory:

```json
{
  "version": 1,
  "install_project": true,
  "prepare_dependencies": true,
  "dependency_network": "auto",
  "dependency_groups": ["test"],
  "dependency_extras": [],
  "timeout_seconds": 120,
  "commands": [
    {"argv": ["python", "-m", "pytest", "-q"], "cwd": "."}
  ]
}
```

The group above must exist in that project's lock. Omit it for the ordinary UV
defaults. Commands are argument arrays, with no implicit shell. Their directories
are relative to the contract's directory; paths cannot traverse outside the
project. Up to eight commands can be declared. Independent controller checks use
separate bounded executions for each command and preserve every result, including
an earlier failure followed by later successes. Existing execution/profile time
and tool limits still apply.

An explicitly standalone fixture can use `install_project: false`,
`prepare_dependencies: false`, and a scoped pytest command such as
`["python", "-m", "pytest", "--confcutdir=.", "-q"]`. Isolation is a project
contract decision; the runner does not silently disable parent conftests to get
a green result.

The controller freezes the owner's existing contract before coding. A model
cannot replace it with a weaker command during the same run. Workspace review
inherits a contract from the captured source HEAD, rather than trusting a changed
candidate contract. New/changed contract policy should be reviewed as configuration
before becoming the next source baseline. Automatic projects discover new tests
without requiring a model-authored contract. A manually entered browser command
is an explicit override; leaving `auto` avoids per-run command entry.

## Network and caching

Execution containers remain `--network none` in both ephemeral and persistent
modes. Attestation still checks that property. Project installation uses
`--no-index --no-deps --no-build-isolation` and tests run with offline installer
settings. No Docker socket or host source checkout is added to their mounts.

When a dependency image is absent, a separate controller preparation build may
access public PyPI. It receives only exported dependency requirements and a
controller-generated Dockerfile, with no project code, agent scripts or API
credentials. It installs wheels; runtime/test dependencies retain lock hashes.
Build requirements are resolved during preparation and the installed versions
are recorded. The resulting image is pinned by immutable image ID and cached
using the base/Python image, pyproject, lock and selected dependency groups/extras.
Subsequent matching runs reuse it. The original sandbox image and trusted worker
are unchanged. Set `dependency_network: "never"` to require an existing cached
image. Private/URL/local dependency sources and source-only distributions need
explicit environment provisioning; they are not silently executed on the host.

Persistent coding sessions retain their workspace/container state according to
the existing idle policy. Independent checks and workspace reviews use separate
copies and containers; they do not reuse potentially modified coding state.

## Reports and meters

Reports distinguish `passed`, `test_failed`, `collection_error`, `no_tests`,
`no_test_plan`, `timeout`, `tests_required` and `environment_blocked`. They retain
command/cwd, pytest collection counts, output, exit codes, run IDs, audit results,
resolved plan and dependency-image identity. Collection/import failure and zero
collected tests cannot become passing evidence.

The sticky top-right meter shows measured native local input/output totals and
OpenAI input/output totals, including the verifier subset, across browser chats.
Active jobs expose a controller-owned progress run ID so usage can be read from
captured responses before the job finishes. Counts update after responses, not
by guessing tokens while a non-streaming request is running. Unknown/pending
usage is marked partial. Tokens are not dollar estimates. Existing detailed chat
and all-chat accounting remains available below.
