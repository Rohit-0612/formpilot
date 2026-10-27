"""The configured provider, or None when the understanding pass runs its rules only."""

from app.config import Settings
from app.llm.fallback import FallbackProvider
from app.llm.groq import GroqProvider
from app.llm.ollama import OllamaProvider
from app.llm.provider import LLMProvider


def provider_from_settings(settings: Settings) -> LLMProvider | None:
    choice = settings.llm_provider
    if choice == "none":
        return None
    has_key = settings.groq_api_key is not None and bool(settings.groq_api_key.get_secret_value())
    ollama = OllamaProvider(
        settings.ollama_base_url,
        settings.ollama_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    if choice == "ollama" or (choice == "auto" and not has_key):
        return ollama
    groq = GroqProvider(
        settings.groq_api_key,
        settings.groq_model,
        base_url=settings.groq_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    if choice == "groq":
        ollama.close()
        return groq
    return FallbackProvider(groq, ollama)  # auto with a key (P4-D1)
