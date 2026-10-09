from pathlib import Path

from local_agent.config import load_config
from local_agent.contracts import AgentConfig


def choose(kind: str, model: str | None, catalog: dict, root: Path) -> AgentConfig:
    filenames = {"coding": "coder.yaml", "screenshot": "phone.yaml", "circuit": "analog.yaml"}
    if kind not in filenames:
        raise ValueError(f"Unknown kind: {kind}")
    cfg = load_config(root / "config" / filenames[kind])
    if cfg.provider != "ollama":
        raise ValueError(f"Provider must be 'ollama', got {cfg.provider}")
    chosen = model or cfg.model
    entry = next((m for m in catalog.get("models", []) if m["model"] == chosen), None)
    if entry is None:
        raise ValueError(f"Model {chosen} not in catalog")
    required = {"completion"}
    if kind == "coding":
        required.add("tools")
    elif kind == "screenshot":
        required.add("vision")
    elif kind == "circuit":
        required.add("vision")
        required.add("tools")
    if not required.issubset(set(entry.get("capabilities", []))):
        missing = required - set(entry.get("capabilities", []))
        raise ValueError(f"Missing capability: {missing}")
    return cfg.model_copy(update={"model": chosen})
