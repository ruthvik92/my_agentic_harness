import json
import os
import socket

import pytest

from local_agent.executor import worker
from local_agent.tools.registry import normalize
from local_agent.workspace.manager import Workspaces


@pytest.fixture
def root(tmp_path, monkeypatch):
    for name in worker.ALLOWED:
        (tmp_path / name).mkdir()
    monkeypatch.setattr(worker, "ROOT", str(tmp_path))
    return tmp_path


def operation(name, args):
    return worker.operate(name, normalize(name, args)["arguments"])


def test_write_patch_read_preconditions(root):
    result = operation("write_file", {"path": "project/nested/a.py", "content": "old\n"})
    assert operation("read_file", {"path": "project/nested/a.py"})["content"] == "old\n"
    with pytest.raises(ValueError, match="already exists"):
        operation("write_file", {"path": "project/nested/a.py", "content": "oops"})
    operation(
        "patch_file",
        {
            "path": "project/nested/a.py",
            "old_text": "old",
            "new_text": "new",
            "expected_hash": result["content_hash"],
        },
    )
    with pytest.raises(ValueError, match="conflict"):
        operation(
            "patch_file",
            {
                "path": "project/nested/a.py",
                "old_text": "new",
                "new_text": "bad",
                "expected_hash": result["content_hash"],
            },
        )


def test_traversal_symlinks_special_files_are_rejected(root, tmp_path):
    secret = root / "sentinel"
    secret.write_text("host sentinel")
    (root / "project" / "link").symlink_to(secret)
    (root / "project" / "dir").symlink_to(root, target_is_directory=True)
    for path in ("project/link", "project/dir/sentinel", "project/../../sentinel"):
        with pytest.raises((ValueError, OSError)):
            operation("read_file", {"path": path})
    os.mkfifo(root / "project" / "fifo")
    with pytest.raises(ValueError, match="regular"):
        operation("read_file", {"path": "project/fifo"})
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.bind(str(root / "project" / "socket"))
        with pytest.raises(OSError):
            operation("read_file", {"path": "project/socket"})
    finally:
        sock.close()
    assert secret.read_text() == "host sentinel"


def test_listing_search_pagination(root):
    for index in range(5):
        operation("write_file", {"path": f"project/{index}.txt", "content": "needle\n"})
    page = operation("list_files", {"limit": 2})
    assert page["truncated"] and page["next_offset"] == 2
    assert len(operation("list_files", {"limit": 5})["matches"]) == 5
    assert len(operation("search_files", {"query": "needle", "limit": 3})["matches"]) == 3


@pytest.mark.parametrize("text", [
    '{"context":"' + '\\"\t\x01' * 7000 + '"}',
    "é🙂" * 7000,
    "first\n" + "x" * 22000 + "\nlast\n",
])
def test_long_file_pages_keep_metadata_and_reassemble_without_loss(root, text):
    data = text.encode("utf-8")
    (root / "scratch" / "context.json").write_bytes(data)
    offset, line, pieces = 0, 0, []
    while True:
        page = operation("read_file", {
            "path": "scratch/context.json", "line_offset": line,
            "byte_offset": offset, "line_limit": 2,
        })
        # The whole JSON object, including hash and continuation, reaches the model.
        encoded = json.dumps(page, ensure_ascii=False).encode("utf-8") + b"\n"
        assert len(encoded) < 16384
        assert page["content_hash"] == worker.content_hash(data)
        assert page["byte_offset"] == offset
        assert page["total_bytes"] == len(data)
        pieces.append(page["content"])
        if page["next_byte_offset"] is None:
            assert page["next_line"] is None
            assert not page["truncated"]
            break
        assert page["next_byte_offset"] > offset
        offset, line = page["next_byte_offset"], page["next_line"]
    assert "".join(pieces) == text


def test_absolute_byte_cursor_takes_precedence_and_preserves_legacy_reads(root):
    (root / "project" / "page.txt").write_text("one\ntwo\nthree\n")
    page = operation("read_file", {
        "path": "project/page.txt", "line_offset": 2, "byte_offset": 4, "byte_limit": 4,
    })
    assert page["content"] == "two\n"
    assert page["next_byte_offset"] == 8
    assert page["next_line"] == 2
    old = normalize("read_file", {"path": "project/page.txt", "line_offset": 1,
                                  "line_limit": 1}, version=1)
    assert worker.operate("read_file", old["arguments"]) == {
        "content": "two\n", "content_hash": worker.content_hash(b"one\ntwo\nthree\n"),
        "line_offset": 1, "next_line": 2,
    }


def test_workspace_copy_rejects_links(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a").write_text("ok")
    manager = Workspaces(tmp_path / "data")
    _, path = manager.create(source)
    assert (path / "project" / "a").read_text() == "ok"
    (source / "link").symlink_to("a")
    with pytest.raises(ValueError, match="symlinks"):
        manager.create(source)


def test_workspace_copy_excludes_archives_and_caches_without_touching_originals(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("print('project')\n")
    for name in (
        ".browser-build", ".tool-build", ".config-cleanup", ".config-consolidation",
        ".executor-review", ".executor-fixes", ".ruff_cache",
    ):
        (source / name).mkdir()
        (source / name / "outside").symlink_to(tmp_path / "nonexistent")
    manager = Workspaces(tmp_path / "data")
    _, path = manager.create(source)
    assert sorted(p.name for p in (path / "project").iterdir()) == ["main.py"]
    assert (path / "project/main.py").read_text() == "print('project')\n"
    assert (source / ".executor-review/outside").is_symlink()
