"""What a pass may use besides the IR (invariant 2): the clock, the LLM provider, settings."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.llm.provider import LLMProvider

type UnderstandMode = Literal["hybrid", "rules", "llm"]


@dataclass(frozen=True)
class PassContext:
    clock: Callable[[], datetime]
    provider: LLMProvider | None = None  # None: the understanding pass runs its rules only
    review_threshold: float = 0.7  # semantic confidence below this -> NEEDS_REVIEW (SPEC §6.2)
    # The eval compares rules only, LLM only and both (SPEC §6.2); the product runs "hybrid".
    understand_mode: UnderstandMode = "hybrid"
    # LLM calls stop at this time (by `clock`): the analyze job must end within its timeout.
    deadline: datetime | None = None
