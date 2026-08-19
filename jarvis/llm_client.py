"""Any-backend LLM abstraction for JARVIS.

Lets Jarvis talk to Groq / OpenAI-compatible endpoints, a local Ollama
server, or Anthropic without hardwiring any provider. Select the backend
via the ``JARVIS_PROVIDER`` environment variable (a key in ``PROVIDERS``)
or by passing a :class:`Provider` to :class:`LLMClient`.

Contract mirrors ``main.ask_ai``: :meth:`LLMClient.chat` returns assistant
text or ``None`` on failure, and never raises. API keys are read from the
environment and are never logged verbatim -- use :func:`mask_key`.
"""

import os
import time
from dataclasses import dataclass

import requests

from jarvis_logging import get_logger

logger = get_logger("llm_client")

ANTHROPIC_VERSION = "2023-06-01"
RETRY_SLEEP_SECONDS = 0.8
MAX_ATTEMPTS = 2
HISTORY_WINDOW = 10
TEMPERATURE = 0.8


@dataclass(frozen=True)
class Provider:
    """Connection details for one LLM backend."""

    name: str
    base_url: str
    model: str
    api_key_env: str  # "" when the backend needs no key (e.g. local Ollama)
    style: str  # 'openai' | 'anthropic' | 'ollama'


PROVIDERS = {
    "groq": Provider(
        "groq",
        "https://api.groq.com/openai/v1/chat/completions",
        "openai/gpt-oss-20b",
        "GROQ_API_KEY",
        "openai",
    ),
    "openai": Provider(
        "openai",
        "https://api.openai.com/v1/chat/completions",
        "gpt-4o-mini",
        "OPENAI_API_KEY",
        "openai",
    ),
    "ollama": Provider(
        "ollama",
        "http://localhost:11434/api/chat",
        "llama3.2",
        "",
        "ollama",
    ),
    "anthropic": Provider(
        "anthropic",
        "https://api.anthropic.com/v1/messages",
        "claude-3-5-haiku-latest",
        "ANTHROPIC_API_KEY",
        "anthropic",
    ),
}

_STYLES_NEEDING_KEY = ("openai", "anthropic")


def active_provider() -> Provider:
    """Return the Provider named by ``$JARVIS_PROVIDER``, defaulting to Groq."""
    name = os.environ.get("JARVIS_PROVIDER", "").strip().lower()
    return PROVIDERS.get(name, PROVIDERS["groq"])


def mask_key(secret: str) -> str:
    """Return a display-safe form of *secret*, revealing only the last 4 chars."""
    secret = secret or ""
    if len(secret) <= 4:
        return "*" * len(secret)
    return "*" * 8 + secret[-4:]


def _post(url, json=None, headers=None, timeout=None):
    """Network seam: the single choke point tests may monkeypatch."""
    return requests.post(url, json=json, headers=headers, timeout=timeout)


class LLMClient:
    """Chat with any configured provider; failures collapse to ``None``."""

    def __init__(self, provider: Provider | None = None, timeout: int = 15):
        self.provider = provider or active_provider()
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def chat(self, prompt: str, history: list | None = None,
             system: str | None = "") -> str | None:
        """Send *prompt* (plus optional history/system) and return reply text.

        Returns ``None`` when the provider's API key is missing or on any
        transport/parse failure. Never raises.
        """
        try:
            return self._chat_impl(prompt, history, system or "")
        except Exception:
            logger.exception("chat failed unexpectedly")
            return None

    def chat_validated_text(self, prompt: str, history: list | None = None,
                            system: str | None = "") -> str | None:
        """Thin alias: stripped reply text, or ``None`` when empty/unavailable."""
        text = self.chat(prompt, history, system)
        if not text:
            return None
        return text.strip() or None

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _api_key(self) -> str:
        env = self.provider.api_key_env
        return os.environ.get(env, "").strip() if env else ""

    def _messages(self, prompt: str, history, system: str) -> list:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        if history:
            msgs.extend(list(history)[-HISTORY_WINDOW:])
        if (not msgs or msgs[-1].get("role") != "user"
                or msgs[-1].get("content") != prompt):
            msgs.append({"role": "user", "content": prompt})
        return msgs

    def _build_headers(self, key: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.provider.style == "anthropic":
            headers["x-api-key"] = key
            headers["anthropic-version"] = ANTHROPIC_VERSION
        elif self.provider.style == "openai" and key:
            headers["Authorization"] = "Bearer " + key
        return headers

    def _build_payload(self, prompt: str, history, system: str) -> dict:
        p = self.provider
        if p.style == "anthropic":
            payload = {
                "model": p.model,
                "max_tokens": 1024,
                "messages": self._messages(prompt, history, system=""),
            }
            if system:
                payload["system"] = system
            return payload
        if p.style == "ollama":
            return {
                "model": p.model,
                "messages": self._messages(prompt, history, system),
                "stream": False,
            }
        return {
            "model": p.model,
            "messages": self._messages(prompt, history, system),
            "temperature": TEMPERATURE,
        }

    def _extract_text(self, data: dict) -> str:
        style = self.provider.style
        if style == "anthropic":
            blocks = data.get("content") or []
            text = blocks[0].get("text", "") if blocks else ""
        elif style == "ollama":
            text = (data.get("message") or {}).get("content", "")
        else:
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            # Reasoning models can spend every token thinking; surface that.
            text = msg.get("content", "") or msg.get("reasoning", "") or ""
        return text.strip() if isinstance(text, str) else ""

    def _chat_impl(self, prompt: str, history, system: str) -> str | None:
        p = self.provider
        key = self._api_key()
        if p.style in _STYLES_NEEDING_KEY and not key:
            logger.warning(
                "provider %r needs an API key; set %s (current value: %s)",
                p.name, p.api_key_env, mask_key(key),
            )
            return None

        headers = self._build_headers(key)
        payload = self._build_payload(prompt, history, system)

        last_err = None
        for _ in range(MAX_ATTEMPTS):
            try:
                resp = _post(p.base_url, json=payload, headers=headers,
                             timeout=self.timeout)
                status = getattr(resp, "status_code", 0)
                if status == 401:
                    logger.error("%s rejected credentials (HTTP 401)", p.name)
                    return None
                if 500 <= status <= 599:
                    last_err = "HTTP %s" % status
                    time.sleep(RETRY_SLEEP_SECONDS)
                    continue
                if not 200 <= status < 300:
                    logger.error("%s returned HTTP %s", p.name, status)
                    return None
                return self._extract_text(resp.json())
            except Exception as exc:
                last_err = type(exc).__name__
                logger.warning("%s request error (%s); will retry once",
                               p.name, last_err)
                time.sleep(RETRY_SLEEP_SECONDS)
        logger.error("chat via %s failed after %d attempts (%s)",
                     p.name, MAX_ATTEMPTS, last_err)
        return None
