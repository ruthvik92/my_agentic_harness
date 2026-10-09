Fix only three files for existing Ruff rules:
- src/local_agent/executor/toolkit/workspace_io.py: both ValueError raises inside except OSError as exc must use from exc. Remove the unused flags assignment in parent_fd loop; retain flags in _open_dir and read_bytes where used.
- runtime/image_capture.py: format the from image_records import block into one sorted line DESCRIPTOR_MIME, save_artifact, tool_images.
- tests/test_custom_tools.py: order custom_schema import before register, registry_storage, workspace_io.
No other changes. Read each once, edit once, compile once and stop. Supervisor runs Ruff and tests; no missing dependency discovery.
