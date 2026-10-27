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

_ALLOWED_FIELDS = frozenset(
    {
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


def submit_profile_turn(server, thread_id, payload):
    """Submit an ``answer`` turn for the selected profile on a thread."""
    payload = _validate_payload(payload)
    name = _resolve_profile_name(payload, server)
    cfg = server.profiles.load(name)

    with server.threads._lock:
        thread = server.threads.get(thread_id)
        pending = server.jobs.get(thread.get("pending_job"))
        if pending is not None:
            status = pending.get("status")
            if status in ("queued", "running"):
                _reject("thread has a pending job in status %r" % status)
        history = server.threads.history(thread_id)
        if len(thread["messages"]) >= _MAX_MESSAGES:
            _reject("thread has reached the maximum message count")

        workflow = cfg.instructions_version
        image, mime, explicit = _resolve_image(server, thread, payload, workflow)
        cfg = _resolve_config(server, cfg, payload, image)

        request = {
            "question": payload.get("question"),
            "history": history,
        }
        for field in ("workspace", "pdf", "page", "dpi", "region", "context_page"):
            if field in payload:
                request[field] = payload[field]
        if image:
            request["image"] = image
        request = validate_browser_request(request, cfg, server.allowed_roots)

        if explicit and image is not None:
            server.threads.update_image(thread_id, image, mime)

        source_run_ids = (
            _gather_source_run_ids(thread["messages"][-len(history):])
            if history
            else []
        )

        metadata = {
            "thread_id": thread_id,
            "question": request["question"],
            "kind": "answer",
            "has_image": image is not None,
            "memory_messages": len(history),
            "source_run_ids": source_run_ids,
            "usage_baseline_model": server.usage_baseline(),
            "profile_name": name,
            "config_hash": digest(canonical(cfg.model_dump(mode="json"))),
            "mode": request["mode"],
            "tools": list(cfg.tools),
            "instructions_version": cfg.instructions_version,
        }

        job_id = server.jobs.submit(request, config=cfg, metadata=metadata)
        server.threads.update(thread_id, pending_job=job_id)
        return job_id
