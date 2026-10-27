"""Browser request validation for the local-agent mobile server.

This module validates browser-originated requests that may target chat,
coding, or circuit (PDF) workflows. It reuses the existing
``mobile.validate_request`` for the question/history/image subset and adds
strict workspace and PDF workflow validation.
"""

import math
import os
from pathlib import Path

from local_agent.mobile import validate_request
from local_agent.workspace.options import FIELDS, validate_options

ALLOWED_FIELDS = {
    *FIELDS,
    "question",
    "history",
    "image",
    "workspace",
    "pdf",
    "page",
    "dpi",
    "region",
    "context_page",
}

CHAT_FIELDS = {"question", "history", "image"}
PDF_FIELDS = {"pdf", "page", "dpi", "region", "context_page"}

CHAT_INSTRUCTIONS = {"phone-v1", "browser-v1"}
CIRCUIT_INSTRUCTIONS = {"analog-v1", "analog-v2"}


def _is_strict_int(value):
    """Return True if value is an int (not bool)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value):
    """Return True if value is a finite int or float (not bool)."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _resolve_strict(path_str):
    """Resolve a path string strictly, raising ValueError on failure."""
    try:
        return Path(path_str).resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Path does not resolve to an existing location: {path_str}") from exc


def _is_within(path, root):
    """Check if path is inside root using Path.relative_to (not string prefix)."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_workspace(workspace_value, allowed_roots):
    """Validate workspace: nonempty string, existing directory, inside allowed_roots."""
    if not isinstance(workspace_value, str):
        raise ValueError("workspace must be a non-empty string")
    if not workspace_value.strip():
        raise ValueError("workspace must be non-empty")
    resolved = _resolve_strict(workspace_value)
    if not resolved.is_dir():
        raise ValueError("workspace must be an existing directory")
    if not allowed_roots:
        raise ValueError("workspace must be inside at least one allowed root")
    for root in allowed_roots:
        try:
            resolved_root = Path(root).resolve(strict=True)
        except (OSError, ValueError):
            continue
        if _is_within(resolved, resolved_root):
            return resolved
    raise ValueError("workspace must be inside at least one allowed root")


def _validate_region(region_value):
    """Validate and normalize region to [left, top, right, bottom]."""
    if not isinstance(region_value, list):
        raise ValueError("region must be a list of four numbers")
    if len(region_value) != 4:
        raise ValueError("region must contain exactly four values")
    for i, v in enumerate(region_value):
        if not _is_finite_number(v):
            raise ValueError(f"region[{i}] must be a finite number")
    left, top, right, bottom = region_value
    if not (0 <= left < right <= 1):
        raise ValueError("region requires 0 <= left < right <= 1")
    if not (0 <= top < bottom <= 1):
        raise ValueError("region requires 0 <= top < bottom <= 1")
    return [left, top, right, bottom]


def _validate_circuit_pdf(value, workspace_resolved):
    """Validate circuit PDF fields and return normalized dict."""
    pdf_value = value.get("pdf")
    if not isinstance(pdf_value, str):
        raise ValueError("pdf must be a non-empty relative path string")
    if not pdf_value.strip():
        raise ValueError("pdf must be non-empty")
    if "\\" in pdf_value:
        raise ValueError("pdf path must not contain backslashes")
    if os.path.isabs(pdf_value):
        raise ValueError("pdf path must be relative")
    parts = Path(pdf_value).parts
    if ".." in parts:
        raise ValueError("pdf path must not contain '..' components")

    pdf_resolved = _resolve_strict(workspace_resolved / pdf_value)
    if not pdf_resolved.is_file():
        raise ValueError("pdf must be an existing regular file")
    if pdf_resolved.suffix.lower() != ".pdf":
        raise ValueError("pdf file must end with .pdf")
    if not _is_within(pdf_resolved, workspace_resolved):
        raise ValueError("pdf must be inside the workspace directory")

    page = value.get("page")
    if page is None:
        raise ValueError("page is required for circuit workflow")
    if not _is_strict_int(page):
        raise ValueError("page must be a positive integer")
    if page < 1:
        raise ValueError("page must be a positive integer")

    dpi = value.get("dpi", 300)
    if not _is_strict_int(dpi):
        raise ValueError("dpi must be an integer")
    if not (72 <= dpi <= 1200):
        raise ValueError("dpi must be between 72 and 1200")

    context_page = value.get("context_page")
    if "context_page" in value:
        if not _is_strict_int(context_page):
            raise ValueError("context_page must be a positive integer")
        if context_page < 1:
            raise ValueError("context_page must be a positive integer")

    region = value.get("region")
    if "region" in value:
        region = _validate_region(region)

    result = {"page": page, "dpi": dpi, "pdf": pdf_value}
    if "context_page" in value:
        result["context_page"] = context_page
    if "region" in value:
        result["region"] = region
    return result


def validate_browser_request(value, config, allowed_roots):
    """Validate and normalize a browser request.

    Args:
        value: Raw request dict.
        config: Server config object with ``instructions_version`` attribute.
        allowed_roots: Iterable of trusted root paths (server constructor values).

    Returns:
        Normalized dict with basic fields, mode, and workflow fields.

    Raises:
        ValueError: On validation errors with safe explanations.
    """
    if not isinstance(value, dict):
        raise ValueError("Request must be a dict")
    unknown = set(value) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {sorted(unknown)}")

    instructions_version = getattr(config, "instructions_version", None)
    if instructions_version in CHAT_INSTRUCTIONS:
        mode = "chat"
    elif instructions_version in CIRCUIT_INSTRUCTIONS:
        mode = "circuit"
    else:
        mode = "coding"

    # Validate the question/history/image subset using existing validator.
    basic_subset = {k: value[k] for k in CHAT_FIELDS if k in value}
    basic = validate_request(basic_subset)

    if mode == "chat":
        for field in {"workspace", *FIELDS} | PDF_FIELDS:
            if field in value:
                raise ValueError(f"chat mode does not accept field: {field}")
        return {"mode": mode, **basic}

    # Coding and circuit both require workspace.
    workspace_resolved = _validate_workspace(value.get("workspace"), allowed_roots)

    if mode == "coding":
        for field in PDF_FIELDS:
            if field in value:
                raise ValueError(f"coding mode does not accept field: {field}")
        return {
            "mode": mode,
            **basic,
            "workspace": str(workspace_resolved),
            **validate_options({key: value[key] for key in FIELDS if key in value}),
        }

    # Circuit mode: reject image, require PDF workflow.
    if any(key in value for key in FIELDS):
        raise ValueError("Workspace task options require coding mode")
    if "image" in value:
        raise ValueError(
            "circuit mode does not accept image; use the PDF workflow instead"
        )

    pdf_fields = _validate_circuit_pdf(value, workspace_resolved)
    return {
        "mode": mode,
        **basic,
        "workspace": str(workspace_resolved),
        **pdf_fields,
    }
