from typing import Protocol

from local_agent.contracts import ModelRequest, ModelResponse


class Provider(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse | dict: ...
