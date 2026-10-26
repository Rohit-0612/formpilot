"""A scripted provider for tests (invariant 5: unit tests never touch the network)."""

from collections.abc import Callable, Sequence

from app.llm.provider import LLMError, LLMProvider, LLMRequest

type Script = Sequence[str] | Callable[[LLMRequest], str]


class FakeProvider(LLMProvider):
    """Returns the scripted responses in order (or computes them), and records every request."""

    name = "fake"

    def __init__(self, script: Script, *, model: str = "fake", remote: bool = False) -> None:
        self.model = model
        self._script = script
        self._remote = remote
        self.requests: list[LLMRequest] = []

    @property
    def is_remote(self) -> bool:
        return self._remote

    def _complete(self, request: LLMRequest) -> str:
        self.requests.append(request)
        if callable(self._script):
            return self._script(request)
        if len(self.requests) > len(self._script):
            raise LLMError("fake: script exhausted")
        return self._script[len(self.requests) - 1]
