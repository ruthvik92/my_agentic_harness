"""Serialization and integrity helpers for registry records (stdlib only)."""
import base64
import binascii
import hashlib
import json

MAX_METADATA = 65536
MAX_CODE = 131072
MAX_RECORD = 524288
FIELDS = ("code_base64", "code_hash", "metadata", "record_hash")


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _b64_decode(value):
    if not isinstance(value, str):
        raise ValueError("code_base64 must be a string")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("invalid base64") from exc


def encode_record(metadata, code):
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a dict")
    if not isinstance(code, (bytes, bytearray)):
        raise ValueError("code must be bytes")
    code = bytes(code)
    if not 1 <= len(code) <= MAX_CODE:
        raise ValueError("code length out of range")
    try:
        meta_bytes = _canonical(metadata)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("metadata not canonicalizable") from exc
    if len(meta_bytes) > MAX_METADATA:
        raise ValueError("metadata too large")
    record = {"metadata": metadata,
              "code_base64": base64.b64encode(code).decode("ascii"),
              "code_hash": "sha256:" + hashlib.sha256(code).hexdigest()}
    record["record_hash"] = "sha256:" + hashlib.sha256(_canonical(record)).hexdigest()
    out = _canonical(record)
    if len(out) > MAX_RECORD:
        raise ValueError("record too large")
    return out


def decode_record(data):
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("data must be bytes")
    data = bytes(data)
    if len(data) > MAX_RECORD:
        raise ValueError("record too large")
    try:
        record = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(record, dict) or set(record) != set(FIELDS):
        raise ValueError("record fields mismatch")
    metadata = record["metadata"]
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a dict")
    try:
        if len(_canonical(metadata)) > MAX_METADATA:
            raise ValueError("metadata too large")
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("metadata not canonicalizable") from exc
    code = _b64_decode(record["code_base64"])
    if not 1 <= len(code) <= MAX_CODE:
        raise ValueError("code length out of range")
    code_hash = record["code_hash"]
    if not isinstance(code_hash, str) or code_hash != "sha256:" + hashlib.sha256(code).hexdigest():
        raise ValueError("code_hash mismatch")
    expected = "sha256:" + hashlib.sha256(_canonical({k: record[k] for k in FIELDS if k != "record_hash"})).hexdigest()
    if record["record_hash"] != expected:
        raise ValueError("record_hash mismatch")
    return {"metadata": metadata, "code": code}
