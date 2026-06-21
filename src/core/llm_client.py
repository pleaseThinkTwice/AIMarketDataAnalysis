"""LLM API client for DeepSeek-V3 (OpenAI-compatible endpoint).

Wraps the OpenAI SDK with:
- Tenacity retry (exponential backoff, max 3 attempts)
- Structured JSON mode support
- Token usage tracking
- Timeout handling

Usage:
    from src.core.config import load_config
    from src.core.llm_client import LLMClient

    cfg = load_config()
    client = LLMClient(cfg)
    resp = client.chat([
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ])
    print(resp.content)
"""

from __future__ import annotations

import json
import time
from typing import Any

from openai import OpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    RetryError,
)

from src.core.schemas import LLMResponse

# Try to import config type for type hints
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.core.config import AppConfig


# ---------------------------------------------------------------------------
# Retry configuration helper
# ---------------------------------------------------------------------------

def _build_retry_decorator(max_attempts: int, base_delay_s: float, backoff_multiplier: float):
    """Build a tenacity retry decorator with exponential backoff.

    Retries on: OpenAI API errors (rate limit, server errors), connection errors.
    Does NOT retry on: timeout (the request itself is the problem), bad request (4xx client errors).
    """
    return retry(
        retry=retry_if_exception_type((
            Exception,  # catch all OpenAI/httpx exceptions
        )),
        wait=wait_exponential(multiplier=base_delay_s, min=base_delay_s, max=30),
        stop=stop_after_attempt(max_attempts),
        reraise=True,
    )


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------


class LLMClient:
    """DeepSeek-V3 API client with retry, JSON mode, and token counting."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._api_key = config.llm.api_key
        self._base_url = config.llm.api_base
        self._model = config.llm.model
        self._timeout = config.llm.timeout_s
        self._max_tokens = config.llm.max_tokens

        self._client = OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request with retry.

        Args:
            messages: List of {"role": "...", "content": "..."} dicts.
            temperature: Override default temperature. If None, uses 0.1.
            json_mode: If True, request JSON response format (DeepSeek supports
                       response_format={"type": "json_object"}).
            max_tokens: Override default max_tokens.

        Returns:
            LLMResponse with content, token counts, model, and timing.

        Raises:
            RuntimeError: If all retry attempts fail.
        """
        temp = temperature if temperature is not None else 0.1
        mt = max_tokens if max_tokens is not None else self._max_tokens

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": mt,
        }

        if json_mode:
            # DeepSeek supports OpenAI-compatible JSON mode
            kwargs["response_format"] = {"type": "json_object"}

        retryer = _build_retry_decorator(
            max_attempts=self._config.llm.retry.max_attempts,
            base_delay_s=self._config.llm.retry.base_delay_s,
            backoff_multiplier=self._config.llm.retry.backoff_multiplier,
        )

        @retryer
        def _call() -> LLMResponse:
            return self._do_call(kwargs)

        try:
            return _call()
        except RetryError as e:
            # All retries exhausted
            last_error = e.last_attempt.exception() if e.last_attempt else None
            raise RuntimeError(
                f"LLM API call failed after {self._config.llm.retry.max_attempts} "
                f"retries. Last error: {last_error}"
            ) from e

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        json_mode: bool = True,  # accepted for caller compatibility, always True
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Send a chat request and parse the response as JSON.

        Returns:
            Parsed JSON dict. Returns {} if parsing fails.
        """
        response = self.chat(
            messages,
            temperature=temperature,
            json_mode=True,
            max_tokens=max_tokens,
        )
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            # Attempt to extract JSON from markdown code blocks
            content = response.content
            if "```json" in content:
                start = content.index("```json") + 7
                end = content.index("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.index("```") + 3
                end = content.index("```", start)
                content = content[start:end].strip()
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _do_call(self, kwargs: dict[str, Any]) -> LLMResponse:
        """Execute a single API call (no retry logic)."""
        t0 = time.monotonic()

        response = self._client.chat.completions.create(**kwargs)

        elapsed = (time.monotonic() - t0) * 1000  # ms

        choice = response.choices[0]
        content = choice.message.content or ""

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        finish_reason = choice.finish_reason or "stop"

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=response.model,
            duration_ms=elapsed,
            finish_reason=finish_reason,
        )

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        return self._model
