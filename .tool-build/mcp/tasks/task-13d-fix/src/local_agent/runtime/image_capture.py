"""Capture tool-produced images as run artifacts."""

import json

from local_agent.executor.toolkit.workspace_io import read_bytes
from local_agent.runtime.image_info import image_metadata
from local_agent.runtime.image_encoding import attachment_jpeg
from local_agent.runtime.image_records import (
    DESCRIPTOR_MIME, save_artifact, tool_images)
from local_agent.storage.blobs import canonical

_CAPTURE_TOOLS = ("render_pdf_region", "view_image")
_MAX_BYTES = 8 * 1024 * 1024


def _worker_record(result):
    ref = result.stdout_ref or result.output_ref
    if not ref:
        raise ValueError("worker stdout reference missing")
    record = json.loads(canonical(ref))
    if not isinstance(record, dict) or record.get("kind") != "image":
        raise ValueError("worker stdout is not an image record")
    return record


def _match_arguments(worker, execution):
    args = execution.arguments or {}
    if execution.tool == "view_image":
        if worker.get("path") != args.get("path"):
            raise ValueError("view_image path mismatch")
        return
    if not str(worker.get("path", "")).startswith("scratch/images/"):
        raise ValueError("render_pdf_region path outside scratch/images/")
    source = worker.get("source") or {}
    for key in ("pdf", "page", "dpi", "region"):
        if source.get(key) != args.get(key):
            raise ValueError("render_pdf_region source mismatch: %s" % key)
    sha = source.get("sha256")
    if not isinstance(sha, str) or not sha.startswith("sha256:") or len(sha) != 71:
        raise ValueError("render_pdf_region source sha256 malformed")


def _original_bytes(worker, agent, execution):
    run_id = agent.run_id
    execution_id = execution.execution_id
    for record in tool_images(run_id, execution_id):
        if record.get("mime_type") not in ("image/png", "image/jpeg"):
            continue
        if record.get("content_hash") != worker.get("sha256"):
            continue
        if record.get("workspace_origin") != worker.get("path"):
            continue
        return canonical(record["blob_ref"])
    root = str(agent.workspaces.path(execution.workspace_id))
    return read_bytes(worker["path"], root=root, limit=_MAX_BYTES)


def capture_image(agent, execution, result):
    if execution.tool not in _CAPTURE_TOOLS or result.status != "succeeded":
        return None
    existing = tool_images(agent.run_id, execution.execution_id)
    if existing:
        return existing[0]
    worker = _worker_record(result)
    _match_arguments(worker, execution)
    data = _original_bytes(worker, agent, execution)
    meta = image_metadata(data)
    for key in ("mime_type", "width", "height", "sha256"):
        if meta[key] != worker.get(key):
            raise ValueError("image metadata mismatch: %s" % key)
    jpeg = attachment_jpeg(data)
    descriptor = {
        "kind": "tool_image",
        "run_id": agent.run_id,
        "execution_id": execution.execution_id,
        "path": worker["path"],
        "image_ref": save_artifact(data, meta["mime_type"]),
        "image_sha256": worker["sha256"],
        "attachment_ref": save_artifact(jpeg, "image/jpeg"),
        "attachment_mime": "image/jpeg",
        "width": meta["width"],
        "height": meta["height"],
        "source": worker.get("source"),
    }
    save_artifact(canonical(descriptor), DESCRIPTOR_MIME)
    return descriptor
