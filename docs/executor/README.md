# Executor Developer Guide

## Responsibilities & Module Map

- **`base.py`**: Legacy `Executor` protocol (dict interface); unused by current paths.
  The separate `LiveExecutor` protocol defines typed dispatch and release for
  live backends, including execution-mode and environment overrides. Docker
  implements it structurally; backend-specific recovery and inspection APIs
  remain outside this protocol.
- **`mock.py`**: `MockExecutor` for scripted M0 simulation and tests; returns fixed data, never opens files or runs code.
- **`docker.py`**: Docker-only executor; controls container lifecycle via the `docker` CLI.
- **`lifecycle.py`**: Host-owned persistent sessions; manages durable state and cleanup.
- **`maintenance.py`**: Host maintenance; runs cleanup sweeps and reaper processes.
- **`build.py`**: Builds the sandbox image; generates `config/sandbox.json`.
- **`worker.py`**: Trusted stdlib-only worker; runs in `python -I -S` mode.
- **`toolkit/`**: Custom registry, safe workspace IO, image/PDF processing:
  - `register.py` / `execute.py`: custom tool registration and execution.
  - `registry_records.py` / `registry_storage.py` / `custom_schema.py`: registry records, storage, and schema.
  - `workspace_io.py`: safe workspace file IO.
  - `image_info.py`: image metadata.
  - `pdf_render.py` / `pdf_source.py` / `pdf_geometry.py` / `render_bounds.py`: PDF rendering, source, geometry, and bounds.

## Host vs Trusted Container Boundary

- **Host**: Manages container lifecycle, security attestation, and durable state.
- **Trusted Worker**: Runs in `python -I -S` mode; no access to host environment.
- **Explicit environment** is passed only to `run_command` and `git_diff`.
- **Toolkit subprocesses** do not receive the host override.
- **Helper snapshots** live in a private temporary directory that is removed
  after execution, including nonzero exits and worker exceptions. Timeouts and
  cancellation remove the whole execution container.
- **Custom-tool argument limits** use the same UTF-8 JSON bytes for validation
  and subprocess stdin: at most 65,536 bytes, with non-finite numbers rejected.

## Durable Dispatch/Result/Release Sequence

- **Dispatch**: The host records a durable dispatch intent and a started attempt *before* invoking Docker.
- **Result**: The host publishes a durable result marker *before* SQLite commits the outcome.
- **Release**: The container is released *after* the SQLite commit. In persistent mode the keeper stays alive across calls; in ephemeral mode the container is removed.
- **Workspace files** survive in either mode; ephemeral mode loses only container-local state (e.g. `/tmp`).

Results report `side_effect_status=unknown` for arbitrary code (`run_command`
and `execute_tool`), even after a nonzero exit. Successful typed mutations
(`write_file`, `patch_file`, `register_tool`, `render_pdf_region`) report
`applied`; unsuccessful mutations conservatively report `unknown` because
partial changes may remain. Read-only tools report `none`.

## Ownership Model

- **Ephemeral**: Container created per invocation; state not preserved.
- **Persistent**: One keeper per workspace; reused across calls.
- **Ownership**: Requires the data-root owner label, mode, workspace, exact container ID, and security attestation. Labels alone are not authority.

## Configuration & Maintenance

- **Config**: See [../executor.md](../executor.md) for `execution_mode_default`, timeouts, and limits.
- **Maintenance**: Use `uv run --locked local-agent containers cleanup` to reconcile idle containers.

## Worker/Image Rebuild Rule

- Rebuild the image when `worker.py`, `pdf_extract.py`, `verify.py`, or any `toolkit/*.py` changes, or when `sandbox/Dockerfile` changes:

  ```bash
  uv run --locked local-agent build-sandbox
  ```

## Testing

- **Unit tests** (no Docker required):

  ```bash
  uv run --locked pytest -q tests/test_worker.py tests/test_worker_execution_options.py \
    tests/test_execution_lifecycle.py tests/test_custom_tools.py tests/test_image_tools.py \
    tests/test_executor_consistency.py
  ```

- **Docker tests** (skipped unless `--docker-image` is supplied):

  ```bash
  uv run --locked pytest -q --docker-image "sha256:<64-hex-image-id>"
  ```

  Replace `<64-hex-image-id>` with the actual pinned image ID from `config/sandbox.json`.

For operational details, see [../executor.md](../executor.md).

> **Note**: The legacy `Executor`/`MockExecutor` dictionary interface is separate
> from `LiveExecutor`, which returns `ExecutionResult`. Replay reads recorded
> results through its own synchronous `CapturedExecutor`; it does not execute tools.
