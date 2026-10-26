"""Groq (optional, SPEC §9) through its OpenAI-compatible chat API, with strict JSON-schema output.

Always remote, so the privacy guard in the base class applies: no value of a sensitive or phone
type is ever sent (CLAUDE.md §3). The understanding pass sends printed form text only.

The key comes from GROQ_API_KEY (app/config.py) and is never logged or put in an error message.
Without a key the provider can still be built, so a replay of recorded answers needs no key; a
real call then fails as an LLMError.
"""

import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr

from app.llm.provider import LLMError, LLMProvider, LLMRequest

# A rate-limited request (HTTP 429) is retried after Groq's retry-after, a few times and only if
# the wait is short: the analyze job has a deadline.
RATE_LIMIT_RETRIES = 3
MAX_RATE_LIMIT_WAIT = 60.0


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The schema as strict mode needs it: every object closed and every property required."""
    out = {key: _strict(value) for key, value in schema.items()}
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


def _strict(value: Any) -> Any:
    if isinstance(value, dict):
        return strict_schema(value)
    if isinstance(value, list):
        return [_strict(item) for item in value]
    return value


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(
        self,
        api_key: SecretStr | None,
        model: str,
        *,
        base_url: str = "https://api.groq.com/openai/v1",
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._sleep = sleep

    @property
    def is_remote(self) -> bool:
        return True

    def _complete(self, request: LLMRequest) -> str:
        if self._api_key is None or not self._api_key.get_secret_value():
            raise LLMError("groq: GROQ_API_KEY is not set")
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "answer",
                    "strict": True,
                    "schema": strict_schema(request.schema),
                },
            },
            "temperature": 0,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        try:
            response = self._post(body, headers)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"groq: HTTP {exc.response.status_code}") from None
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"groq: {type(exc).__name__}") from None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("groq: empty response")
        return content

    def _post(self, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        url = f"{self.base_url}/chat/completions"
        for _ in range(RATE_LIMIT_RETRIES):
            response = self._client.post(url, json=body, headers=headers)
            if response.status_code != 429:
                return response
            wait = _retry_after(response)
            if wait is None or wait > MAX_RATE_LIMIT_WAIT:
                return response
            self._sleep(wait)
        return self._client.post(url, json=body, headers=headers)

    def close(self) -> None:
        self._client.close()


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return max(0.0, float(response.headers["retry-after"]))
    except (KeyError, ValueError):
        return None
