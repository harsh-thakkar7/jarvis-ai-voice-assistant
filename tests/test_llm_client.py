"""Tests for llm_client: provider matrix, retries, parsing, key masking."""

from types import SimpleNamespace

import pytest
import requests

import llm_client
from llm_client import LLMClient, PROVIDERS, active_provider, mask_key


# --------------------------------------------------------------------------- #
# Fakes / fixtures
# --------------------------------------------------------------------------- #

class FakeResp:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data


class Recorder:
    """Monkeypatchable _post seam: records calls, yields canned replies.

    Entries in *replies* may be FakeResp instances or Exception instances
    (raised to simulate timeouts / connection errors).
    """

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        item = self.replies.pop(0) if self.replies else FakeResp(200, {})
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("JARVIS_PROVIDER", "GROQ_API_KEY",
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    monkeypatch.setattr(llm_client.time, "sleep", lambda _s: None)


def install(monkeypatch, replies=None):
    rec = Recorder(replies)
    monkeypatch.setattr(llm_client, "_post", rec)
    return rec


KEYED = ("groq", "openai", "anthropic")


# --------------------------------------------------------------------------- #
# Provider selection + masking
# --------------------------------------------------------------------------- #

def test_active_provider_defaults_to_groq():
    assert active_provider() is PROVIDERS["groq"]
    assert LLMClient().provider is PROVIDERS["groq"]


def test_active_provider_from_env_and_unknown_falls_back(monkeypatch):
    monkeypatch.setenv("JARVIS_PROVIDER", "ollama")
    assert active_provider() is PROVIDERS["ollama"]
    monkeypatch.setenv("JARVIS_PROVIDER", "does-not-exist")
    assert active_provider() is PROVIDERS["groq"]


def test_mask_key_reveals_only_last4():
    secret = "sk-super-secret-1234abcd"
    masked = mask_key(secret)
    assert masked.endswith("abcd")
    assert secret not in masked
    assert len(masked) < len(secret)
    # Short secrets are fully hidden.
    assert set(mask_key("abc")) == {"*"}
    assert mask_key("abcd") == "****"
    assert mask_key("") == ""


# --------------------------------------------------------------------------- #
# Per-style request building matrix
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", KEYED)
def test_keyed_providers_include_auth_header_when_key_set(monkeypatch, name):
    monkeypatch.setenv(PROVIDERS[name].api_key_env, "sk-test-9876zyxw")
    rec = install(monkeypatch, [FakeResp(200, {})])
    LLMClient(provider=PROVIDERS[name]).chat("ping")
    headers = rec.calls[0]["headers"]
    if PROVIDERS[name].style == "anthropic":
        assert headers["x-api-key"] == "sk-test-9876zyxw"
        assert headers["anthropic-version"]
        assert "Authorization" not in headers
    else:
        assert headers["Authorization"] == "Bearer sk-test-9876zyxw"


@pytest.mark.parametrize("name", KEYED)
def test_missing_key_returns_none_without_network_call(monkeypatch, name):
    rec = install(monkeypatch)  # any call would still be recorded
    assert LLMClient(provider=PROVIDERS[name]).chat("hi") is None
    assert rec.calls == []


def test_ollama_is_keyless_but_never_sends_auth(monkeypatch):
    rec = install(monkeypatch, [FakeResp(200, {"message": {"content": "yo"}})])
    assert LLMClient(provider=PROVIDERS["ollama"]).chat("hi") == "yo"
    headers = rec.calls[0]["headers"]
    assert "Authorization" not in headers
    assert "x-api-key" not in headers


@pytest.mark.parametrize("name", list(PROVIDERS))
def test_matrix_url_headers_payload_shape(monkeypatch, name):
    p = PROVIDERS[name]
    if p.api_key_env:
        monkeypatch.setenv(p.api_key_env, "sk-test-9876zyxw")
    history = [{"role": "user", "content": "earlier"},
               {"role": "assistant", "content": "yes sir"}]
    rec = install(
        monkeypatch,
        [FakeResp(200, {"choices": [{"message": {"content": "ok"}}],
                         "content": [{"text": "ok"}],
                         "message": {"content": "ok"}})],
    )
    out = LLMClient(provider=p).chat("hello", history=list(history),
                                     system="be brief")
    assert out == "ok"

    call = rec.calls[0]
    assert call["url"] == p.base_url
    payload = call["json"]

    if p.style == "openai":
        assert set(payload) == {"model", "messages", "temperature"}
        assert payload["model"] == p.model
        assert payload["temperature"] == 0.8
        roles = [m["role"] for m in payload["messages"]]
        assert roles == ["system", "user", "assistant", "user"]
        assert payload["messages"][0]["content"] == "be brief"
        assert payload["messages"][-1] == {"role": "user", "content": "hello"}
    elif p.style == "anthropic":
        assert set(payload) >= {"model", "max_tokens", "system", "messages"}
        assert payload["model"] == p.model
        assert payload["system"] == "be brief"
        roles = [m["role"] for m in payload["messages"]]
        assert roles == ["user", "assistant", "user"]  # no system role inside
        assert "temperature" not in payload
    elif p.style == "ollama":
        assert payload["stream"] is False
        assert payload["model"] == p.model
        roles = [m["role"] for m in payload["messages"]]
        assert roles == ["system", "user", "assistant", "user"]


def test_history_window_trims_to_last_ten(monkeypatch):
    rec = install(monkeypatch,
                  [FakeResp(200, {"message": {"content": "ok"}})])
    big_history = [{"role": "user", "content": f"m{i}"} for i in range(15)]
    LLMClient(provider=PROVIDERS["ollama"]).chat("go", history=big_history)
    msgs = rec.calls[0]["json"]["messages"]
    assert len(msgs) == 11  # last 10 history turns + the new user prompt
    assert msgs[0]["content"] == "m5"
    assert msgs[-1] == {"role": "user", "content": "go"}


# --------------------------------------------------------------------------- #
# Status-code handling and retry semantics
# --------------------------------------------------------------------------- #

def test_401_returns_none_without_retry(monkeypatch):
    rec = install(monkeypatch, [FakeResp(401, {"error": "bad key"})])
    monkeypatch.setenv("GROQ_API_KEY", "sk-test-9876zyxw")
    assert LLMClient(provider=PROVIDERS["groq"]).chat("hi") is None
    assert len(rec.calls) == 1


def test_500_then_200_retries_once(monkeypatch):
    rec = install(monkeypatch, [
        FakeResp(500, {}),
        FakeResp(200, {"choices": [{"message": {"content": "recovered"}}]}),
    ])
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-9876zyxw")
    out = LLMClient(provider=PROVIDERS["openai"]).chat("hi")
    assert out == "recovered"
    assert len(rec.calls) == 2


def test_timeout_then_success_retries_once(monkeypatch):
    rec = install(monkeypatch, [
        requests.exceptions.Timeout("too slow"),
        FakeResp(200, {"message": {"content": "ollama ok"}}),
    ])
    out = LLMClient(provider=PROVIDERS["ollama"]).chat("hi")
    assert out == "ollama ok"
    assert len(rec.calls) == 2


def test_persistent_failure_returns_none_after_two_attempts(monkeypatch):
    rec = install(monkeypatch, [
        FakeResp(503, {}),
        requests.exceptions.ConnectionError("no route"),
    ])
    monkeypatch.setenv("GROQ_API_KEY", "sk-test-9876zyxw")
    assert LLMClient(provider=PROVIDERS["groq"]).chat("hi") is None
    assert len(rec.calls) == 2


def test_other_error_status_no_retry(monkeypatch):
    rec = install(monkeypatch, [FakeResp(400, {"error": "bad"})])
    monkeypatch.setenv("GROQ_API_KEY", "sk-test-9876zyxw")
    assert LLMClient(provider=PROVIDERS["groq"]).chat("hi") is None
    assert len(rec.calls) == 1


def test_never_raises_on_garbage_response(monkeypatch):
    class Boom:
        status_code = 200

        def json(self):
            raise ValueError("not json")

    install(monkeypatch, [Boom(), Boom()])
    monkeypatch.setenv("GROQ_API_KEY", "sk-test-9876zyxw")
    assert LLMClient(provider=PROVIDERS["groq"]).chat("hi") is None


# --------------------------------------------------------------------------- #
# Response parsing per style
# --------------------------------------------------------------------------- #

def test_ollama_parses_message_content(monkeypatch):
    install(monkeypatch, [FakeResp(200, {"message": {"content": " hi there "}})])
    assert LLMClient(provider=PROVIDERS["ollama"]).chat("q") == "hi there"


def test_anthropic_parses_content_blocks_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-9876zyxw")
    install(monkeypatch, [
        FakeResp(200, {"content": [{"type": "text", "text": " hello sir "}]})
    ])
    assert LLMClient(provider=PROVIDERS["anthropic"]).chat("q") == "hello sir"


def test_openai_parses_choices_and_reasoning_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-test-9876zyxw")
    install(monkeypatch, [
        FakeResp(200, {"choices": [{"message": {"content": "", "reasoning": "hmm"}}]})
    ])
    assert LLMClient(provider=PROVIDERS["groq"]).chat("q") == "hmm"


def test_empty_content_yields_empty_string(monkeypatch):
    install(monkeypatch, [FakeResp(200, {"choices": [{"message": {"content": "  "}}]})])
    monkeypatch.setenv("GROQ_API_KEY", "sk-test-9876zyxw")
    client = LLMClient(provider=PROVIDERS["groq"])
    assert client.chat("q") == ""
    assert client.chat_validated_text("q") is None


# --------------------------------------------------------------------------- #
# Alias behaviour
# --------------------------------------------------------------------------- #

def test_chat_validated_text_alias(monkeypatch):
    install(monkeypatch, [
        FakeResp(200, {"message": {"content": "  padded reply \n"}}),
    ])
    client = LLMClient(provider=PROVIDERS["ollama"])
    assert client.chat_validated_text("q") == "padded reply"

    install(monkeypatch, [FakeResp(502, {}), FakeResp(502, {})])
    assert client.chat_validated_text("q") is None


def test_timeout_kwarg_forwarded_to_seam(monkeypatch):
    rec = install(monkeypatch, [FakeResp(200, {"message": {"content": "k"}})])
    LLMClient(provider=PROVIDERS["ollama"], timeout=42).chat("q")
    assert rec.calls[0]["timeout"] == 42


def test_module_exports_expected_surface():
    for attr in ("Provider", "PROVIDERS", "active_provider",
                 "LLMClient", "mask_key", "_post"):
        assert hasattr(llm_client, attr)
