"""Ollama (the local default, SPEC §9) through its HTTP chat API, with JSON-schema output.

Remote unless both the host and the model are local: Ollama also serves cloud models (tags such
as `qwen3.5:cloud`) that run on Ollama's servers, and a non-local host is another machine.
`host.docker.internal` is this machine, seen from a container.
"""

from urllib.parse import urlparse

import httpx

from app.llm.provider import LLMError, LLMProvider, LLMRequest

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
# Ollama's default context (4096 tokens) is too small for the understanding prompt plus a batch.
NUM_CTX = 8192


def is_cloud_model(model: str) -> bool:
    tag = model.rpartition(":")[2] if ":" in model else ""
    return tag == "cloud" or tag.endswith("-cloud")


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = 300.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = client or httpx.Client(timeout=timeout_seconds)

    @property
    def is_remote(self) -> bool:
        host = urlparse(self.base_url).hostname or ""
        return host not in LOCAL_HOSTS or is_cloud_model(self.model)

    def _complete(self, request: LLMRequest) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "format": request.schema,  # Ollama constrains the output to this JSON schema
            "stream": False,
            "think": False,  # reasoning models (qwen3) answer directly
            "options": {"temperature": 0, "num_ctx": NUM_CTX},
        }
        try:
            response = self._client.post(f"{self.base_url}/api/chat", json=body)
            response.raise_for_status()
            content = response.json()["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise LLMError(f"ollama: {type(exc).__name__}") from None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("ollama: empty response")
        return content
