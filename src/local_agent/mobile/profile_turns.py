"""Profile-driven answer turns for the mobile server.

This module implements ``submit_profile_turn`` which handles the ``answer``
kind when a selected profile is supplied. Legacy review/netlist workflows are
handled elsewhere; this path keeps them separate.
"""

from __future__ import annotations

import base64

from local_agent.mobile import image_mime
from local_agent.mobile.browser_requests import validate_browser_request
from local_agent.mobile.models import Models
from local_agent.storage.blobs import canonical, digest
from local_agent.workspace.options import FIELDS

_ALLOWED_FIELDS = frozenset(
    {
        *FIELDS,
        "question",
        "image",
        "model_id",
        "profile_name",
        "workspace",
        "pdf",
        "page",
        "dpi",
        "region",
        "context_page",
        "execution_mode",
        "run_limit_minutes",
        "n_last_chats",
    }
)

_MAX_MESSAGES = 200

# Circuit workflow versions that must not reuse a saved thread image.
_NO_IMAGE_WORKFLOWS = frozenset({"analog-v1", "analog-v2"})


def _reject(message: str) -> None:
    raise ValueError(message)


def _validate_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        _reject("payload must be a dict")
    unknown = set(payload) - _ALLOWED_FIELDS
    if unknown:
        _reject("unknown payload fields: %s" % ", ".join(sorted(unknown)))
    return payload


def _resolve_profile_name(payload: dict, server) -> str:
    name = payload.get("profile_name", server.default_profile)
    if not isinstance(name, str) or not name:
        _reject("profile_name must be a non-empty string")
    return name


def _resolve_config(server, cfg, payload: dict, image):
    model_id = payload.get("model_id")
    if model_id is None or model_id == "":
        return cfg
    if not isinstance(model_id, str):
        _reject("model_id must be a string")
    prefix = cfg.provider + ":"
    if not model_id.startswith(prefix):
        _reject(
            "model_id %r does not match profile provider %r"
            % (model_id, cfg.provider)
        )
    chosen, item = Models(cfg, server.models.verifier_path).select(
        model_id, has_image=bool(image)
    )
    return chosen


def _resolve_image(server, thread, payload: dict, workflow: str):
    """Return (image, mime, explicit) for the turn.

    ``explicit`` is True when the caller supplied a valid image in the
    payload and it should be persisted via ``update_image``.
    """
    if workflow in _NO_IMAGE_WORKFLOWS and "image" in payload:
        _reject(
            "workflow %s does not accept images; use the PDF "
            "workflow instead" % workflow
        )
    explicit_image = payload.get("image")
    if "image" in payload:
        if not isinstance(explicit_image, str) or not explicit_image:
            _reject("image must be a non-empty base64 string")
        mime = image_mime(base64.b64decode(explicit_image, validate=True))
        return explicit_image, mime, True
    if workflow in _NO_IMAGE_WORKFLOWS:
        return None, None, False
    saved = thread.get("image")
    if saved is not None:
        return saved, None, False
    return None, None, False


def _gather_source_run_ids(messages: list) -> list:
    run_ids = []
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        run_id = message.get("run_id")
        if run_id:
            run_ids.append(run_id)
    return run_ids


def submit_profile_turn(server, thread_id, payload, *, repair_context=None, task_context=None,
                        config_override=None, force_tests=False, extra_metadata=None):
    """Submit an ``answer`` turn for the selected profile on a thread."""
    from local_agent.mobile.task_context import DEFAULT_N_LAST_CHATS, validate_n_last_chats

    payload = _validate_payload(payload)
    n_last_chats = validate_n_last_chats(payload.get("n_last_chats", DEFAULT_N_LAST_CHATS))
    name = _resolve_profile_name(payload, server)
    cfg = config_override or server.profiles.load(name)
    from local_agent.mobile.run_limits import override

    cfg = override(cfg, payload.get("run_limit_minutes"))

    with server.threads._lock:
        if hasattr(server, "loops"):
            active = server.loops.active(thread_id=thread_id, workspace_id=payload.get("continue_workspace_id"))
            if active and (extra_metadata or {}).get("loop_id") != active["loop_id"]:
                _reject("Stop the active loop before submitting another task for this workspace")
        thread = server.threads.get(thread_id)
        pending = server.jobs.get(thread.get("pending_job"))
        if pending is not None:
            status = pending.get("status")
            if status in ("queued", "running"):
                _reject("thread has a pending job in status %r" % status)
        from local_agent.mobile.task_context import ensure_previous_terminal

        ensure_previous_terminal(server, payload.get("continue_workspace_id"))
        history = server.threads.history(thread_id)
        if len(thread["messages"]) >= _MAX_MESSAGES:
            _reject("thread has reached the maximum message count")

        workflow = cfg.instructions_version
        if repair_context is not None or force_tests:
            if cfg.provider != "ollama" or not workflow.startswith("coder-") or not cfg.tools:
                _reject("Select a local coding profile to fix this review")
            image, mime, explicit = None, None, False
        else:
            image, mime, explicit = _resolve_image(server, thread, payload, workflow)
        cfg = _resolve_config(server, cfg, payload, image)
        if repair_context is not None or force_tests:
            if cfg.provider != "ollama":
                _reject("Review repairs require a local model")
            cfg = cfg.model_copy(update={"project_tests": True})
        if "execution_mode" in payload:
            execution_mode = payload["execution_mode"]
            if not isinstance(execution_mode, str) or execution_mode not in {"ephemeral", "persistent"}:
                _reject("execution_mode must be ephemeral or persistent")
            if not cfg.tools:
                _reject("execution_mode requires a tool-enabled profile")
            cfg = cfg.model_copy(update={"execution": cfg.execution.model_copy(
                update={"execution_mode_default": execution_mode}
            )})

        request = {
            "question": payload.get("question"),
            "history": history,
        }
        for field in ("workspace", "pdf", "page", "dpi", "region", "context_page", *FIELDS):
            if field in payload:
                request[field] = payload[field]
        if image:
            request["image"] = image
        request = validate_browser_request(request, cfg, server.allowed_roots)
        if request.get("continue_workspace_id") and repair_context is None:
            from local_agent.mobile.task_context import attach, capture

            task_context = task_context or capture(
                server, thread_id, request["continue_workspace_id"], n_last_chats
            )
            if task_context is not None:
                request = attach(request, task_context)
        if repair_context is not None:
            from local_agent.mobile.repair_controls import attach_repair_context

            request = attach_repair_context(request, repair_context, cfg)

        if explicit and image is not None:
            server.threads.update_image(thread_id, image, mime)

        source_run_ids = (
            _gather_source_run_ids(thread["messages"][-len(history):])
            if history
            else []
        )
        if task_context is not None:
            source_run_ids = list(dict.fromkeys([
                *source_run_ids,
                *(a["run_id"] for a in task_context.get("attempts", []) if a.get("run_id")),
            ]))

        metadata = {
            "thread_id": thread_id,
            "question": request["question"],
            "kind": "answer",
            "has_image": image is not None,
            "memory_messages": len(history),
            "source_run_ids": source_run_ids,
            "usage_baseline_model": server.usage_baseline(),
            "profile_name": name,
            "run_timeout_seconds": cfg.limits.run_timeout_seconds,
            "n_last_chats": n_last_chats,
            "task_context": task_context,
            "config_hash": digest(canonical(cfg.model_dump(mode="json"))),
            "mode": request["mode"],
            "tools": list(cfg.tools),
            "instructions_version": cfg.instructions_version,
        }
        if request["mode"] == "coding":
            metadata["source_workspace"] = request["workspace"]
            if request.get("continue_workspace_id"):
                metadata["workspace_id"] = request["continue_workspace_id"]
        if cfg.tools:
            metadata["execution_mode"] = cfg.execution.execution_mode_default
        if repair_context is not None:
            metadata["repair_review_job_id"] = repair_context["review_job_id"]
            metadata["repair_original_task"] = repair_context["evidence"]["original_task"]
            metadata["question"] = "Fix the findings from this workspace review and rerun the tests."
            if repair_context["evidence"].get("additional_context"):
                metadata["question"] += "\n\nAdditional repair context:\n" + repair_context["evidence"]["additional_context"]
            metadata["source_run_ids"] = list(dict.fromkeys(
                [*repair_context["source_run_ids"], *source_run_ids]
            ))
        if extra_metadata:
            if set(extra_metadata) - {"loop_id", "loop_stage", "loop_deadline"}:
                raise ValueError("Unknown controller job metadata")
            metadata.update(extra_metadata)
            metadata["question"] = "Local loop iteration: repair findings and rerun checks."

        job_id = server.jobs.submit(request, config=cfg, metadata=metadata)
        server.threads.update(thread_id, pending_job=job_id)
        return job_id
