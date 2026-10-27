"""What a pass may use besides the IR (invariant 2): the clock, the LLM provider, the profile,
settings."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo

from app.llm.provider import LLMProvider

type UnderstandMode = Literal["hybrid", "rules", "llm"]

INDIA = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class PassContext:
    clock: Callable[[], datetime]
    provider: LLMProvider | None = None  # None: the understanding pass runs its rules only
    review_threshold: float = 0.7  # semantic confidence below this -> NEEDS_REVIEW (SPEC §6.2)
    # The eval compares rules only, LLM only and both (SPEC §6.2); the product runs "hybrid".
    understand_mode: UnderstandMode = "hybrid"
    # LLM calls stop at this time (by `clock`): the analyze job must end within its timeout.
    deadline: datetime | None = None
    # Phase 4: the user's profile (profile key -> value, decrypted), read by the match pass.
    profile: Mapping[str, str] = field(default_factory=dict)
    # The fill policy's LLM confidence floor (decision P4-D2).
    fill_min_confidence: float = 0.95
    # The fit pass (SPEC §6.7): default and smallest font size, in points.
    fit_font_size: float = 10.0
    fit_min_font_size: float = 6.0
    # "Today" for dates on the form (date of filling, age, DOB not in the future).
    timezone: tzinfo = INDIA

    def today(self) -> date:
        return self.clock().astimezone(self.timezone).date()
