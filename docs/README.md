# Documentation index

Start with one guide for the task at hand. The user manual owns the browser
workflow; reference pages own settings and technical detail. Historical plans and
run-specific findings are kept separately.

## Learn and use the harness

| Guide | What it owns |
| --- | --- |
| [User manual](functional-manual.md) | New task → continue/repair → check → review → merge; choosing a version and understanding previews |
| [CLI quick start](tldr.md) | Installation and a first command-line run |
| [Key concepts and glossary](key-concepts.md) | Runs, jobs, workspaces, evidence, verification, and context terminology |
| [Harness characteristics and implementation](harness-characteristics.md) | The ten core characteristics, their implementation/docs, limitations, and the local-output/paid-output objective |
| [Browser reference](browser.md) | Pairing, selectors, controls, limits, and saved state |
| [Reviews and data sent to models](reviews.md) | Review types, shared code/chat/test evidence, exact context caps, and token accounting |
| [Circuit investigation](circuits.md) | PDF schematics, image evidence, and draft netlists |

## Configure, verify, and troubleshoot

| Reference | What it owns |
| --- | --- |
| [Configuration](configs.md) | Profiles, fields, provider metadata, and token-limit validation |
| [Git workspaces](git-workspaces.md) | Branch versus worktree, data-root location, Docker mounts, continuation, and merge rules |
| [Project tests](project-tests.md) | Test plans/contracts, automatic checks, dependencies, and result classifications |
| [Browser verification](browser-verification.md) | Actual click/key/persistence checks and browser-runner capabilities |
| [Environment preparation](environment-preparation.md) | Inventory, runtime/package requests, images, and provisioning grants |
| [Local repair and review policy](local-repair-reliability.md) | Repair milestones, recovery allowances, review eligibility, and findings |
| [Model capability probes](model-capability-probes.md) | How supported model/tool combinations are checked |
| [Execution and isolation](executor.md) | Why choose ephemeral/persistent containers, container `/tmp`, resource limits, and cleanup |
| [Traces and outcomes](traces.md) | Inspecting events, statuses, audits, replay, and evidence |
| [Runtime data](runtime-data.md) | Finding chat/job/run/workspace records and retained artifacts |
| [Operations](operations.md) | Cancellation, recovery, backups, and evaluation procedures |

## Develop and integrate

| Reference | What it owns |
| --- | --- |
| [Implementation guide](guide.md) | Runtime flow, provider transports, tool authority, and developer commands |
| [Architecture](architecture.md) | Durability, authorization, execution, and recovery boundaries |
| [Context and helpers](context-helpers.md) | Request construction, trimming, evidence retrieval, and helper execution |
| [Executor developer guide](executor/README.md) | Executor source modules and their responsibilities |
| [MCP integration](mcp.md) | External harness tools and client integration |
| [Repository layout](repository-layout.md) | Source, examples, external development data, and archive locations |
| [Evaluation results](evaluation-results.md) | Recorded measurements and their limitations |

## History and compatibility

[Development history](history/README.md) contains build plans, the older phone
interface guide, and dated run investigations. Those pages describe their recorded
version, not necessarily today's behavior. Old entry URLs remain as pointers:
[phone compatibility](phone.md), [game-run diagnosis](run-failure-diagnosis.md), and
[repair implementation plan](local-repair-reliability-plan.md).

[Progress.md](../Progress.md) is the work/validation log. It is not a setup guide.

## Keeping documentation consistent

Update the page that owns a topic, then link to it from other guides. Keep the
user manual focused on decisions and actions, the browser reference focused on
controls, and the implementation guide focused on source behavior. Avoid copying
numeric limits into several guides. Label examples and configuration-dependent
values; cite source paths for exact limits. Keep old entry paths usable when a
page moves. Put completed plans and run-specific case studies under `history/`.
