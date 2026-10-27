import json
from pathlib import Path

from local_agent.executor.docker import docker
from local_agent.storage.blobs import canonical, digest


async def build_image(base="mirror.gcr.io/library/python:3.12-slim-bookworm"):
    repository = Path(__file__).resolve().parents[3]
    try:
        info = json.loads(await docker("image", "inspect", base))[0]
    except RuntimeError:
        await docker("pull", base, timeout=900)
        info = json.loads(await docker("image", "inspect", base))[0]
    base_id = info["Id"]
    if not info["RepoDigests"]:
        raise ValueError("base image must have a recorded registry digest")
    base_reference = info["RepoDigests"][0]
    await docker(
        "build",
        "--build-arg",
        "BASE_IMAGE=" + base_reference,
        "-f",
        str(repository / "sandbox" / "Dockerfile"),
        "-t",
        "local-agent-sandbox:v1",
        str(repository),
        timeout=900,
        progress=True,
    )
    image = json.loads(await docker("image", "inspect", "local-agent-sandbox:v1"))[0]
    config = {
        "schema_version": 1,
        "image": image["Id"],
        "base_image": base_id,
        "base_reference": base_reference,
        "worker_hash": digest((repository / "src/local_agent/executor/worker.py").read_bytes()),
        "pdf_helper_hash": digest((repository / "sandbox/pdf_extract.py").read_bytes()),
        "verifier_hash": digest((repository / "sandbox/verify.py").read_bytes()),
        "toolkit_hashes": {
            p.name: digest(p.read_bytes())
            for p in sorted((repository / "src/local_agent/executor/toolkit").glob("*.py"))
        },
    }
    directory = repository / "config"
    directory.mkdir(exist_ok=True)
    (directory / "sandbox.json").write_bytes(canonical(config) + b"\n")
    return config
