"""Record / replay of model responses (SPEC §9 "LLM cache"): CI evals run without a model.

The key is the SHA-256 of (provider, model, prompt, request, schema), so any change to the prompt
or the schema misses the cache instead of returning a stale answer. One JSON file per response,
holding only the response text (the understanding pass sends printed form text, no values).
"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from app.llm.provider import LLMError, LLMProvider, LLMRequest

type CacheMode = Literal["record", "replay"]


def cache_key(provider: str, model: str, request: LLMRequest) -> str:
    payload = json.dumps(
        {
            "provider": provider,
            "model": model,
            "system": request.system,
            "user": request.user,
            "schema": request.schema,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class CachedProvider(LLMProvider):
    """`record`: call the inner provider and store the answer (a stored answer is reused).
    `replay`: answer from the cache only; a miss is an error, never a model call."""

    def __init__(self, inner: LLMProvider, directory: Path, mode: CacheMode) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.directory = directory
        self.mode = mode

    @property
    def is_remote(self) -> bool:
        return self.inner.is_remote  # the privacy guard applies whether or not the cache hits

    def _complete(self, request: LLMRequest) -> str:
        path = self.directory / f"{cache_key(self.name, self.model, request)}.json"
        if path.exists():
            return str(json.loads(path.read_text())["response"])
        if self.mode == "replay":
            raise LLMError("cache: no recorded response for this request")
        response = self.inner.complete_json(request)
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"response": response}, ensure_ascii=False, indent=1) + "\n")
        return response
