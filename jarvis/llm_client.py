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
import re
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

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"

# On-disk fallback for the Gemini key, mirroring main.py's
# ``.jarvis_api_key`` convention for Groq: a GUI assistant cannot rely on
# env vars surviving a relaunch, so the key is persisted here (mode 0600)
# alongside ``~`` user files and read only when $GEMINI_API_KEY is unset.
_GEMINI_KEY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".jarvis_gemini_key",
)


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
    "google": Provider(
        "google",
        # Gemini's OpenAI-compatible endpoint: reuses the whole 'openai'
        # request/parse path, so no API-key or body special-casing is needed.
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        os.environ.get("JARVIS_GEMINI_MODEL", "gemini-3.6-flash"),
        GEMINI_API_KEY_ENV,
        "openai",
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


def provider_api_key(provider: Provider) -> str:
    """Env-first, then the on-disk key file (same convention as Groq).

    Returns the raw key (never logged). The Gemini key survives relaunches
    because ``LLMClient`` resolves it from file when the env var is unset.
    """
    if not provider.api_key_env:
        return ""
    key = os.environ.get(provider.api_key_env, "").strip()
    if key:
        return key
    if provider.api_key_env == GEMINI_API_KEY_ENV:
        try:
            with open(_GEMINI_KEY_FILE, "r", encoding="utf-8") as f:
                return f.read().strip().strip("'\"")
        except Exception:
            return ""
    return ""


def configure_gemini_key(key: str) -> bool:
    """Persist a Gemini API key to the project key file (mode 0600).

    Returns True on success. Callers should treat the key as confidential:
    never log it, only ever display via :func:`mask_key`.
    """
    key = (key or "").strip().strip("'\"")
    if len(key) < 10:
        return False
    try:
        with open(_GEMINI_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(key)
        os.chmod(_GEMINI_KEY_FILE, 0o600)
        return True
    except Exception:
        logger.exception("failed to persist Gemini API key")
        return False


def gemini_configured() -> bool:
    """True when a Gemini key is available (env or the on-disk key file)."""
    return bool(provider_api_key(PROVIDERS["google"]))


def _post(url, json=None, headers=None, timeout=None):
    """Network seam: the single choke point tests may monkeypatch."""
    return requests.post(url, json=json, headers=headers, timeout=timeout)


def chat_anywhere(prompt, history=None, system="", chain=("groq", "google")):
    """Try providers in *chain* order; first non-empty reply wins.

    Skips backends whose API key is unset so the resilient paths can be
    stitched together from environment alone (Groq first, Gemini as the
    quota/outage escape hatch by default). Never raises.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    for name in chain:
        provider = PROVIDERS.get(name)
        if provider is None:
            continue
        if provider.api_key_env and not provider_api_key(provider):
            continue
        try:
            reply = LLMClient(provider=provider).chat(
                prompt, history=history, system=system)
        except Exception:
            logger.warning("chat_anywhere: %s failed", name, exc_info=True)
            reply = None
        if reply:
            return reply
    return None


_PLANNER_GATE = re.compile(
    r"\b(compare|contrast|difference between|pros and cons|trade.?off|"
    r"plan|outline|step.by.step|analy|evaluate|weigh|decide|choose "
    r"between|best approach|roadmap|architecture|strategy|design)\w*\b",
    re.I,
)

PLANNER_SYSTEM = (
    "You are the JARVIS planning layer. The user asked a hard, multi-step "
    "question that deserves more than a one-liner. Respond with a clear "
    "spoken plan or short structured analysis: numbered steps or a compact "
    "comparison. Under 120 words, no preamble or closing pleasantries, "
    "address the user as 'sir'."
)


def planner_reply(text, history=None):
    """Gemini-backed planner for genuinely multi-step questions.

    Fires only when a GEMINI_API_KEY is configured *and* the text looks like
    a hard problem (comparison / plan / trade-off / analysis). Everything
    else falls through untouched, so the fast Groq/local path is never
    slowed down. Returns plan text or ``None``.
    """
    if not gemini_configured():
        return None
    if not (isinstance(text, str) and 3 <= len(text) <= 4000):
        return None
    if not _PLANNER_GATE.search(text):
        return None
    try:
        reply = chat_anywhere(text, history=history, system=PLANNER_SYSTEM,
                              chain=("google",))
        if not reply:
            return None
        # Route Gemini output through the harness so spoken replies are
        # normalized exactly like Groq's (strip fences and butler chatter).
        try:
            from prompt_harness import clean_reply
            return clean_reply(reply) or reply
        except Exception:
            return reply
    except Exception:
        logger.warning("planner_reply failed", exc_info=True)
        return None


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
            text = self._chat_impl(prompt, history, system or "")
            # Contract: reply text or None. Empty bodies collapse to None
            # so callers testing ``is None`` get the documented failure.
            return (text or "").strip() or None
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
        return provider_api_key(self.provider)

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
            choices = data.get("choices")
            # Do not index a dict: some gateways return ``"choices": {}``.
            choice = choices[0] if isinstance(choices, list) and choices else {}
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
                    # Rate limits are transient; retry like 5xx instead of
                    # failing the turn outright. Other 4xx are fatal.
                    if status == 429:
                        last_err = "HTTP 429"
                        time.sleep(RETRY_SLEEP_SECONDS)
                        continue
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
