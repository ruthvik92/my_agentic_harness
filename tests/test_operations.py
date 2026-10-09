import asyncio
from pathlib import Path

import pytest

from local_agent.evaluation.report import rate, report
from local_agent.observability.audit import audit
from local_agent.runtime.loop import simulate
from local_agent.runtime.replay import recorded_replay
from local_agent.storage.bundles import backup, export_run, verify_bundle
from local_agent.storage.database import Store


def test_private_exports_backup_and_replay(tmp_path):
    store = Store(tmp_path / "source")
    first = asyncio.run(simulate(store))["run_id"]
    second = asyncio.run(simulate(store))["run_id"]
    metadata = tmp_path / "metadata"
    export_run(store, first, metadata)
    assert verify_bundle(metadata)["capture_mode"] == "metadata-only"
    assert not (metadata / "control").exists()
    full = tmp_path / "full"
    export_run(store, first, full, include_evidence=True)
    assert verify_bundle(full)["capture_mode"] == "full"
    restored = Store(full, readonly=True)
    assert audit(restored, first)["ok"]
    assert recorded_replay(restored, first)["real_tools_executed"] == 0
    with pytest.raises(ValueError, match="unknown run"):
        restored.run(second)
    restored.close()
    complete = tmp_path / "backup"
    backup(store, complete)
    restored = Store(complete, readonly=True)
    assert audit(restored, first)["ok"] and audit(restored, second)["ok"]
    restored.close()
    (metadata / "report.json").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        verify_bundle(metadata)
    store.close()


def test_metrics_keep_unknown_usage_null_and_ids_out_of_labels(tmp_path):
    import json

    store = Store(tmp_path / "source")
    run_id = asyncio.run(simulate(store))["run_id"]
    result = report(store, run_id)
    assert result["status"] == "completed_unverified" and not result["verified"]
    assert all(m["decode_tokens_per_second"] is None for m in result["models"])
    assert rate(None, 1) is None and rate(1, 0) is None
    assert rate(4, 2_000_000_000) == 2
    metrics = json.loads(result["otel_metrics"])
    assert run_id not in str(metrics)
    store.close()


@pytest.mark.parametrize(
    "suite,folder,filename,old,new",
    [
        ("mean", "mean_repo", "statistics_utils.py", "//", "/"),
        (
            "clamp",
            "clamp_repo",
            "bounds.py",
            "min(max(value, upper), lower)",
            "min(max(value, lower), upper)",
        ),
    ],
)
def test_held_out_verifiers_fail_then_pass(tmp_path, request, suite, folder, filename, old, new):
    from local_agent.config import load_config
    from local_agent.doctor import sandbox_config
    from local_agent.models.scripted import ScriptedProvider
    from local_agent.runtime.agent import Agent
    from local_agent.storage.blobs import digest

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    root = Path(__file__).parent / "fixtures" / folder
    store = Store(tmp_path / "data")
    provider = ScriptedProvider(
        responses=(
            {"text": "Done prematurely", "tool_calls": [], "finish_status": "stop"},
            {
                "text": "Repair",
                "tool_calls": [
                    {
                        "name": "patch_file",
                        "arguments": {
                            "path": "project/" + filename,
                            "old_text": old,
                            "new_text": new,
                            "expected_hash": digest((root / filename).read_bytes()),
                        },
                    }
                ],
                "finish_status": "tool_calls",
            },
            {"text": "Fixed", "tool_calls": [], "finish_status": "stop"},
        )
    )
    result = asyncio.run(
        Agent(
            store,
            load_config(Path("config/coder.yaml")),
            {**sandbox_config(), "image": image},
            provider=provider,
        ).run(root, "Fix", verify_fixture=suite)
    )
    assert result["status"] == "verified", result
    assert [
        e.data["passed"]
        for e in store.events(result["run_id"])
        if e.event_type == "completion.verified"
    ] == [False, True]
    assert audit(store, result["run_id"])["ok"]
    exported = tmp_path / "live-export"
    export_run(store, result["run_id"], exported, include_evidence=True)
    restored = Store(exported, readonly=True)
    report = audit(restored, result["run_id"])
    assert report["ok"], report["errors"]
    restored.close()
    store.close()


def test_evidence_quota_counts_unique_content_and_fails_closed(tmp_path):
    from local_agent.storage.blobs import BlobStore

    blobs = BlobStore(tmp_path / "blobs")
    blobs.begin_budget(10)
    blobs.put(b"12345")
    blobs.put(b"12345")
    assert blobs.budget == 5
    with pytest.raises(OSError, match="budget exhausted"):
        blobs.put(b"123456")
    from local_agent.storage.blobs import digest

    assert not blobs.path("blob://" + digest(b"123456")[7:]).exists()
    blobs.end_budget()
    blobs.put(b"123456")
