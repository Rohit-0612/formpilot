"""The configured provider, or None when the understanding pass runs its rules only."""

from app.config import Settings
from app.llm.ollama import OllamaProvider
from app.llm.provider import LLMProvider


def provider_from_settings(settings: Settings) -> LLMProvider | None:
    if settings.llm_provider == "ollama":
        return OllamaProvider(
            settings.ollama_base_url,
            settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return None
