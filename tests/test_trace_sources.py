"""Tests for the trace source catalog (local_agent.observability.sources)."""

import json

import pytest

from local_agent.observability.sources import (
    SourceCatalog,
    _normalize,
    _source_id,
)
from local_agent.storage.database import Store


def make_root(tmp_path, name="root"):
    root = tmp_path / name
    (root / "control").mkdir(parents=True)
    store = Store(root)
    store.close()
    return root


def make_run_root(tmp_path, name="runroot"):
    root = tmp_path / name
    run_dir = root / "control" / "runs" / "run_0123456789abcdef"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").touch()
    store = Store(root)
    store.close()
    return root


def test_add_rejects_non_string_project(tmp_path):
    root = make_root(tmp_path)
    catalog = SourceCatalog(tmp_path / "default")
    for bad in (None, 0, False, 123, ["p"]):
        with pytest.raises(ValueError):
            catalog.add(str(root), bad)


def test_add_rejects_blank_project(tmp_path):
    root = make_root(tmp_path)
    catalog = SourceCatalog(tmp_path / "default")
    with pytest.raises(ValueError):
        catalog.add(str(root), "   ")


def test_add_rejects_overlong_project(tmp_path):
    root = make_root(tmp_path)
    catalog = SourceCatalog(tmp_path / "default")
    with pytest.raises(ValueError):
        catalog.add(str(root), "x" * 121)


def test_add_new_source_persists(tmp_path):
    root = make_root(tmp_path, "alpha")
    catalog = SourceCatalog(tmp_path / "default")
    result = catalog.add(str(root), "alpha-proj")
    assert result["project"] == "alpha-proj"
    assert result["root"] == str(root)
    assert result["id"] == _source_id(root)
    reopened = SourceCatalog(tmp_path / "default")
    rows = {s["id"]: s for s in reopened.sources()}
    assert rows[_source_id(root)]["project"] == "alpha-proj"


def test_add_existing_root_rename_returns_new_project(tmp_path):
    root = make_root(tmp_path, "beta")
    catalog = SourceCatalog(tmp_path / "default")
    catalog.add(str(root), "old-name")
    result = catalog.add(str(root), "new-name")
    assert result["project"] == "new-name"
    reopened = SourceCatalog(tmp_path / "default")
    rows = {s["id"]: s for s in reopened.sources()}
    assert rows[_source_id(root)]["project"] == "new-name"


def test_add_existing_root_without_project_keeps_old(tmp_path):
    root = make_root(tmp_path, "gamma")
    catalog = SourceCatalog(tmp_path / "default")
    catalog.add(str(root), "kept")
    result = catalog.add(str(root))
    assert result["project"] == "kept"


def test_add_invalid_location_creates_no_db(tmp_path):
    missing = tmp_path / "does-not-exist"
    catalog = SourceCatalog(tmp_path / "default")
    with pytest.raises(ValueError):
        catalog.add(str(missing), "p")
    assert not (missing / "control" / "agent.db").exists()
    with pytest.raises(ValueError):
        catalog.add(str(tmp_path / "plainfile"), "p")
    assert not (tmp_path / "plainfile" / "control" / "agent.db").exists()


def test_add_unsupported_file_location(tmp_path):
    root = tmp_path / "root"
    (root / "control").mkdir(parents=True)
    (root / "control" / "agent.db").touch()
    catalog = SourceCatalog(tmp_path / "default")
    with pytest.raises(ValueError):
        catalog.add(str(root / "control" / "other.db"), "p")


def test_normalization_from_events_file(tmp_path):
    root = make_run_root(tmp_path)
    catalog = SourceCatalog(tmp_path / "default")
    events = root / "control" / "runs" / "run_0123456789abcdef" / "events.jsonl"
    result = catalog.add(str(events), "from-events")
    assert result["root"] == str(root)
    assert result["project"] == "from-events"


def test_normalization_from_control_dir(tmp_path):
    root = make_root(tmp_path, "ctl")
    catalog = SourceCatalog(tmp_path / "default")
    result = catalog.add(str(root / "control"), "ctl-proj")
    assert result["root"] == str(root)


def test_normalization_from_agent_db(tmp_path):
    root = make_root(tmp_path, "db")
    catalog = SourceCatalog(tmp_path / "default")
    result = catalog.add(str(root / "control" / "agent.db"), "db-proj")
    assert result["root"] == str(root)


def test_malformed_catalog_raises(tmp_path):
    default = tmp_path / "default"
    (default / "control").mkdir(parents=True)
    (default / "control" / "agent.db").touch()
    (default / "control" / "trace-sources.json").write_text(
        json.dumps({"not": "a list"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="malformed"):
        SourceCatalog(default)


def test_malformed_catalog_entry_raises(tmp_path):
    default = tmp_path / "default"
    (default / "control").mkdir(parents=True)
    (default / "control" / "agent.db").touch()
    (default / "control" / "trace-sources.json").write_text(
        json.dumps([{"root": "relative/path", "project": "p", "id": "x"}]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="malformed"):
        SourceCatalog(default)


def test_unavailable_other_root_error_isolated(tmp_path):
    good = make_root(tmp_path, "good")
    bad = tmp_path / "bad"
    (bad / "control").mkdir(parents=True)
    bad_store = Store(bad)
    bad_store.close()
    catalog = SourceCatalog(tmp_path / "default")
    catalog.add(str(good), "good-proj")
    catalog.add(str(bad), "bad-proj")
    (bad / "control" / "agent.db").write_bytes(b"not a sqlite file")
    rows = {s["root"]: s for s in catalog.sources()}
    assert "error" not in rows[str(good)]
    assert "error" in rows[str(bad)]


def test_normalize_control_runs_dir(tmp_path):
    root = make_run_root(tmp_path, "runsdir")
    assert _normalize(str(root / "control" / "runs")) == root


def test_normalize_run_dir(tmp_path):
    root = make_run_root(tmp_path, "rundir")
    run_id = next((root / "control" / "runs").iterdir()).name
    assert _normalize(str(root / "control" / "runs" / run_id)) == root


def test_rename_failure_rolls_back(tmp_path, monkeypatch):
    root = make_root(tmp_path, "delta")
    catalog = SourceCatalog(tmp_path / "default")
    catalog.add(str(root), "before")
    monkeypatch.setattr(catalog, "_persist", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        catalog.add(str(root), "after")
    rows = {s["id"]: s for s in catalog.sources()}
    assert rows[_source_id(root)]["project"] == "before"
    reopened = SourceCatalog(tmp_path / "default")
    rows = {s["id"]: s for s in reopened.sources()}
    assert rows[_source_id(root)]["project"] == "before"


def test_list_runs_empty(tmp_path):
    root = make_root(tmp_path, "runs")
    catalog = SourceCatalog(tmp_path / "default")
    catalog.add(str(root), "runs-proj")
    assert catalog.list_runs() == []
