"""Minimal JSON-schema subset validator (stdlib only)."""
import json
import math
import re

ROOT_KEYS = {"type", "properties", "required", "additionalProperties", "description", "title"}
PROP_KEYS = {"type", "description", "title"}
TYPES = {"string", "number", "integer", "boolean"}
MAX_PROPS = 32
MAX_ARGS_BYTES = 65536
MAX_META_LEN = 1000
PROP_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _fail(msg):
    raise ValueError(msg)


def _check_meta(value, label):
    if not isinstance(value, str):
        _fail(f"{label} must be a string")
    if len(value) > MAX_META_LEN:
        _fail(f"{label} must be at most {MAX_META_LEN} characters")


def validate_schema(schema):
    """Validate a schema dict; raise ValueError on any violation."""
    if not isinstance(schema, dict):
        _fail("schema must be a dict")
    extra = set(schema) - ROOT_KEYS
    if extra:
        _fail(f"unsupported root keys: {sorted(extra)}")
    if schema.get("type", "object") != "object":
        _fail("root type must be 'object'")
    for meta_key in ("description", "title"):
        if meta_key in schema:
            _check_meta(schema[meta_key], f"root {meta_key}")
    props = schema.get("properties", {})
    if not isinstance(props, dict):
        _fail("properties must be a dict")
    if len(props) > MAX_PROPS:
        _fail(f"properties must have at most {MAX_PROPS} fields")
    for name, prop in props.items():
        if not isinstance(name, str) or not PROP_NAME_RE.fullmatch(name):
            _fail(f"property name {name!r} must match ^[a-z][a-z0-9_]{{0,63}}$")
        if not isinstance(prop, dict):
            _fail(f"property {name!r} must be a dict")
        extra = set(prop) - PROP_KEYS
        if extra:
            _fail(f"property {name!r} has unsupported keys: {sorted(extra)}")
        for meta_key in ("description", "title"):
            if meta_key in prop:
                _check_meta(prop[meta_key], f"property {name!r} {meta_key}")
        ptype = prop.get("type")
        if not isinstance(ptype, str) or ptype not in TYPES:
            _fail(f"property {name!r} type must be one of {sorted(TYPES)}")
    required = schema.get("required", [])
    if not isinstance(required, list):
        _fail("required must be a list")
    seen = set()
    for name in required:
        if not isinstance(name, str) or name not in props:
            _fail(f"required entry {name!r} must be a declared property name")
        if name in seen:
            _fail(f"duplicate required entry {name!r}")
        seen.add(name)
    if schema.get("additionalProperties", False) is not False:
        _fail("additionalProperties must be false")
    return None


def validate_arguments(schema, args):
    """Validate args against schema; raise ValueError on violation."""
    validate_schema(schema)
    if not isinstance(args, dict):
        _fail("args must be a dict")
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    for name in args:
        if name not in props:
            _fail(f"undeclared argument {name!r}")
    for name in required:
        if name not in args:
            _fail(f"missing required argument {name!r}")
    for name, value in args.items():
        ptype = props[name]["type"]
        if ptype == "boolean":
            if not isinstance(value, bool):
                _fail(f"argument {name!r} must be boolean")
        elif ptype == "string":
            if not isinstance(value, str):
                _fail(f"argument {name!r} must be string")
        elif ptype in ("number", "integer"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _fail(f"argument {name!r} must be {ptype}")
            if ptype == "integer" and not isinstance(value, int):
                _fail(f"argument {name!r} must be integer")
            if isinstance(value, float) and not math.isfinite(value):
                _fail(f"argument {name!r} must be finite")
    try:
        payload = json.dumps(args, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        _fail(f"args not JSON-serializable: {exc}")
    if len(payload) > MAX_ARGS_BYTES:
        _fail(f"serialized args exceed {MAX_ARGS_BYTES} bytes")
    return None
