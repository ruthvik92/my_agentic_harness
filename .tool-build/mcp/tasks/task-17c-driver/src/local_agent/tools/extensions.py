"""Pydantic argument schemas for local-agent tool registration and execution.

This module is a pure data-schema layer. It defines the validated argument
objects that a host harness would pass to a sandboxed tool worker. It does
NOT implement worker/executor behavior, image delivery, or PDF rendering;
those concerns live in the host harness.

Intended usage:
  * RegisterToolArgs  - payload for registering a tool (name, description,
    version, code path, and JSON-schema parameters).
  * ExecuteToolArgs   - payload for executing a registered tool with
    arguments and a timeout.
  * ViewImageArgs     - payload for requesting an image from the sandbox
    for delivery to the model.
  * RenderPdfRegionArgs - payload for rendering a normalized region of a
    PDF page at a given DPI.
"""

from __future__ import annotations

import json
import math

from pydantic import (
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from local_agent.contracts import PathText, Record, validate_path

_MAX_SERIALIZED_BYTES = 64 * 1024  # 64 KiB


def _check_serialized_size(payload: dict[str, JsonValue]) -> None:
    """Ensure a JSON-serializable dict fits within the 64 KiB limit and
    contains no NaN/Inf values (which json.dumps would emit as bare
    literals, breaking strict JSON consumers)."""
    try:
        raw = json.dumps(payload, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError) as exc:
        raise ValueError(f'payload contains non-finite or non-serializable values: {exc}') from exc
    if len(raw) > _MAX_SERIALIZED_BYTES:
        raise ValueError(f'serialized payload is {len(raw)} bytes; limit is {_MAX_SERIALIZED_BYTES}')


class RegisterToolArgs(Record):
    """Arguments for registering a tool in the sandbox.

    ``code_path`` must live under ``tools/`` and pass the shared
    ``validate_path`` check (no absolute paths, no traversal).
    ``parameters`` is a JSON-schema-style dict describing the tool's
    accepted arguments; it must serialize to at most 64 KiB of UTF-8 JSON.
    """

    name: str = Field(..., pattern=r'^[a-z][a-z0-9_]{0,63}$')
    description: str = Field(..., min_length=1, max_length=1000)
    version: str = Field(..., min_length=1, max_length=64)
    code_path: PathText
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator('code_path')
    @classmethod
    def _check_code_path(cls, v: str) -> str:
        validate_path(v)
        if not v.startswith('tools/'):
            raise ValueError('code_path must begin with tools/')
        return v

    @model_validator(mode='after')
    def _check_parameters_size(self) -> 'RegisterToolArgs':
        _check_serialized_size(self.parameters)
        return self


class ExecuteToolArgs(Record):
    """Arguments for executing a previously registered tool.

    ``arguments`` is the concrete argument dict passed to the tool; it
    must serialize to at most 64 KiB of UTF-8 JSON. ``timeout_seconds``
    bounds how long the sandbox worker may run the tool.
    """

    name: str = Field(..., pattern=r'^[a-z][a-z0-9_]{0,63}$')
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=60, ge=1, le=300)

    @model_validator(mode='after')
    def _check_arguments_size(self) -> 'ExecuteToolArgs':
        _check_serialized_size(self.arguments)
        return self


class ViewImageArgs(Record):
    """Arguments for requesting an image from the sandbox for delivery
    to the model. ``path`` must be a validated relative path under one of
    the allowed read-only prefixes (project, tools, scratch, outputs).
    """

    path: PathText

    @field_validator('path')
    @classmethod
    def _check_path(cls, v: str) -> str:
        validate_path(v)
        allowed = ('project/', 'tools/', 'scratch/', 'outputs/')
        if not v.startswith(allowed):
            raise ValueError(f'path must begin with one of {allowed}')
        return v


class RenderPdfRegionArgs(Record):
    """Arguments for rendering a normalized region of a PDF page.

    ``pdf`` must be a validated relative path under ``project/``.
    ``region`` is a 4-tuple ``(left, top, right, bottom)`` of finite
    floats in [0, 1] with ``left < right`` and ``top < bottom``.
    ``dpi`` controls the rasterization resolution.
    """

    pdf: PathText
    page: int = Field(..., ge=1)
    region: tuple[float, float, float, float]
    dpi: int = Field(default=600, ge=72, le=1200)

    @field_validator('pdf')
    @classmethod
    def _check_pdf(cls, v: str) -> str:
        validate_path(v)
        if not v.startswith('project/'):
            raise ValueError('pdf must begin with project/')
        return v

    @field_validator('region')
    @classmethod
    def _check_region(cls, v: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        if len(v) != 4:
            raise ValueError('region must be a 4-tuple (left, top, right, bottom)')
        left, top, right, bottom = v
        for x in v:
            if not math.isfinite(x):
                raise ValueError('region values must be finite')
        if not (0 <= left < right <= 1):
            raise ValueError('region requires 0 <= left < right <= 1')
        if not (0 <= top < bottom <= 1):
            raise ValueError('region requires 0 <= top < bottom <= 1')
        return v
