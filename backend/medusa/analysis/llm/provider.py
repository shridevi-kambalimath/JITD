"""LLM providers behind one small interface.

Every failure becomes an LLMError with a stable code, so the pipeline can decide what to do:
    auth            401/403: wrong or missing key. Not retried; LLM stops for this run.
    rate_limited    429 after all retries.
    timeout         no answer within MEDUSA_LLM_TIMEOUT_SECONDS after all retries.
    unavailable     connection error or 5xx/529 after all retries.
    bad_request     other 4xx (unknown model, bad parameter). Not retried.
    malformed_output the reply did not contain the expected JSON.
    misconfigured   settings incomplete (raised before any call).

The API key is sent only in the request header; it is never logged and never included in an error.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

import httpx

from ...core.config import Settings

logger = logging.getLogger("medusa.llm")
RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}
MAX_BACKOFF_SECONDS = 10.0


class LLMError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class LLMProvider(Protocol):
    name: str  # "<provider>/<model>", recorded on every claim this provider produced

    def complete_json(self, system: str, user: str) -> str: ...


class _HttpProvider:
    provider_id = "http"

    def __init__(self, model: str, api_key: str | None, base_url: str, timeout: float, max_retries: int,
                 transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep):
        self.model = model
        self.name = f"{self.provider_id}/{model}"
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    def _post(self, url: str, headers: dict[str, str], body: dict) -> dict:
        last: LLMError | None = None
        for attempt in range(self.max_retries + 1):
            retry_after: float | None = None
            try:
                with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                    r = client.post(url, headers=headers, json=body)
            except httpx.TimeoutException:
                last = LLMError("timeout", f"No answer from {self.name} within {self.timeout:g}s.")
            except httpx.TransportError as exc:
                last = LLMError("unavailable", f"Could not connect to {self.base_url} ({exc.__class__.__name__}).")
            else:
                if r.status_code < 300:
                    try:
                        return r.json()
                    except ValueError:
                        raise LLMError("malformed_output", "Provider returned a non-JSON HTTP body.") from None
                if r.status_code in (401, 403):
                    raise LLMError("auth", f"Provider rejected the credentials (HTTP {r.status_code}). Check MEDUSA_LLM_API_KEY.")
                if r.status_code not in RETRYABLE_STATUS:
                    raise LLMError("bad_request", f"Provider refused the request (HTTP {r.status_code}): {r.text[:200]}")
                code = "rate_limited" if r.status_code == 429 else "unavailable"
                last = LLMError(code, f"Provider answered HTTP {r.status_code}.")
                try:
                    retry_after = float(r.headers.get("retry-after", ""))
                except ValueError:
                    retry_after = None
            if attempt < self.max_retries:
                wait = min(retry_after if retry_after is not None else 2.0 ** attempt, MAX_BACKOFF_SECONDS)
                logger.warning("LLM call failed (%s), retry %d/%d in %.1fs", last.code, attempt + 1, self.max_retries, wait)
                self._sleep(wait)
        assert last is not None
        raise last


class AnthropicProvider(_HttpProvider):
    provider_id = "anthropic"

    def complete_json(self, system: str, user: str) -> str:
        data = self._post(f"{self.base_url}/v1/messages",
                          {"x-api-key": self._key or "", "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          {"model": self.model, "max_tokens": 4096, "temperature": 0, "system": system,
                           "messages": [{"role": "user", "content": user}]})
        try:
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError, AttributeError):
            raise LLMError("malformed_output", "Anthropic response had no text content.") from None
        if not text.strip():
            raise LLMError("malformed_output", "Anthropic response text was empty.")
        return text


class OpenAICompatibleProvider(_HttpProvider):
    provider_id = "openai_compatible"

    def complete_json(self, system: str, user: str) -> str:
        headers = {"content-type": "application/json"}
        if self._key:
            headers["authorization"] = f"Bearer {self._key}"
        data = self._post(f"{self.base_url}/chat/completions", headers,
                          {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("malformed_output", "Response had no choices[0].message.content.") from None
        if not isinstance(text, str) or not text.strip():
            raise LLMError("malformed_output", "Response content was empty.")
        return text


DEFAULT_BASE_URL = {"anthropic": "https://api.anthropic.com", "openai_compatible": "https://api.openai.com/v1"}


def llm_configuration(settings: Settings) -> tuple[str, str | None]:
    """('disabled' | 'misconfigured' | 'configured', reason). Never raises; used by the API and the pipeline."""
    if settings.llm_provider == "none":
        return "disabled", None
    if not settings.llm_model.strip():
        return "misconfigured", "MEDUSA_LLM_MODEL is not set."
    if settings.llm_provider == "anthropic" and settings.llm_api_key is None:
        return "misconfigured", "MEDUSA_LLM_API_KEY is not set (required for anthropic)."
    return "configured", None


def build_provider(settings: Settings, transport: httpx.BaseTransport | None = None) -> LLMProvider | None:
    status, _ = llm_configuration(settings)
    if status != "configured":
        return None
    cls = AnthropicProvider if settings.llm_provider == "anthropic" else OpenAICompatibleProvider
    key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    return cls(settings.llm_model.strip(), key, settings.llm_base_url.strip() or DEFAULT_BASE_URL[settings.llm_provider],
               settings.llm_timeout_seconds, settings.llm_max_retries, transport=transport)
