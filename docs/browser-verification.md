# Browser verification and capability recovery

The harness provides one interactive browser runner for coding agents, paid
reviewers and independent controller checks. Models still choose and author the
project's regression scenarios. The runner supplies browser mechanics so each
model does not have to discover WebSocket libraries or rewrite browser setup.

## What the inventory establishes

`environment_inventory` inspects the selected immutable image. Coding runs receive
it before their first turn; workspace reviews run a controller preflight too.

- `capabilities.browser_dom_dump` reports launcher availability. Its `tested: false`
  explicitly means this is discovery, rather than executed page verification.
- `capabilities.browser_interaction.available` becomes true only after an isolated
  offline self-test starts Chromium, types into an input, sends keyboard events,
  clicks a button, reloads and checks persisted localStorage.
- Successful interaction probes are cached by image, runner source hash and
  execution settings. Cached reports are identified. Transient failures are not
  cached as permanent absence, and installed binaries alone never establish readiness.

Probe evidence and the runner source are retained in the run ledger. Resuming a
run restores its recorded helper version. Fresh independent check copies stage
the host's helper again; edits to an agent's tools copy do not carry into replay.

If interaction support is missing, a coding agent with preparation permission can
request `prepare_environment` with `capabilities: ["browser_interaction"]`.
This uses the existing bounded preparation path, installs Chromium and requires
its interaction self-test to pass before selecting the image. Existing
`headless_browser` requests remain supported. Reviewers report missing tooling;
they do not install dependencies or edit the candidate.

## Authoring project browser regressions

Commit a plan such as `tests/browser-flow.json`:

```json
{
  "version": 1,
  "steps": [
    {"action": "navigate", "url": "file:///workspace/project/index.html"},
    {"action": "click", "selector": "#start"},
    {"action": "wait", "expression": "document.querySelector('#name') !== null"},
    {"action": "fill", "selector": "#name", "value": "Ada"},
    {"action": "press", "selector": "#name", "key": " "},
    {"action": "assert", "expression": "document.querySelector('#name').value === 'Ada '"}
  ]
}
```

Selectors and expectations must match the project. A test must arrange its own
state, including any game-over condition, and explicitly assert required behavior.
This example is a plan format illustration, not an executed game acceptance test.

Inside the sandbox, run:

```text
python /workspace/tools/harness_browser_test.py --plan /workspace/project/tests/browser-flow.json --timeout 30
```

The paid reviewer can select this exact command alongside the project's other
suites. Independent controller replay uses a fresh copy of the same candidate.
A scratch plan can aid inspection, but commit the regression before declaring it
as a replayable candidate test. No browser helper automatically generates meaningful
coverage or establishes that a game is correct.

`--self-test` checks the runner and browser independently of the project. `--help`
describes the plan schema. Actions include `navigate`, `reload`, `init` (script
before subsequent documents), `evaluate`, `wait`, `assert`, `click`, `fill` and
`press`; optional `name` labels each step. Assertions require exactly JavaScript
`true`. Use a literal space for the Space key. Native CDP input dispatch tests
keyboard handlers as well as input values; filling an input alone does not prove
that keyboard shortcuts are handled correctly.

Each invocation starts a fresh browser profile. Persistence assertions must save
and reload within the same plan. A single deadline covers startup and all steps;
there are at most 100 steps and plans are limited to 1 MiB. Browser processes are
owned and cleaned up, including by a watchdog if the runner is killed. Execution
remains offline under the configured CPU, memory and PID limits. The runner uses
Chromium's debugging pipe and Python's standard library; Node `ws`, Playwright and
Selenium are not required. Projects requiring a web server must arrange that
server inside their test's lifecycle; the runner does not start project services.

Output is structured JSON with per-step results and an overall status. Exit zero
means every step completed. Missing Chromium, assertion failure, timeout and invalid
plan remain distinct nonzero results. Controller reports label missing tooling as
`environment_blocked`, invalid plans as `collection_error`, timeouts as `timeout`
and assertions as `test_failed`. A successful DOM dump verifies initial structure,
rather than interactive behavior.

## Recovery after a failed command

Command feedback distinguishes missing dependencies/executables, missing paths,
assertion failures, timeouts, output limits and actual process-limit evidence.
A generic SIGKILL does not prove PID exhaustion. Dependency diagnostics suggest
inspection of project manifests and approved preparation; stderr never authorizes
installing an arbitrary package. Assertions direct attention to tests and code;
timeouts direct attention to bounded waits, readiness and child cleanup.

Within a run, unavailable dependencies are retained as controller-owned evidence
across context trimming and resume. An identical command in the same directory,
image and measured source state is skipped with `executed: false` and its original
evidence, rather than starting another futile process. This is an environment
blocker, never a passing test. Changed source/image/arguments permit a new attempt.
Successful workspace mutations, preparation and non-probe commands conservatively
invalidate this memory because they can change dependencies. Pure version/import
probes do not erase it. If source state cannot be measured safely, execution is not
suppressed on that basis. Skips still consume tool attempts and count toward the
existing bounded repair guard; they cannot create an unbounded free retry loop.

This memory is scoped to the run, not a permanent global missing-package cache.
Recovery never silently replays a mutation, raises resource limits or schedules a
paid rescue. A model can still stall; work and evidence remain available for a
concrete follow-up task. See [local repair reliability](local-repair-reliability.md)
and [environment preparation](environment-preparation.md).
