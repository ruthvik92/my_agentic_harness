from typing import Protocol

from local_agent.contracts import ExecutionRequest


class Executor(Protocol):
    async def execute(self, request: ExecutionRequest) -> dict: ...
