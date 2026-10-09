"""Vision circuit workflow on the durable, offline execution runtime."""

import base64
import json
import os
import stat
from pathlib import Path

from local_agent.circuits.contracts import CircuitGraph
from local_agent.circuits.netlist import compile_netlist, graph_schema
from local_agent.contracts import ArtifactRecord, new_id
from local_agent.runtime.agent import Agent
from local_agent.storage.blobs import digest


def read_evidence(root, relative, limit=10 * 1024 * 1024):
    """Read data without following generated symlinks or executing generated code."""
    parts = Path(relative).parts
    if not parts or any(p in {".", ".."} for p in parts) or Path(relative).is_absolute():
        raise ValueError("invalid evidence path")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("evidence must be a bounded regular file")
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError("evidence exceeds capture limit")
            return data
    finally:
        os.close(fd)


class CircuitAgent(Agent):
    def __init__(
        self, *args, pdf=None, page=None, dpi=300, region=None, context_page=None, **kwargs
    ):
        super().__init__(*args, **kwargs)
        if self.config.instructions_version != "analog-v1":
            raise ValueError("circuit workflow requires analog-v1 instructions")
        self.pdf, self.page, self.dpi = pdf, page, dpi
        self.region, self.context_page = region, context_page

    def prepared(self):
        for event in reversed(self.store.events(self.run_id)):
            if event.event_type == "circuit.prepared":
                return self.store.blobs.json(event.data["input_ref"])
        raise RuntimeError("circuit preparation is missing; start a fresh circuit run")

    def capture(self, relative, execution_id, mime):
        data = read_evidence(self.path / "project", relative)
        ref = self.store.blobs.put(data)
        artifact = ArtifactRecord(
            artifact_id=new_id("artifact"),
            run_id=self.run_id,
            execution_id=execution_id,
            blob_ref=ref,
            content_hash=digest(data),
            mime=mime,
            size=len(data),
            workspace_origin="project/" + relative,
        )
        self.last = self.store.register_artifact(artifact, causes=(self.last.event_id,))
        return ref

    async def save(self, relative, content, purpose):
        target = self.path / "project" / relative
        arguments = {"path": "project/" + relative, "content": content}
        if target.exists() or target.is_symlink():
            arguments["create_only"] = False
            arguments["expected_hash"] = digest(read_evidence(self.path / "project", relative))
        else:
            arguments["create_only"] = True
        _, result = await self.trusted("write_file", arguments, purpose)
        if result is None or result.status != "succeeded":
            raise RuntimeError("could not save " + relative)
        return result

    async def prepare(self):
        selected = next(
            e for e in self.store.events(self.run_id) if e.event_type == "model.selected"
        )
        metadata = self.store.blobs.json(selected.data["metadata_ref"])
        if self.config.provider == "ollama" and not metadata.get("scripted"):
            if "vision" not in metadata.get("show", {}).get("capabilities", []):
                raise ValueError("circuit image analysis requires a vision-capable model")
        if (
            not self.pdf
            or not self.page
            or Path(self.pdf).is_absolute()
            or ".." in Path(self.pdf).parts
        ):
            raise ValueError("provide a case-relative PDF and a one-based PDF page")
        argv = [
            "python",
            "-I",
            "/opt/local-agent/pdf_extract.py",
            "--pdf",
            "/workspace/project/" + self.pdf,
            "--page",
            str(self.page),
            "--dpi",
            str(self.dpi),
        ]
        if self.region:
            argv.extend(["--region", *map(str, self.region)])
        if self.context_page:
            argv.extend(["--context-page", str(self.context_page)])
        _, result = await self.trusted(
            "run_command", {"argv": argv, "timeout_seconds": 300}, "pdf_extraction"
        )
        if result is None or result.status != "succeeded":
            raise RuntimeError("PDF extraction failed; inspect its retained execution evidence")
        directory = f"extracted/page-{self.page:03d}"
        manifest_ref = self.capture(
            directory + "/manifest.json", result.execution_id, "application/json"
        )
        manifest = self.store.blobs.json(manifest_ref)
        # Capture the original PDF in bounded chunks; do not put a large PDF in one blob.
        original = read_evidence(self.path / "project", self.pdf, 256 * 1024 * 1024)
        if digest(original) != manifest["pdf_hash"]:
            raise ValueError("PDF changed during extraction")
        chunks = []
        for index, offset in enumerate(range(0, len(original), 8 * 1024 * 1024)):
            data = original[offset : offset + 8 * 1024 * 1024]
            ref = self.store.blobs.put(data)
            record = ArtifactRecord(
                artifact_id=new_id("artifact"),
                run_id=self.run_id,
                execution_id=result.execution_id,
                blob_ref=ref,
                content_hash=digest(data),
                mime="application/octet-stream",
                size=len(data),
                workspace_origin=f"project/{self.pdf}#chunk-{index}",
            )
            self.last = self.store.register_artifact(record, causes=(self.last.event_id,))
            chunks.append(ref)
        for item in manifest["images"]:
            item["evidence_ref"] = self.capture(item["path"], result.execution_id, "image/png")
            data = self.store.blobs.read(item["evidence_ref"])
            if not data.startswith(b"\x89PNG\r\n\x1a\n") or digest(data) != item["sha256"]:
                raise ValueError("rendered image hash/signature mismatch")
        manifest["source_chunks"] = chunks
        manifest["manifest_ref"] = manifest_ref
        manifest["text_ref"] = self.capture(
            manifest["text_path"], result.execution_id, "text/plain"
        )
        manifest["case_input"] = {}
        for filename in ("symptoms.md", "measurements.csv"):
            if (self.path / "project" / filename).exists():
                manifest["case_input"][filename] = self.capture(
                    filename, result.execution_id, "text/plain"
                )
        await self.save("analysis/graph-schema.json", graph_schema(), "circuit_graph_schema")
        self.event(
            "circuit.prepared", "runtime", {"input_ref": self.store.blobs.put_json(manifest)}
        )

    def fixed_messages(self, task):
        manifest = self.prepared()
        labels = "\n".join(
            f"Image {i + 1}: PDF page {v['page']}, {v['label']}, {v['dpi']} DPI, region {v['region']}"
            for i, v in enumerate(manifest["images"])
        )
        notes = "\n".join(
            name + ":\n" + self.store.blobs.read(ref).decode("utf-8", errors="replace")
            for name, ref in manifest.get("case_input", {}).items()
        )
        content = (
            task
            + "\n\nSource PDF: "
            + manifest["pdf_filename"]
            + "\n\n"
            + labels
            + "\n\nCase notes:\n"
            + notes
        )
        encoded = [
            base64.b64encode(self.store.blobs.read(v["evidence_ref"])).decode("ascii")
            for v in manifest["images"]
        ]
        if self.config.provider == "openai":
            message = {
                "role": "user",
                "content": [
                    {"type": "text", "text": content},
                    *[
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64," + data, "detail": "high"},
                        }
                        for data in encoded
                    ],
                ],
            }
        else:
            message = {"role": "user", "content": content, "images": encoded}
        return [{"role": "system", "content": self.instructions}, message]

    async def complete(self, answer, verify_fixture):
        if verify_fixture:
            raise ValueError("coding fixture verification cannot verify a circuit")
        try:
            graph = CircuitGraph.model_validate_json(
                read_evidence(self.path / "project", "netlists/circuit.graph.json", 1024 * 1024)
            )
            explanation = read_evidence(
                self.path / "project", "analysis/explanation.md", 1024 * 1024
            )
            if not explanation.strip():
                raise ValueError("explanation is empty")
            if len(graph.components) > 4:
                raise ValueError(
                    f"initial graph contains {len(graph.components)} components; retain only 1-4 readable components "
                    "and put other missing coverage in unresolved. Do not invent missing values or connections."
                )
            allowed = {v["page"] for v in self.prepared()["images"]}
            if not set(graph.pages) <= allowed:
                raise ValueError("graph cites pages not supplied as image evidence")
        except (ValueError, OSError) as exc:
            failure_key = ("circuit_validation", str(exc))
            self.failures[failure_key] += 1
            if self.failures[failure_key] >= self.config.limits.max_identical_failures:
                raise RuntimeError(
                    "repeated identical circuit validation failure: " + str(exc)
                ) from exc
            self.groups.append(
                [
                    {
                        "role": "user",
                        "content": "Save both required files and repair graph schema errors: "
                        + str(exc),
                    }
                ]
            )
            self.checkpoint()
            return None
        netlist, validation = compile_netlist(graph)
        await self.save("netlists/draft.cir", netlist, "circuit_netlist_compile")
        await self.save(
            "netlists/validation.json",
            json.dumps(validation, indent=2) + "\n",
            "circuit_netlist_report",
        )
        refs = {}
        for name, mime in [
            ("netlists/circuit.graph.json", "application/json"),
            ("analysis/explanation.md", "text/markdown"),
            ("netlists/draft.cir", "text/plain"),
            ("netlists/validation.json", "application/json"),
        ]:
            expected = read_evidence(self.path / "project", name)
            _, captured = await self.trusted(
                "run_command", {"argv": ["cat", "--", name]}, "circuit_artifact_capture"
            )
            if captured is None or captured.status != "succeeded" or captured.truncated:
                raise RuntimeError("circuit artifact capture failed")
            if self.store.blobs.read(captured.stdout_ref) != expected:
                raise ValueError("circuit artifact changed during capture")
            refs[name] = self.capture(name, captured.execution_id, mime)
        self.event(
            "circuit.netlist_generated",
            "runtime",
            {
                "artifact_refs": list(refs.values()),
                "validation_ref": refs["netlists/validation.json"],
                "simulation_ready": False,
            },
        )
        result = await super().complete(answer, False)
        if result:
            result["circuit"] = validation
            result["circuit_artifacts"] = refs
        return result

    def export_case(self, case, result):
        """Copy captured artifacts into fresh run directories in the user's case."""
        directories = {}
        for group in ("analysis", "netlists", "extracted"):
            target = Path(case) / group / self.run_id
            target.mkdir(parents=True, exist_ok=False)
            directories[group] = target
        for name, ref in result.get("circuit_artifacts", {}).items():
            group, relative = name.split("/", 1)
            target = directories[group] / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.store.blobs.read(ref))
        manifest = self.prepared()
        for item in manifest["images"]:
            _, relative = item["path"].split("/", 1)
            target = directories["extracted"] / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.store.blobs.read(item["evidence_ref"]))
        (directories["extracted"] / "extraction-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
        return str(directories["analysis"])
