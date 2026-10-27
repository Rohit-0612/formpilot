"""The provider interface and the privacy guard every provider passes through.

A request says which semantic types' *values* it carries (`carries`). Values of the sensitive
types (decision D2) and of the phone types are never sent to a remote provider: the base class
refuses such a request before the subclass sees it (CLAUDE.md §3, SPEC §11). The understanding
pass sends printed form text only (labels, headings), so its requests carry no values.

Providers are synchronous: passes are plain functions and run in the worker's analysis thread.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.ir.semantic_types import PHONE_TYPES, SENSITIVE_TYPES, SemanticType

# Never sent to a remote provider (human decision, 2026-10-26).
NEVER_REMOTE: frozenset[SemanticType] = SENSITIVE_TYPES | PHONE_TYPES


class LLMError(Exception):
    """The provider failed or returned nothing usable; callers fall back (e.g. to `unknown`)."""


class PrivacyError(LLMError):
    """A request carrying values that must not leave the machine was sent to a remote provider."""


@dataclass(frozen=True)
class LLMRequest:
    system: str  # the versioned prompt (llm/prompts/)
    user: str  # the request's data, usually JSON
    schema: dict[str, Any]  # JSON schema the output must follow
    # The semantic types whose values the request holds; empty for printed form text only.
    carries: frozenset[SemanticType] = field(default_factory=frozenset)


class LLMProvider(ABC):
    """Returns the model's raw JSON text; callers validate it with Pydantic (invariant 4)."""

    name: str
    model: str

    @property
    @abstractmethod
    def is_remote(self) -> bool:
        """True if the request leaves this machine."""

    def complete_json(self, request: LLMRequest) -> str:
        if self.is_remote and request.carries & NEVER_REMOTE:
            raise PrivacyError(f"{self.name}: request carries values that must stay local")
        return self._complete(request)

    @abstractmethod
    def _complete(self, request: LLMRequest) -> str: ...

    def close(self) -> None:
        """Release connections, if any."""
        return None
