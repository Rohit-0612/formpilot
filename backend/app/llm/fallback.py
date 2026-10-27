"""A primary provider with a fallback (decision P4-D1: Groq first, local Ollama when Groq fails).

Counts as remote if either provider is remote, so the privacy guard refuses a request carrying
sensitive or phone values before either provider sees it; each provider also guards itself.
"""

from app.llm.provider import LLMError, LLMProvider, LLMRequest, PrivacyError


class FallbackProvider(LLMProvider):
    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}+{fallback.name}"
        self.model = f"{primary.model}+{fallback.model}"

    @property
    def is_remote(self) -> bool:
        return self.primary.is_remote or self.fallback.is_remote

    def _complete(self, request: LLMRequest) -> str:
        try:
            return self.primary.complete_json(request)
        except PrivacyError:
            raise
        except LLMError:
            return self.fallback.complete_json(request)

    def close(self) -> None:
        self.primary.close()
        self.fallback.close()
