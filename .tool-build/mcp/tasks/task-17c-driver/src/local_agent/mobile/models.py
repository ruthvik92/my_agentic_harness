"""Controller-owned model discovery and per-job configurations; no browser secrets."""

import os
import threading
import time
from pathlib import Path

import httpx

from local_agent.config import load_config

# Curated vision + Chat Completions support; /models alone has no capability schema.
REVIEW_MODELS = {
    "gpt-6-astra": ("Most capable · higher cost", "medium"),
    "gpt-6.1-sol": ("Complex work · lower cost than Astra", "medium"),
    "gpt-6-luna": ("Efficient focused review", "medium"),
    "gpt-5.4": ("Earlier flagship", "medium"),
    "gpt-5.4-mini": ("Earlier efficient model", "medium"),
    "gpt-4.1-2025-04-14": ("Previous reviewer · no reasoning effort", None),
    "gpt-4.1": ("GPT-4.1 alias · no reasoning effort", None),
}


class Models:
    def __init__(self, config, verifier_path=None):
        self.config = config
        self.verifier_path = Path(verifier_path or "config/phone-verifier.yaml").absolute()
        self.lock = threading.Lock()
        self.cached, self.expires = None, 0

    def catalog(self, refresh=False):
        with self.lock:
            if self.cached is not None and not refresh and time.monotonic() < self.expires:
                return self.cached
            entries, error = [], None
            try:
                with httpx.Client(
                    base_url="http://127.0.0.1:11434", timeout=5, trust_env=False
                ) as client:
                    tags = client.get("/api/tags").raise_for_status().json()["models"]
                    for tag in tags[:64]:
                        name = tag["name"]
                        try:
                            info = (
                                client.post("/api/show", json={"model": name})
                                .raise_for_status()
                                .json()
                            )
                            caps = info.get("capabilities", [])
                            ready = "completion" in caps
                            entries.append(
                                {
                                    "id": "ollama:" + name,
                                    "model": name,
                                    "provider": "ollama",
                                    "capabilities": caps,
                                    "vision": "vision" in caps,
                                    "selectable": ready,
                                    "reason": None if ready else "Not a chat model",
                                }
                            )
                        except (httpx.HTTPError, ValueError, KeyError):
                            entries.append(
                                {
                                    "id": "ollama:" + name,
                                    "model": name,
                                    "provider": "ollama",
                                    "capabilities": [],
                                    "vision": False,
                                    "selectable": False,
                                    "reason": "Metadata unavailable",
                                }
                            )
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                error = "Ollama discovery unavailable: " + type(exc).__name__
            default_id = self.config.provider + ":" + self.config.model
            if not any(e["id"] == default_id for e in entries):
                entries.append(
                    {
                        "id": default_id,
                        "model": self.config.model,
                        "provider": self.config.provider,
                        "capabilities": [],
                        "vision": False,
                        "selectable": self.config.provider == "openai",
                        "reason": "Configured API model; image capability not locally probed"
                        if self.config.provider == "openai"
                        else "Not found in local model discovery",
                    }
                )
            reviewer = self.review_catalog()
            self.cached = {
                "models": entries,
                "default_id": default_id,
                "verifier": reviewer,
                "error": error,
            }
            self.expires = time.monotonic() + 60
            return self.cached

    def review_catalog(self):
        reviewer = {
            "model": None,
            "default_id": "",
            "models": [],
            "enabled": False,
            "reason": "Verifier config missing",
            "error": None,
        }
        try:
            cfg = self.verifier_config()
        except (OSError, ValueError) as exc:
            reviewer["reason"] = "Verifier unavailable: " + type(exc).__name__
            return reviewer
        key = os.environ.get(cfg.api_key_env)
        reviewer.update(model=cfg.model, default_id="openai:" + cfg.model)
        available, problem = None, None
        if key:
            try:
                with httpx.Client(timeout=5, trust_env=False) as client:
                    response = client.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": "Bearer " + key},
                    )
                    response.raise_for_status()
                    available = {m["id"] for m in response.json()["data"]}
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                problem = "OpenAI model discovery unavailable: " + type(exc).__name__
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (
                    401,
                    403,
                ):
                    available = set()
                    problem = "OpenAI model discovery denied: HTTP " + str(exc.response.status_code)
        for model, (label, effort) in REVIEW_MODELS.items():
            selectable = bool(key) and (available is None or model in available)
            reason = (
                "Set " + cfg.api_key_env + " in the server's launch terminal"
                if not key
                else problem
                if available == set()
                else "Not listed for this API key"
                if available is not None and model not in available
                else None
            )
            reviewer["models"].append(
                {
                    "id": "openai:" + model,
                    "model": model,
                    "provider": "openai",
                    "capabilities": ["completion", "vision"] + (["reasoning"] if effort else []),
                    "vision": True,
                    "selectable": selectable,
                    "reason": reason,
                    "label": label,
                    "access_checked": available is not None,
                }
            )
        reviewer["enabled"] = any(m["selectable"] for m in reviewer["models"])
        reviewer["reason"] = (
            None
            if reviewer["enabled"]
            else problem
            or (
                "Set " + cfg.api_key_env + " in the server's launch terminal"
                if not key
                else "No supported reviewer models listed for this API key"
            )
        )
        reviewer["error"] = problem
        return reviewer

    def select_reviewer(self, model_id=None):
        cfg = self.verifier_config()
        model_id = model_id or "openai:" + cfg.model
        item = next((m for m in self.catalog()["verifier"]["models"] if m["id"] == model_id), None)
        if not item or not item["selectable"]:
            raise ValueError("Select an available OpenAI reviewer from the catalog")
        effort = REVIEW_MODELS[item["model"]][1]
        return cfg.model_copy(
            update={
                "model": item["model"],
                "reasoning_effort": effort,
                "completion_token_field": "max_completion_tokens",
                "output_reserve_tokens": 16384 if effort else 4096,
            }
        )

    def select(self, model_id=None, *, has_image=False):
        model_id = model_id or self.config.provider + ":" + self.config.model
        item = next((m for m in self.catalog()["models"] if m["id"] == model_id), None)
        if not item or not item["selectable"]:
            raise ValueError("Select an available chat model from the catalog")
        if has_image and item["provider"] == "ollama" and not item["vision"]:
            raise ValueError("Selected model cannot read images; choose a model with vision")
        cfg = self.config.model_copy(update={"provider": item["provider"], "model": item["model"]})
        return cfg, item

    def verifier_config(self):
        cfg = load_config(self.verifier_path)
        if (
            cfg.provider != "openai"
            or cfg.base_url.rstrip("/") != "https://api.openai.com/v1"
            or not cfg.api_key_env
            or cfg.instructions_version != "phone-v1"
            or cfg.tools
        ):
            raise ValueError("Verifier must use the official OpenAI API, phone-v1 and no tools")
        return cfg
