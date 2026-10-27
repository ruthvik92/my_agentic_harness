import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict

import yaml

from local_agent.config import AgentConfig, load_config
from local_agent.doctor import sandbox_config


def metadata(name: str, config: AgentConfig) -> Dict[str, Any]:
    return {
        "name": name,
        "kind": "agent",
        "mode": "chat" if config.instructions_version in ["phone-v1", "browser-v1"] else
                "circuit" if config.instructions_version in ["analog-v1", "analog-v2"] else
                "coding",
        "provider": config.provider,
        "model": config.model,
        "instructions_version": config.instructions_version,
        "tools": list(config.tools),
        "window_tokens": config.window_tokens,
        "output_reserve_tokens": config.output_reserve_tokens,
        "limits": config.limits.model_dump(mode='json'),
        "api_key_env": config.api_key_env,
        "execution": config.execution.model_dump(mode="json"),
    }

def validate_profile(name: str, content: str) -> Dict[str, Any]:
    if not isinstance(content, str):
        raise ValueError("Profile content must be a string")
    if not content:
        raise ValueError("Profile content cannot be empty")
    if len(content.encode('utf-8')) > 65536:
        raise ValueError("Profile content exceeds 65536 bytes in UTF-8")

    # Handle sandbox.json specially
    if name == "sandbox.json":
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in sandbox.json: {e}") from e
        if not isinstance(parsed, dict):
            raise ValueError("sandbox.json must contain a JSON object")
        if type(parsed.get('schema_version')) is not int or parsed.get('schema_version') != 1:
            raise ValueError("schema_version must be the integer 1")
        image = parsed.get('image')
        if not isinstance(image, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise ValueError("image must be a valid sha256: lowercase hex string")
        allowed_keys = {"schema_version", "image", "base_image", "base_reference", "worker_hash", "verifier_hash", "pdf_helper_hash", "toolkit_hashes"}
        unknown_keys = set(parsed.keys()) - allowed_keys
        if unknown_keys:
            raise ValueError(f"Unknown keys in sandbox.json: {unknown_keys}")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', encoding='utf-8', delete=False) as temp:
            temp.write(content)
            temp.flush()
            temp_path = Path(temp.name)
        try:
            sandbox_config(temp_path)
        except Exception as e:
            raise ValueError(f"Invalid sandbox.json: {e}") from e
        finally:
            temp_path.unlink(missing_ok=True)
        return {
            "name": "sandbox.json",
            "kind": "sandbox",
            "mode": "infrastructure",
            "image": image
        }

    # For other profiles, treat as YAML
    try:
        config = yaml.safe_load(content)
        if not isinstance(config, dict):
            raise ValueError("Profile must be a dictionary")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', encoding='utf-8', delete=False) as temp:
            temp.write(content)
            temp.flush()
            temp_path = Path(temp.name)
        try:
            loaded_config = load_config(temp_path)
            # Reject phone-v1 with nonempty tools
            if loaded_config.instructions_version == "phone-v1" and loaded_config.tools:
                raise ValueError("phone-v1 instructions_version cannot have non-empty tools")
            return metadata(name, loaded_config)
        except Exception as e:
            raise ValueError(f"Invalid profile config: {e}") from e
        finally:
            temp_path.unlink(missing_ok=True)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}") from e
    except Exception as e:
        raise ValueError(f"Unexpected error: {e}") from e
