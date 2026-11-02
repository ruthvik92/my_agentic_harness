# Diagnosis of the two obstacle-game repair runs

Examined the retained tool requests, execution results and model timings for
`run_068242287b4f481284399cf483344003` and
`run_f4b26a5e33b049dd9dffb6f99aa256b2`. Both exhausted their configured
`limits.run_timeout_seconds: 1200` budget. These findings do not certify or repair
the game implementation.

| Symptom | Classification | Recovery |
| --- | --- | --- |
| `Cannot find module '/workspace/project/scratch/find_seed.js'` | Model command-path mistake; the harness also gave misleading dependency advice | A helper written to `scratch/find_seed.js` is at `/workspace/scratch/find_seed.js`. With command `cwd: project`, use that absolute container path. The harness now classifies this as `missing_path`, not `missing_dependency`. |
| `create-only target already exists` | Correct harness overwrite protection; incorrect model arguments | Read the file, then replace with `create_only: false` and its actual `expected_hash`, or use a small hash-checked patch. |
| `ENOENT ... /workspace/js/leaderboard.js` | Model helper computed the wrong project root | Resolve project files under `/workspace/project`. Installing a dependency cannot create the missing project file. The harness now supplies path-specific recovery advice. |
| `document.createElement is not a function` / `listEl.appendChild is not a function` | Incomplete DOM test doubles in the generated Node test | Repair the test setup or exercise the real browser using the staged browser runner. These errors do not establish that Node or a package is absent. |
| Six obstacle-spawn assertions fail | Game implementation or test timing/randomness issue | Inspect source, fixtures and assertions. A failing game assertion is not an environment-install request. The traces alone do not distinguish every game bug from every test bug. |
| No independent controller test result | The run never reached successful completion/verification within its deadline | Model-requested tests remain evidence of their particular command outcomes, not independent certification. |

## Time consumption

The first run recorded 37 completed model responses totaling **1137.24 seconds**;
the second recorded 29 totaling **1180.67 seconds**. That is approximately 95% and
98% of their 1200-second budgets, respectively, before including the final
interrupted model request. Most Docker tool invocations took less than one second.

The page reads were largely legitimate pagination through the source and tests,
not identical repeated first-page reads. Increasing the output-token ceiling does
not make those model requests faster. The timeout is an operator-configurable
budget, not a fixed 20-minute architectural ceiling. This fix does not change it.

## A further harness defect found in the traces

The first run's `scratch/task-context.json` read had a truncated **inner read
preview**. Its JSON content came before its hash and continuation metadata, so a
long escaped line could hide both metadata and valid JSON framing. This was not
a malformed outer model API request; the complete captured output was retained.
The worker also ignored the byte-pagination arguments advertised by the tool.

File reads now honor `byte_limit` and absolute `byte_offset`, bounding the
serialized JSON page so the content hash and continuation fields reach the model
together. A nonzero `byte_offset` takes precedence over `line_offset`. Continue
with `next_byte_offset` when present; `next_line` remains available for line-based
reads. Normal UTF-8 pages preserve character boundaries. Older tool versions keep
their line-only behavior.

Read-only evidence previews also preserve valid JSON and a cursor corresponding
to the content actually shown. For oversized legacy file results, the model gets
the original hash plus a retained-evidence continuation hint. Captured results,
ownership checks and audit evidence are preserved.

## Asking the harness to install a real dependency

The model can call `environment_inventory`, then request `prepare_environment`.
The existing operator network grant and preparation limits still apply.

For a missing Node runtime:

```json
{"reason":"The project test command requires Node","runtimes":["node"]}
```

The classifier uses the actual command arguments to distinguish a worker that
could not launch `node` from a running script that failed to open a file. A
structured executable-launch failure now points to this preparation workflow.

For dependencies declared by an npm project with an existing lock file:

```json
{"reason":"Install the project's locked test dependencies","runtimes":["node"],"dependency_manifests":["project/package.json","project/package-lock.json"]}
```

Python dependencies can use `python_packages` or the supported project manifests;
system tools use `system_packages`. Names and manifests must be established from
the project and inventory, not blindly copied from error output.

Preparation builds/selects a Docker image, records its commands and output, and
preserves workspace files. Replacing an image restarts container processes.
Ordinary commands remain offline. The model can then retry the relevant check;
preparation does not imply that the application's assertions pass.

See [environment preparation](environment-preparation.md) and
[browser verification](browser-verification.md).
