import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from local_agent.circuits.agent import CircuitAgent, read_evidence
from local_agent.circuits.contracts import CircuitGraph
from local_agent.circuits.netlist import compile_netlist
from local_agent.config import load_config
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.runtime.context import estimate
from local_agent.storage.blobs import digest
from local_agent.storage.bundles import roots
from local_agent.storage.database import Store


def graph_data():
    return {
        "schema_version": 1,
        "title": "Test circuit",
        "pages": [1],
        "coverage": "partial",
        "components": [
            {
                "schema_version": 1,
                "ref": "R1",
                "kind": "R",
                "value": "10k",
                "nodes": ["input", "0"],
                "connection_status": "observed",
                "evidence": {
                    "schema_version": 1,
                    "page": 1,
                    "region": [0, 0, 1, 1],
                    "note": "test image",
                },
            },
            {
                "schema_version": 1,
                "ref": "IC1",
                "kind": "IC",
                "part_number": "unknown",
                "connection_status": "uncertain",
                "uncertainty": "Pin connections unreadable",
                "evidence": {
                    "schema_version": 1,
                    "page": 1,
                    "region": [0, 0, 1, 1],
                    "note": "test image",
                },
            },
        ],
        "unresolved": ["Active model and remainder of schematic missing"],
    }


def test_netlist_rejects_injection_and_preserves_uncertainty():
    data = graph_data()
    data["title"] = "Circuit\n.include secret"
    data["components"][1]["uncertainty"] += "\n.control\nshell malicious"
    netlist, report = compile_netlist(CircuitGraph.model_validate_json(json.dumps(data)))
    assert "R1 input 0 10k" in netlist
    assert all(
        line.startswith("*") or line == ".end" or line.startswith("R1 ")
        for line in netlist.splitlines()
    )
    assert report["omitted_components"] == ["IC1"]
    assert not report["simulation_ready"]
    data["components"][0]["value"] = "10k\n.include secret"
    with pytest.raises(ValidationError):
        CircuitGraph.model_validate_json(json.dumps(data))
    data = graph_data()
    data["components"][0]["uncertainty"] = "Junction inferred"
    with pytest.raises(ValidationError, match="with uncertainty"):
        CircuitGraph.model_validate_json(json.dumps(data))
    data = graph_data()
    data["components"][0]["value"] = None
    second = json.loads(json.dumps(data["components"][0]))
    second["ref"] = "R2"
    data["components"].append(second)
    with pytest.raises(ValidationError) as caught:
        CircuitGraph.model_validate_json(json.dumps(data))
    assert "R1: observed passive" in str(caught.value)
    assert "R2: observed passive" in str(caught.value)
    data = graph_data()
    data["components"].append(data["components"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        CircuitGraph.model_validate_json(json.dumps(data))


def test_image_context_estimation_and_safe_read(tmp_path):
    assert estimate({"images": ["a" * 100000]}) == estimate({"images": ["a"]})
    assert (
        estimate({"content": [{"type": "image_url", "image_url": {"url": "data:" + "a" * 100000}}]})
        < 6400
    )
    (tmp_path / "secret").write_text("data")
    (tmp_path / "link").symlink_to(tmp_path / "secret")
    with pytest.raises(OSError):
        read_evidence(tmp_path, "link")
    with pytest.raises(ValueError):
        read_evidence(tmp_path, "../secret")
    with pytest.raises(ValueError):
        read_evidence(tmp_path, "secret", 2)


def make_pdf(path):
    # A deterministic one-page vector PDF; no extra PDF package needed by the harness.
    stream = b"BT /F1 16 Tf 20 120 Td (R1 10k) Tj ET 20 80 m 120 80 l S"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 144 144] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    data += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(data)


@pytest.mark.parametrize("repair_distinct_errors", [False, True])
def test_circuit_docker_end_to_end(tmp_path, request, repair_distinct_errors):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires pinned Docker image")
    source = tmp_path / "case"
    source.mkdir()
    make_pdf(source / "manual.pdf")
    prepared_pdf_hash = digest((source / "manual.pdf").read_bytes())
    config = load_config(Path("config/analog.yaml"))
    tools = list(dict.fromkeys(list(config.tools) + ["render_pdf_region", "view_image"]))
    config = config.model_copy(update={"tools": tools})
    graphs = []
    if repair_distinct_errors:
        duplicate = graph_data()
        duplicate["components"].append(duplicate["components"][0])
        wrong_page = graph_data()
        wrong_page["pages"] = [2]
        for component in wrong_page["components"]:
            component["evidence"]["page"] = 2
        missing_value = graph_data()
        missing_value["components"][0]["value"] = None
        oversized = graph_data()
        oversized["components"] = []
        for number in range(5):
            component = json.loads(json.dumps(graph_data()["components"][0]))
            component["ref"] = f"R{number + 1}"
            oversized["components"].append(component)
        graphs.extend([duplicate, wrong_page, missing_value, oversized])
    graphs.append(graph_data())
    responses = [
        {
            "text": "",
            "tool_calls": [
                {
                    "name": "render_pdf_region",
                    "arguments": {
                        "pdf": "project/manual.pdf",
                        "page": 1,
                        "region": [0.1, 0.1, 0.6, 0.6],
                        "dpi": 300,
                    },
                }
            ],
            "finish_status": "tool_calls",
        }
    ]
    previous = None
    for index, graph in enumerate(graphs):
        content = json.dumps(graph)
        arguments = {"path": "project/netlists/circuit.graph.json", "content": content}
        if previous is not None:
            arguments.update(create_only=False, expected_hash=digest(previous.encode()))
        calls = [{"name": "write_file", "arguments": arguments}]
        if index == 0:
            calls.append(
                {
                    "name": "write_file",
                    "arguments": {
                        "path": "project/analysis/explanation.md",
                        "content": "Illustrative R1 on PDF page 1. Active model unresolved.",
                    },
                }
            )
        responses.extend(
            [
                {"text": "", "tool_calls": calls, "finish_status": "tool_calls"},
                {"text": "Draft saved.", "tool_calls": [], "finish_status": "stop"},
            ]
        )
        previous = content
    provider = ScriptedProvider(responses=responses)
    store = Store(tmp_path / "data")
    try:
        agent = CircuitAgent(
            store,
            config,
            {"image": image},
            provider=provider,
            pdf="manual.pdf",
            page=1,
            dpi=72,
            region=[0, 0, 1, 1],
        )
        result = asyncio.run(agent.run(source, "Explain page 1"))
        assert result["status"] == "completed_unverified", result
        assert result["circuit"]["emitted_passives"] == ["R1"]
        assert audit(store, result["run_id"])["ok"]
        snapshot = store.blobs.json(provider.requests[1].context_ref)
        payload = store.blobs.json(snapshot["payload_ref"])
        last3 = payload["messages"][-3:]
        assert [m["role"] for m in last3] == ["assistant", "tool", "user"]
        assert last3[-1]["content"][-1]["type"] == "image_url"
        assert last3[-1]["content"][-1]["image_url"]["url"].startswith("data:image/")
        exported = Path(agent.export_case(source, result))
        assert (source / "netlists" / result["run_id"] / "draft.cir").read_text().endswith(".end\n")
        assert (exported / "explanation.md").exists()
        manifest = json.loads(
            (exported / result["run_id"] / "extraction-manifest.json").read_text()
        )
        adaptive = manifest["adaptive_images"]
        assert len(adaptive) == 1
        image_entry = adaptive[0]
        assert image_entry["source"]["page"] == 1
        assert image_entry["source"]["sha256"] == prepared_pdf_hash
        image_ref = image_entry["image_ref"]
        assert store.blobs.read(image_ref) == (exported / image_entry["exported_path"]).read_bytes()
        prepared = agent.prepared()
        assert len(prepared["images"]) == 2
        refs, _ = roots(store, result["run_id"])
        assert prepared["images"][0]["evidence_ref"] in refs
        assert image_ref in refs
        assert prepared["images"][1]["evidence_ref"] in refs
        assert any(
            e.event_type == "circuit.prepared" and e.data["input_ref"] in refs
            for e in store.events(result["run_id"])
        )
        config_openai = config.model_copy(update={"provider": "openai"})
        agent.config = config_openai
        assert agent.fixed_messages("test")[1]["content"][1]["image_url"]["url"].startswith(
            "data:image/png;base64,"
        )
    finally:
        store.close()
