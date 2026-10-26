"""LLM layer (Phase 3): privacy guard, Ollama request and errors, fake provider, record / replay.

No network: Ollama is reached through httpx.MockTransport.
"""

import json
from pathlib import Path

import httpx
import pytest

from app.ir.semantic_types import SENSITIVE_TYPES, SemanticType
from app.llm.cache import CachedProvider, cache_key
from app.llm.fake import FakeProvider
from app.llm.ollama import OllamaProvider, is_cloud_model
from app.llm.provider import NEVER_REMOTE, LLMError, LLMRequest, PrivacyError

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def _request(**overrides: object) -> LLMRequest:
    values: dict[str, object] = {"system": "Answer.", "user": '{"q": 1}', "schema": SCHEMA}
    values.update(overrides)
    return LLMRequest(**values)  # type: ignore[arg-type]


def _ollama(handler: object, base_url: str = "http://localhost:11434", model: str = "qwen3:8b"):
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return OllamaProvider(base_url, model, client=client)


# --- privacy guard ------------------------------------------------------------------------


def test_never_remote_is_the_sensitive_types_plus_phones() -> None:
    phones = {SemanticType.PHONE_MOBILE, SemanticType.PHONE_ALTERNATE}

    assert SENSITIVE_TYPES <= NEVER_REMOTE
    assert phones == NEVER_REMOTE - SENSITIVE_TYPES
    assert {SemanticType.AADHAAR, SemanticType.VOTER_ID} <= NEVER_REMOTE


@pytest.mark.parametrize("carried", [SemanticType.PAN, SemanticType.PHONE_MOBILE])
def test_remote_provider_refuses_sensitive_or_phone_values(carried: SemanticType) -> None:
    provider = FakeProvider(['{"ok": true}'], remote=True)

    with pytest.raises(PrivacyError):
        provider.complete_json(_request(carries=frozenset({carried})))

    assert provider.requests == []  # refused before the provider saw anything


def test_remote_provider_accepts_other_values_and_local_accepts_all() -> None:
    address = _request(carries=frozenset({SemanticType.CURRENT_ADDRESS_LINE1}))
    pan = _request(carries=frozenset({SemanticType.PAN}))

    assert FakeProvider(['{"ok": true}'], remote=True).complete_json(address) == '{"ok": true}'
    assert FakeProvider(['{"ok": true}']).complete_json(pan) == '{"ok": true}'


@pytest.mark.parametrize(
    ("base_url", "model", "remote"),
    [
        ("http://localhost:11434", "qwen3:8b", False),
        ("http://127.0.0.1:11434", "qwen3:8b", False),
        ("http://host.docker.internal:11434", "qwen3:8b", False),
        ("http://localhost:11434", "qwen3.5:cloud", True),
        ("http://localhost:11434", "gpt-oss:120b-cloud", True),
        ("https://ollama.example.com", "qwen3:8b", True),
    ],
)
def test_ollama_is_remote_for_cloud_models_and_other_hosts(
    base_url: str, model: str, remote: bool
) -> None:
    assert OllamaProvider(base_url, model).is_remote is remote


def test_cloud_model_tags() -> None:
    assert is_cloud_model("kimi-k2.6:cloud")
    assert not is_cloud_model("qwen3:8b")
    assert not is_cloud_model("cloudy-model")


def test_ollama_cloud_model_refuses_a_pan_without_any_http_call() -> None:
    calls: list[httpx.Request] = []
    provider = _ollama(lambda r: calls.append(r) or httpx.Response(200), model="qwen3.5:cloud")

    with pytest.raises(PrivacyError):
        provider.complete_json(_request(carries=frozenset({SemanticType.PAN})))

    assert calls == []


# --- Ollama ---------------------------------------------------------------------------------


def test_ollama_sends_a_schema_constrained_deterministic_chat() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.url.path == "/api/chat"
        return httpx.Response(200, json={"message": {"role": "assistant", "content": '{"ok":1}'}})

    assert _ollama(handler).complete_json(_request()) == '{"ok":1}'
    body = seen[0]
    assert body["model"] == "qwen3:8b"
    assert body["format"] == SCHEMA
    assert body["stream"] is False and body["think"] is False
    assert body["options"] == {"temperature": 0}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(200, json={"error": "no message"}),
        httpx.Response(200, json={"message": {"content": "  "}}),
        httpx.Response(200, text="not json"),
    ],
)
def test_ollama_failures_are_llm_errors(response: httpx.Response) -> None:
    with pytest.raises(LLMError):
        _ollama(lambda _: response).complete_json(_request())


def test_ollama_connection_error_is_an_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError):
        _ollama(handler).complete_json(_request())


# --- fake provider ----------------------------------------------------------------------------


def test_fake_provider_scripts_and_records() -> None:
    provider = FakeProvider(["a", "b"])

    assert [provider.complete_json(_request()) for _ in range(2)] == ["a", "b"]
    assert len(provider.requests) == 2
    with pytest.raises(LLMError):
        provider.complete_json(_request())


# --- record / replay ------------------------------------------------------------------------------


def test_record_then_replay_without_the_model(tmp_path: Path) -> None:
    recorder = CachedProvider(FakeProvider(['{"ok": true}']), tmp_path, "record")
    assert recorder.complete_json(_request()) == '{"ok": true}'

    silent = FakeProvider([])  # replay must never call the model
    replay = CachedProvider(silent, tmp_path, "replay")

    assert replay.complete_json(_request()) == '{"ok": true}'
    assert silent.requests == []


def test_replay_miss_is_an_error_not_a_model_call(tmp_path: Path) -> None:
    silent = FakeProvider([])

    with pytest.raises(LLMError):
        CachedProvider(silent, tmp_path, "replay").complete_json(_request())
    assert silent.requests == []


def test_cache_key_changes_with_prompt_schema_and_model() -> None:
    base = cache_key("ollama", "qwen3:8b", _request())

    assert base == cache_key("ollama", "qwen3:8b", _request())
    assert base != cache_key("ollama", "qwen3:8b", _request(system="Answer again."))
    assert base != cache_key("ollama", "qwen3:8b", _request(schema={"type": "object"}))
    assert base != cache_key("ollama", "qwen3:4b", _request())


def test_cached_remote_provider_still_guards(tmp_path: Path) -> None:
    cached = CachedProvider(FakeProvider([], remote=True), tmp_path, "record")

    with pytest.raises(PrivacyError):
        cached.complete_json(_request(carries=frozenset({SemanticType.AADHAAR})))
