from typing import Protocol

from local_agent.contracts import ExecutionMode, ExecutionRequest, ExecutionResult


class Executor(Protocol):
    """Legacy dictionary interface for scripted/mock execution only."""

    async def execute(self, request: ExecutionRequest) -> dict: ...


class LiveExecutor(Protocol):
    """Live dispatch and release capability; excludes backend-specific recovery APIs."""

    async def execute(
        self,
        request: ExecutionRequest,
        *,
        execution_mode: ExecutionMode | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult: ...

    async def release(self, execution_id: str) -> None: ...
