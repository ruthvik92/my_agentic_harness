"""Versioned protocol records; strict inputs are separate from authorization."""

from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

ID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*_[0-9a-f]{32}$")]
Hash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
BlobRef = Annotated[str, Field(pattern=r"^blob://[0-9a-f]{64}$")]
TraceID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
SpanID = Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
Name = Annotated[str, Field(min_length=1, max_length=128)]
PathText = Annotated[str, Field(min_length=1, max_length=4096)]


def new_id(kind: str) -> str:
    return f"{kind}_{uuid4().hex}"


class Record(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    schema_version: Literal[1] = 1

    @field_validator("schema_version", "tool_version", mode="before", check_fields=False)
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema version must be an integer")
        return value


class Limits(Record):
    max_model_turns: int = Field(default=30, ge=1, le=1000)
    max_attempted_tool_calls: int = Field(default=100, ge=1, le=10000)
    run_timeout_seconds: int = Field(default=1200, ge=1, le=86400)
    model_timeout_seconds: int = Field(default=180, ge=1, le=3600)
    max_identical_failures: int = Field(default=3, ge=1, le=10)
    max_evidence_bytes: int = Field(default=1073741824, ge=1048576, le=1073741824)


class AgentConfig(Record):
    agent_id: Name = "coder"
    instructions_version: Name = "coder-v1"
    instructions_hash: Hash
    provider: Literal["scripted", "ollama", "openai"] = "scripted"
    model: Name = "scripted-v1"
    base_url: str = "https://api.openai.com/v1"
    api_key_env: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")] | None = "OPENAI_API_KEY"
    completion_token_field: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] | None = None
    tools: tuple[Name, ...] = ("read_file", "run_command")
    policy_profile: Name = "dev-offline-v1"
    limits: Limits = Field(default_factory=Limits)
    window_tokens: int = Field(default=8192, ge=2048, le=131072)
    output_reserve_tokens: int = Field(default=2048, ge=256, le=32768)


class RunManifest(Record):
    run_id: ID
    thread_id: ID
    workspace_id: ID
    source_revision: str | None = None
    package_versions: dict[str, str]
    config_ref: BlobRef
    config_hash: Hash
    model_identity: Name
    sandbox_image_digest: str | None = None
    mode: Literal["simulation", "live"] = "simulation"


class ContextSnapshot(Record):
    messages: tuple[dict[str, JsonValue], ...]
    tool_definitions: tuple[dict[str, JsonValue], ...]
    payload_ref: BlobRef
    payload_hash: Hash
    provenance: tuple[dict[str, JsonValue], ...]
    exclusions: tuple[dict[str, JsonValue], ...] = ()
    token_estimate: int = Field(ge=0)


class ModelRequest(Record):
    request_id: ID
    run_id: ID
    context_ref: BlobRef
    provider: Name
    model: Name
    options: dict[str, JsonValue]
    deadline_utc: str
    attempt: int = Field(default=1, ge=1)
    trace_id: TraceID
    parent_span_id: SpanID
    purpose: Name = "agent"
    target_workspace_id: ID | None = None
    workspace_grant_ref: BlobRef | None = None


class ProposedCall(Record):
    name: Name
    arguments: JsonValue
    provider_id: str | None = Field(default=None, max_length=256)


class ModelResponse(Record):
    request_id: ID
    text: str = Field(default="", max_length=65536)
    tool_calls: tuple[ProposedCall, ...] = Field(default=(), max_length=100)
    finish_status: Literal["stop", "tool_calls", "error"]
    usage: dict[str, JsonValue] | None = None
    original_response_ref: BlobRef
    client_duration_seconds: float | None = Field(default=None, ge=0)


class ToolCall(Record):
    call_id: ID
    request_id: ID
    provider_id: str | None = None
    index: int = Field(ge=0)
    name: Name
    tool_version: int = Field(default=1, ge=1, le=16)
    arguments_ref: BlobRef


class PolicyDecision(Record):
    decision_id: ID
    call_id: ID
    verdict: Literal["allow", "deny", "approval"]
    rule_ids: tuple[Name, ...]
    policy_hash: Hash
    normalized_request_hash: Hash
    normalized_request_ref: BlobRef
    reason: str = Field(max_length=4096)


class EffectiveLimits(Record):
    memory_mb: int = Field(default=4096, ge=1, le=4096)
    cpu_cores: int = Field(default=4, ge=1, le=4)
    pids: int = Field(default=128, ge=1, le=128)
    network: Literal[False] = False
    gpu: Literal[False] = False

    @field_validator("network", "gpu", mode="before")
    @classmethod
    def strict_boolean(cls, value):
        if type(value) is not bool:
            raise ValueError("capability flags must be booleans")
        return value


class ExecutionRequest(Record):
    execution_id: ID
    call_id: ID
    workspace_id: ID
    tool: Name
    tool_version: int = Field(default=1, ge=1, le=16)
    arguments: dict[str, JsonValue]
    effective_limits: EffectiveLimits = Field(default_factory=EffectiveLimits)
    authorization_ref: ID
    normalized_request_hash: Hash
    trace_id: TraceID
    parent_span_id: SpanID
    deadline_utc: str | None = None
    workspace_grant_ref: BlobRef | None = None


class ExecutionResult(Record):
    execution_id: ID
    status: Literal["succeeded", "failed", "timeout", "cancelled", "output_limit"]
    exit_code: int | None
    output_ref: BlobRef
    preview: str = Field(max_length=16384)
    duration_seconds: float | None = Field(ge=0)
    truncated: bool = False
    side_effect_status: Literal["none", "applied", "unknown"]
    simulated: bool = False
    stdout_ref: BlobRef | None = None
    stderr_ref: BlobRef | None = None
    attestation_ref: BlobRef | None = None
    captured_bytes: int = Field(default=0, ge=0)
    helper_ref: BlobRef | None = None


class DecisionRecord(Record):
    actor: Name
    kind: Name
    selected_action: Name
    evidence_refs: tuple[BlobRef, ...]
    config_hash: Hash
    rationale_source: Literal["deterministic_rule", "model_reported"]
    reason: str = Field(max_length=4096)


class ArtifactRecord(Record):
    artifact_id: ID
    run_id: ID
    execution_id: ID
    blob_ref: BlobRef
    content_hash: Hash
    mime: Name
    size: int = Field(ge=0)
    workspace_origin: PathText


class Checkpoint(Record):
    checkpoint_id: ID
    run_id: ID
    completed_event_seq: int = Field(ge=0)
    conversation_refs: tuple[BlobRef, ...]
    model_turns: int = Field(ge=0)
    attempted_calls: int = Field(ge=0)
    pending_ids: tuple[ID, ...]
    workspace_id: ID
    workspace_version: int = Field(ge=0)


class Approval(Record):
    approval_id: ID
    call_id: ID
    request_hash: Hash
    workspace_id: ID
    policy_hash: Hash
    effective_limits: EffectiveLimits
    expires_utc: str
    state: Literal["pending", "granted", "denied", "expired"]
    actor: Name


def validate_path(value: str | None) -> str | None:
    if value is None:
        return None
    parts = value.split("/")
    if "\x00" in value or "\\" in value or value.startswith("/"):
        raise ValueError("expected a relative workspace path")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("empty, dot, and parent path components are forbidden")
    if parts[0] not in {"project", "memory", "tools", "scratch", "outputs"}:
        raise ValueError("path must start with an approved workspace directory")
    return value


class ReadFileV1Args(Record):
    path: PathText
    line_offset: int = Field(default=0, ge=0, le=10000000)
    line_limit: int = Field(default=100, ge=1, le=1000)
    _path = field_validator("path")(validate_path)


class ReadFileV2Args(Record):
    path: PathText | None = None
    evidence_ref: BlobRef | None = None
    line_offset: int = Field(default=0, ge=0, le=10000000)
    line_limit: int = Field(default=100, ge=1, le=1000)
    _path = field_validator("path")(validate_path)

    @model_validator(mode="after")
    def one_source(self):
        if (self.path is None) == (self.evidence_ref is None):
            raise ValueError("exactly one of path or evidence_ref is required")
        return self


class ReadFileArgs(ReadFileV2Args):
    byte_offset: int = Field(default=0, ge=0, le=10485760)
    byte_limit: int = Field(default=8192, ge=1, le=8192)


class RunCommandV1Args(Record):
    argv: tuple[Annotated[str, Field(min_length=1, max_length=8192)], ...] = Field(
        min_length=1, max_length=128
    )
    cwd: PathText = "project"
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    _path = field_validator("cwd")(validate_path)

    @field_validator("argv")
    @classmethod
    def no_nuls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any("\x00" in item for item in value):
            raise ValueError("NUL in argv")
        return value


class RunCommandArgs(RunCommandV1Args):
    helper_manifest: PathText | None = None
    _manifest_path = field_validator("helper_manifest")(validate_path)


class WriteFileArgs(Record):
    path: PathText
    content: str = Field(max_length=1048576)
    expected_hash: Hash | None = None
    create_only: bool = True
    _path = field_validator("path")(validate_path)

    @model_validator(mode="after")
    def explicit_precondition(self):
        if self.create_only == (self.expected_hash is not None):
            raise ValueError("choose create_only or an expected_hash for replacement")
        return self


class PatchFileArgs(Record):
    path: PathText
    old_text: str = Field(min_length=1, max_length=1048576)
    new_text: str = Field(max_length=1048576)
    expected_hash: Hash
    _path = field_validator("path")(validate_path)


class ListFilesArgs(Record):
    directory: PathText = "project"
    depth: int = Field(default=3, ge=0, le=10)
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0, le=100000)
    _path = field_validator("directory")(validate_path)


class SearchFilesArgs(Record):
    query: str = Field(min_length=1, max_length=1024)
    directory: PathText = "project"
    limit: int = Field(default=100, ge=1, le=1000)
    _path = field_validator("directory")(validate_path)


class GitDiffArgs(Record):
    repository: PathText = "project"
    paths: tuple[PathText, ...] = Field(default=(), max_length=100)
    _path = field_validator("repository")(validate_path)

    @field_validator("paths")
    @classmethod
    def safe_paths(cls, value):
        for path in value:
            validate_path(path)
        return value
