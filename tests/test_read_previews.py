"""Escaping must never hide read cursors, hashes, or retained evidence."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from local_agent.contracts import ExecutionResult, new_id
from local_agent.runtime.tool_results import result_preview
from local_agent.storage.blobs import BlobStore, canonical


def captured(store, payload):
    raw = canonical(payload)
    return ExecutionResult(
        execution_id=new_id("exec"), status="succeeded", exit_code=0,
        output_ref=store.blobs.put(raw), preview=raw.decode()[:16384],
        duration_seconds=0, side_effect_status="none", captured_bytes=len(raw),
        truncated=len(raw.decode()) > 16384,
    )


def test_evidence_preview_is_valid_and_cursor_does_not_skip_escaped_bytes(tmp_path):
    store = SimpleNamespace(blobs=BlobStore(tmp_path / "blobs"))
    data = ("\\\"\t\x01" * 5000).encode()
    ref = store.blobs.put(data)
    offset, parts = 0, []
    while offset < len(data):
        end = min(len(data), offset + 8192)
        result = captured(store, {
            "source_ref": ref, "byte_offset": offset, "total_bytes": len(data),
            "content": data[offset:end].decode(),
            "next_byte_offset": end if end < len(data) else None,
            "truncated": end < len(data),
        })
        original = result.model_dump()
        preview = result_preview(store, result, "read_file")
        page = json.loads(preview["preview"])
        assert len(preview["preview"].encode()) < 16384
        assert page["source_ref"] == ref
        assert page["byte_offset"] == offset
        parts.append(page["content"])
        assert result.model_dump() == original  # Captured evidence/audit prefix is unchanged.
        if page["next_byte_offset"] is None:
            assert not page["truncated"]
            break
        assert page["next_byte_offset"] > offset
        offset = page["next_byte_offset"]
    assert "".join(parts).encode() == data


def test_legacy_line_read_keeps_hash_and_evidence_when_capture_preview_is_invalid(tmp_path):
    store = SimpleNamespace(blobs=BlobStore(tmp_path / "blobs"))
    result = captured(store, {
        "content": "\\\"" * 15000, "content_hash": "sha256:" + "a" * 64,
        "line_offset": 0, "next_line": None,
    })
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.preview)
    summary = result_preview(store, result, "read_file")
    page = json.loads(summary["preview"])
    assert len(summary["preview"].encode()) < 16384
    assert page["content_hash"] == "sha256:" + "a" * 64
    assert page["content_preview_truncated"] is True
    assert result.output_ref in page["continuation_hint"]
    assert summary["evidence_ref"] == result.output_ref


def test_docker_file_read_pages_reach_model_with_hash_and_continuation(sandbox):
    from local_agent.observability.audit import audit
    from local_agent.storage.blobs import digest

    text = '{"task_context":"' + '\\"\t' * 10000 + '"}'

    async def scenario():
        written = await sandbox.execute("write_file", {
            "path": "scratch/task-context.json", "content": text,
        })
        assert written.status == "succeeded"
        offset, parts = 0, []
        while True:
            result = await sandbox.execute("read_file", {
                "path": "scratch/task-context.json", "byte_offset": offset,
            })
            assert result.status == "succeeded"
            assert not result.truncated
            page = json.loads(result_preview(sandbox.store, result, "read_file")["preview"])
            assert page["content_hash"] == digest(text.encode())
            assert len(result.preview.encode()) < 16384
            parts.append(page["content"])
            if page["next_byte_offset"] is None:
                break
            assert page["next_byte_offset"] > offset
            offset = page["next_byte_offset"]
        assert "".join(parts) == text
        assert audit(sandbox.store, sandbox.run_id)["ok"]

    asyncio.run(scenario())


def test_docker_missing_executable_has_a_dependency_preparation_route(sandbox):
    from local_agent.runtime.capability_failures import diagnose

    arguments = {"argv": ["harness_nonexistent_runtime_6dc73a"]}
    result = asyncio.run(sandbox.execute("run_command", arguments))
    assert result.status == "failed"
    failure = diagnose(result.status, result.exit_code, result.preview,
                       result.error, arguments=arguments)
    assert failure["kind"] == "missing_executable"
    assert failure["next_action"] == "prepare_environment"
