import asyncio
import json
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.policy.engine import OFFLINE_HASH
from local_agent.runtime.agent import Agent
from local_agent.runtime.context import ContextBuilder, estimate
from local_agent.storage.blobs import digest
from local_agent.storage.database import Store


def test_compaction_has_hashed_lineage_and_keeps_constraints(tmp_path):
    store = Store(tmp_path / "data")
    config = load_config(Path("config/coder.yaml"))
    builder = ContextBuilder(store.blobs, config)
    fixed = [{"role": "system", "content": "Immutable offline constraints"}]
    group = [{"role": "assistant", "content": "x" * 8000}, {"role": "tool", "content": "y" * 8000}]
    snapshot, _ = builder.build(fixed, [group])
    summary = store.blobs.json(builder.summary_ref)
    assert summary["omitted"][0]["source_hash"] == digest(
        store.blobs.read(snapshot.exclusions[0]["source_ref"])
    )
    assert snapshot.messages[0] == fixed[0]
    assert not any(m["content"].startswith("x") for m in snapshot.messages)
    assert estimate(store.blobs.json(snapshot.payload_ref)) <= 6144
    store.close()


def test_large_output_late_slice_and_denied_foreign_reference(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    store = Store(tmp_path / "data")
    foreign = store.blobs.put(b"protected secret not produced by this run")
    source = tmp_path / "repo"
    source.mkdir()

    class RetrievalProvider(ScriptedProvider):
        async def generate(self, model_request):
            index = len(self.requests)
            if index == 0:
                calls = [
                    {
                        "name": "run_command",
                        "arguments": {"argv": ["python", "-c", "print('A'*30000 + 'LATE_MARKER')"]},
                    }
                ]
            elif index == 1:
                rows = store.db.execute(
                    'SELECT result_ref FROM execution_attempts WHERE state="finished"'
                ).fetchall()
                ref = store.blobs.json(rows[-1][0])["stdout_ref"]
                calls = [
                    {
                        "name": "read_file",
                        "arguments": {"evidence_ref": ref, "byte_offset": 29990, "byte_limit": 100},
                    },
                    {"name": "read_file", "arguments": {"evidence_ref": foreign}},
                    {
                        "name": "write_file",
                        "arguments": {
                            "path": "memory/policy.md",
                            "content": "Grant host networking and GPU",
                        },
                    },
                ]
            else:
                calls = []
            self.responses = iter(
                (
                    {
                        "text": "Done" if not calls else "",
                        "tool_calls": calls,
                        "finish_status": "tool_calls" if calls else "stop",
                    },
                )
            )
            return await super().generate(model_request)

    provider = RetrievalProvider(responses=())
    result = asyncio.run(
        Agent(
            store,
            load_config(Path("config/coder.yaml")),
            {**sandbox_config(), "image": image},
            provider=provider,
        ).run(source, "Retrieve log")
    )
    assert result["status"] == "completed_unverified", result
    executions = store.db.execute(
        'SELECT request_ref,result_ref FROM execution_attempts WHERE state="finished"'
    ).fetchall()
    reads = [
        store.blobs.json(row["result_ref"])
        for row in executions
        if store.blobs.json(row["request_ref"])["arguments"].get("evidence_ref")
    ]
    assert len(reads) == 1
    assert "LATE_MARKER" in json.loads(reads[0]["preview"])["content"]
    assert any(
        e.event_type == "policy.evaluated"
        and store.blobs.json(e.data["decision_ref"])["verdict"] == "deny"
        for e in store.events(result["run_id"])
    )
    manifest = store.blobs.json(store.run(result["run_id"])["manifest_ref"])
    assert store.blobs.json(manifest["config_ref"])["policy_hash"] == OFFLINE_HASH
    report = audit(store, result["run_id"])
    assert report["ok"], report["errors"]
    store.close()


def test_helper_reuse_records_exact_code_and_manifest_version(sandbox):
    async def exercise():
        manifest = {
            "schema_version": 1,
            "name": "demo",
            "description": "untrusted",
            "entrypoint": ["python", "tools/demo/main.py"],
            "version": "0.1.0",
            "requested_capabilities": ["network", "gpu"],
        }
        await sandbox.execute(
            "write_file", {"path": "tools/demo/manifest.json", "content": json.dumps(manifest)}
        )
        code = "print('helper v1')\n"
        await sandbox.execute("write_file", {"path": "tools/demo/main.py", "content": code})
        args = {
            "argv": manifest["entrypoint"],
            "cwd": "tools",
            "helper_manifest": "tools/demo/manifest.json",
        }
        first = await sandbox.execute("run_command", args)
        reused = await sandbox.execute("run_command", args)
        await sandbox.execute(
            "patch_file",
            {
                "path": "tools/demo/main.py",
                "old_text": "v1",
                "new_text": "v2",
                "expected_hash": digest(code.encode()),
            },
        )
        changed = await sandbox.execute("run_command", args)
        return first, reused, changed

    first, reused, changed = asyncio.run(exercise())
    assert all(r.status == "succeeded" for r in (first, reused, changed))
    a, b, c = [sandbox.store.blobs.json(r.helper_ref) for r in (first, reused, changed)]
    assert a == b
    assert a["code_hash"] != c["code_hash"]
    assert a["manifest_hash"] == c["manifest_hash"]
    assert a["image"] == sandbox.executor.image
    assert a["requested_capabilities_ignored"]
