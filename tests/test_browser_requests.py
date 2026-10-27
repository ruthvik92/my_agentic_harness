"""Validation checks for browser-originated chat, coding, and circuit requests."""

import base64
from types import SimpleNamespace

import pytest
from test_mobile_runtime import screenshot

from local_agent.mobile.browser_requests import validate_browser_request


def config(version):
    return SimpleNamespace(instructions_version=version)


def png_b64():
    return base64.b64encode(screenshot("PNG")).decode()


def make_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def make_pdf(workspace):
    pdf = workspace / "schematic.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    return pdf


# ---------------------------------------------------------------------------
# Chat mode (phone-v1 / browser-v1): no workspace required.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["phone-v1", "browser-v1"])
def test_chat_mode_accepts_question_without_workspace(tmp_path, version):
    result = validate_browser_request(
        {"question": "hello"}, config(version), [tmp_path]
    )
    assert result["mode"] == "chat"
    assert result["question"] == "hello"
    assert result["history"] == []
    assert "workspace" not in result


@pytest.mark.parametrize("version", ["phone-v1", "browser-v1"])
def test_chat_mode_accepts_history_and_image(tmp_path, version):
    result = validate_browser_request(
        {
            "question": "hi",
            "history": [{"role": "user", "content": "earlier"}],
            "image": png_b64(),
        },
        config(version),
        [tmp_path],
    )
    assert result["mode"] == "chat"
    assert result["history"] == [{"role": "user", "content": "earlier"}]
    assert result["image"] == png_b64()


@pytest.mark.parametrize("version", ["phone-v1", "browser-v1"])
def test_chat_mode_rejects_workspace(tmp_path, version):
    workspace = make_workspace(tmp_path)
    with pytest.raises(ValueError):
        validate_browser_request(
            {"question": "hi", "workspace": str(workspace)},
            config(version),
            [tmp_path],
        )


@pytest.mark.parametrize("version", ["phone-v1", "browser-v1"])
@pytest.mark.parametrize("field", ["pdf", "page", "dpi", "region", "context_page"])
def test_chat_mode_rejects_pdf_fields(tmp_path, version, field):
    with pytest.raises(ValueError):
        validate_browser_request(
            {"question": "hi", field: "x"}, config(version), [tmp_path]
        )


# ---------------------------------------------------------------------------
# Coding mode (coder-v3): workspace required, PDF fields rejected.
# ---------------------------------------------------------------------------


def test_coding_mode_requires_workspace(tmp_path):
    with pytest.raises(ValueError):
        validate_browser_request({"question": "hi"}, config("coder-v3"), [tmp_path])


def test_coding_mode_returns_normalized_workspace(tmp_path):
    workspace = make_workspace(tmp_path)
    result = validate_browser_request(
        {"question": "hi", "workspace": str(workspace)},
        config("coder-v3"),
        [tmp_path],
    )
    assert result["mode"] == "coding"
    assert result["workspace"] == str(workspace.resolve())


@pytest.mark.parametrize("field", ["pdf", "page", "dpi", "region", "context_page"])
def test_coding_mode_rejects_pdf_fields(tmp_path, field):
    workspace = make_workspace(tmp_path)
    with pytest.raises(ValueError):
        validate_browser_request(
            {"question": "hi", "workspace": str(workspace), field: "x"},
            config("coder-v3"),
            [tmp_path],
        )


# ---------------------------------------------------------------------------
# Circuit mode (analog-v2): existing relative PDF, positive page, dpi 72-1200.
# ---------------------------------------------------------------------------


def test_circuit_mode_accepts_minimal_pdf_request(tmp_path):
    workspace = make_workspace(tmp_path)
    make_pdf(workspace)
    result = validate_browser_request(
        {
            "question": "hi",
            "workspace": str(workspace),
            "pdf": "schematic.pdf",
            "page": 1,
        },
        config("analog-v2"),
        [tmp_path],
    )
    assert result["mode"] == "circuit"
    assert result["workspace"] == str(workspace.resolve())
    assert result["pdf"] == "schematic.pdf"
    assert result["page"] == 1
    assert result["dpi"] == 300
    assert "context_page" not in result
    assert "region" not in result


def test_circuit_mode_accepts_full_pdf_request(tmp_path):
    workspace = make_workspace(tmp_path)
    make_pdf(workspace)
    result = validate_browser_request(
        {
            "question": "hi",
            "workspace": str(workspace),
            "pdf": "schematic.pdf",
            "page": 2,
            "dpi": 600,
            "context_page": 1,
            "region": [0.1, 0.2, 0.9, 0.8],
        },
        config("analog-v2"),
        [tmp_path],
    )
    assert result["page"] == 2
    assert result["dpi"] == 600
    assert result["context_page"] == 1
    assert result["region"] == [0.1, 0.2, 0.9, 0.8]


def test_circuit_mode_rejects_explicit_image(tmp_path):
    workspace = make_workspace(tmp_path)
    make_pdf(workspace)
    with pytest.raises(ValueError):
        validate_browser_request(
            {
                "question": "hi",
                "workspace": str(workspace),
                "image": png_b64(),
                "pdf": "schematic.pdf",
                "page": 1,
            },
            config("analog-v2"),
            [tmp_path],
        )


@pytest.mark.parametrize("page", [True, 0])
def test_circuit_mode_rejects_bool_or_zero_page(tmp_path, page):
    workspace = make_workspace(tmp_path)
    make_pdf(workspace)
    with pytest.raises(ValueError):
        validate_browser_request(
            {
                "question": "hi",
                "workspace": str(workspace),
                "pdf": "schematic.pdf",
                "page": page,
            },
            config("analog-v2"),
            [tmp_path],
        )


@pytest.mark.parametrize("dpi", [True, 71, 1201])
def test_circuit_mode_rejects_bool_or_out_of_range_dpi(tmp_path, dpi):
    workspace = make_workspace(tmp_path)
    make_pdf(workspace)
    with pytest.raises(ValueError):
        validate_browser_request(
            {
                "question": "hi",
                "workspace": str(workspace),
                "pdf": "schematic.pdf",
                "page": 1,
                "dpi": dpi,
            },
            config("analog-v2"),
            [tmp_path],
        )


def test_circuit_mode_rejects_none_context_page(tmp_path):
    workspace = make_workspace(tmp_path)
    make_pdf(workspace)
    with pytest.raises(ValueError):
        validate_browser_request(
            {
                "question": "hi",
                "workspace": str(workspace),
                "pdf": "schematic.pdf",
                "page": 1,
                "context_page": None,
            },
            config("analog-v2"),
            [tmp_path],
        )


@pytest.mark.parametrize(
    "region",
    [
        None,
        [0.1, 0.2, float("nan"), 0.8],
        [0.9, 0.2, 0.1, 0.8],
        [],
    ],
)
def test_circuit_mode_rejects_invalid_region(tmp_path, region):
    workspace = make_workspace(tmp_path)
    make_pdf(workspace)
    with pytest.raises(ValueError):
        validate_browser_request(
            {
                "question": "hi",
                "workspace": str(workspace),
                "pdf": "schematic.pdf",
                "page": 1,
                "region": region,
            },
            config("analog-v2"),
            [tmp_path],
        )


@pytest.mark.parametrize("pdf", ["missing.pdf", "/abs/schematic.pdf", "../schematic.pdf"])
def test_circuit_mode_rejects_missing_absolute_or_parent_pdf(tmp_path, pdf):
    workspace = make_workspace(tmp_path)
    make_pdf(workspace)
    with pytest.raises(ValueError):
        validate_browser_request(
            {
                "question": "hi",
                "workspace": str(workspace),
                "pdf": pdf,
                "page": 1,
            },
            config("analog-v2"),
            [tmp_path],
        )


# ---------------------------------------------------------------------------
# Workspace containment: outside allowed roots and symlink escapes rejected.
# ---------------------------------------------------------------------------


def test_workspace_outside_allowed_roots_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError):
        validate_browser_request(
            {"question": "hi", "workspace": str(outside)},
            config("coder-v3"),
            [tmp_path / "allowed"],
        )


def test_workspace_symlink_escaping_root_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = allowed / "escape"
    link.symlink_to(outside)
    with pytest.raises(ValueError):
        validate_browser_request(
            {"question": "hi", "workspace": str(link)},
            config("coder-v3"),
            [allowed],
        )


def test_pdf_symlink_escaping_workspace_rejected(tmp_path):
    workspace = make_workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"%PDF-1.4 dummy")
    (workspace / "link.pdf").symlink_to(outside / "secret.pdf")
    with pytest.raises(ValueError):
        validate_browser_request(
            {
                "question": "hi",
                "workspace": str(workspace),
                "pdf": "link.pdf",
                "page": 1,
            },
            config("analog-v2"),
            [tmp_path],
        )
