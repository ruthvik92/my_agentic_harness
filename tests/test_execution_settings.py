"""Focused tests for execution lifecycle configuration and result metadata."""

import pytest
from pydantic import ValidationError

from local_agent.contracts import (
    AgentConfig,
    ContainerState,
    ExecutionMode,
    ExecutionResult,
    ExecutionSettings,
)
from local_agent.observability.events import Event, EventType

INSTRUCTIONS_HASH = "sha256:" + "0" * 64
RUN_ID = "run_" + "a" * 32
WORKSPACE_ID = "workspace_" + "b" * 32
TOOL_CALL_ID = "call_" + "c" * 32
EXECUTION_ID = "execution_" + "d" * 32
BLOB_REF = "blob://" + "e" * 64
TRACE_ID = "f" * 32
SPAN_ID = "1" * 16


def make_agent_config(**overrides):
    base = {"instructions_hash": INSTRUCTIONS_HASH}
    base.update(overrides)
    return AgentConfig.model_validate(base)


def make_execution_result(**overrides):
    base = {
        "execution_id": EXECUTION_ID,
        "status": "succeeded",
        "exit_code": 0,
        "output_ref": BLOB_REF,
        "preview": "ok",
        "side_effect_status": "none",
        "duration_seconds": None,
    }
    base.update(overrides)
    return ExecutionResult.model_validate(base)


def make_event(event_type):
    return Event.model_validate(
        {
            "event_id": "event_" + "2" * 32,
            "run_id": RUN_ID,
            "run_seq": 1,
            "timestamp_utc": "2025-01-01T00:00:00Z",
            "trace_id": TRACE_ID,
            "span_id": SPAN_ID,
            "parent_span_id": None,
            "event_type": event_type,
            "actor": "operator",
            "data": {},
        }
    )


class TestExecutionSettings:
    def test_defaults(self):
        settings = ExecutionSettings.model_validate({})
        assert settings.schema_version == 1
        assert settings.execution_mode_default == "ephemeral"
        assert settings.max_execution_seconds == 300
        assert settings.persistent_container_idle_timeout == 1800
        assert settings.max_persistent_containers == 4
        assert settings.container_memory_limit == 4096
        assert settings.container_cpu_limit == 4
        assert settings.container_network_enabled is False

    def test_valid_persistent_settings(self):
        settings = ExecutionSettings.model_validate(
            {
                "execution_mode_default": "persistent",
                "max_execution_seconds": 1,
                "persistent_container_idle_timeout": 86400,
                "max_persistent_containers": 64,
                "container_memory_limit": 64,
                "container_cpu_limit": 1,
                "container_network_enabled": False,
            }
        )
        assert settings.execution_mode_default == "persistent"
        assert settings.max_execution_seconds == 1
        assert settings.persistent_container_idle_timeout == 86400
        assert settings.max_persistent_containers == 64
        assert settings.container_memory_limit == 64
        assert settings.container_cpu_limit == 1

    @pytest.mark.parametrize(
        "field, value",
        [
            ("execution_mode_default", "always"),
            ("max_execution_seconds", 0),
            ("max_execution_seconds", 301),
            ("persistent_container_idle_timeout", 0),
            ("persistent_container_idle_timeout", 86401),
            ("max_persistent_containers", 0),
            ("max_persistent_containers", 65),
            ("container_memory_limit", 63),
            ("container_memory_limit", 4097),
            ("container_cpu_limit", 0),
            ("container_cpu_limit", 5),
        ],
    )
    def test_invalid_boundaries(self, field, value):
        with pytest.raises(ValidationError):
            ExecutionSettings.model_validate({field: value})

    @pytest.mark.parametrize(
        "field, value",
        [
            ("max_execution_seconds", "300"),
            ("max_execution_seconds", 300.0),
            ("persistent_container_idle_timeout", True),
            ("max_persistent_containers", "4"),
            ("container_memory_limit", 4096.0),
            ("container_cpu_limit", "4"),
            ("container_network_enabled", 1),
            ("container_network_enabled", "false"),
        ],
    )
    def test_invalid_types(self, field, value):
        with pytest.raises(ValidationError):
            ExecutionSettings.model_validate({field: value})

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            ExecutionSettings.model_validate({"docker_privileges": ["ALL"]})

    def test_frozen(self):
        settings = ExecutionSettings.model_validate({})
        with pytest.raises(ValidationError):
            settings.max_execution_seconds = 10  # type: ignore[misc]


class TestAgentConfigExecution:
    def test_execution_defaults(self):
        config = make_agent_config()
        assert config.execution == ExecutionSettings.model_validate({})

    def test_execution_settings_override(self):
        config = make_agent_config(
            execution={
                "execution_mode_default": "persistent",
                "max_execution_seconds": 120,
            }
        )
        assert config.execution.execution_mode_default == "persistent"
        assert config.execution.max_execution_seconds == 120
        assert config.execution.persistent_container_idle_timeout == 1800

    def test_offline_policy_rejects_enabled_network(self):
        with pytest.raises(ValidationError, match="dev-offline-v1"):
            make_agent_config(
                execution={"container_network_enabled": True}
            )

    def test_offline_policy_accepts_disabled_network(self):
        config = make_agent_config(execution={"container_network_enabled": False})
        assert config.execution.container_network_enabled is False

    def test_unknown_execution_field_rejected(self):
        with pytest.raises(ValidationError):
            make_agent_config(execution={"environment": {"PATH": "/usr/bin"}})

    def test_unknown_config_field_rejected(self):
        with pytest.raises(ValidationError):
            make_agent_config(docker_socket="/var/run/docker.sock")


class TestExecutionResultMetadata:
    def test_legacy_payload_still_parses(self):
        result = make_execution_result()
        assert result.run_id is None
        assert result.workspace_id is None
        assert result.tool_call_id is None
        assert result.container_id is None
        assert result.execution_mode is None
        assert result.started_at is None
        assert result.completed_at is None
        assert result.duration_ms is None
        assert result.error is None

    def test_new_metadata_fields(self):
        result = make_execution_result(
            run_id=RUN_ID,
            workspace_id=WORKSPACE_ID,
            tool_call_id=TOOL_CALL_ID,
            container_id="ctr_0123456789abcdef",
            execution_mode="persistent",
            started_at="2025-01-01T00:00:00Z",
            completed_at="2025-01-01T00:00:05Z",
            duration_ms=5000.5,
            error="timed out",
        )
        assert result.run_id == RUN_ID
        assert result.workspace_id == WORKSPACE_ID
        assert result.tool_call_id == TOOL_CALL_ID
        assert result.container_id == "ctr_0123456789abcdef"
        assert result.execution_mode == "persistent"
        assert result.started_at == "2025-01-01T00:00:00Z"
        assert result.completed_at == "2025-01-01T00:00:05Z"
        assert result.duration_ms == 5000.5
        assert result.error == "timed out"

    def test_invalid_metadata_rejected(self):
        with pytest.raises(ValidationError):
            make_execution_result(run_id="not-an-id")
        with pytest.raises(ValidationError):
            make_execution_result(execution_mode="hybrid")
        with pytest.raises(ValidationError):
            make_execution_result(duration_ms=-1)
        with pytest.raises(ValidationError):
            make_execution_result(error="x" * 4097)
        with pytest.raises(ValidationError):
            make_execution_result(container_id="x" * 257)

    def test_error_boundary_accepted(self):
        result = make_execution_result(error="x" * 4096)
        assert len(result.error) == 4096


class TestLifecycleEvents:
    @pytest.mark.parametrize(
        "event_type",
        [
            "execution.requested",
            "execution.timed_out",
            "execution.resource_limited",
            "container.created",
            "container.started",
            "container.idle",
            "container.stopped",
            "container.removed",
            "container.failed",
            "container.cleanup_failed",
        ],
    )
    def test_accepted_lifecycle_event_names(self, event_type):
        event = make_event(event_type)
        assert event.event_type == event_type

    def test_unknown_event_type_rejected(self):
        with pytest.raises(ValidationError):
            make_event("container.exploded")

    def test_existing_event_types_still_accepted(self):
        for event_type in ("execution.started", "execution.finished", "run.created"):
            assert make_event(event_type).event_type == event_type


class TestAliases:
    def test_execution_mode_values(self):
        assert set(ExecutionMode.__args__) == {"ephemeral", "persistent"}

    def test_container_state_values(self):
        assert set(ContainerState.__args__) == {
            "CREATED",
            "STARTING",
            "RUNNING",
            "EXECUTING",
            "IDLE",
            "STOPPING",
            "STOPPED",
            "FAILED",
            "REMOVED",
        }

    def test_event_type_is_literal(self):
        assert "execution.requested" in EventType.__args__
        assert "container.cleanup_failed" in EventType.__args__
