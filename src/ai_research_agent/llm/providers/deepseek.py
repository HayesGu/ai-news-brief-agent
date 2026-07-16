"""DeepSeek provider using the OpenAI-compatible chat completions API."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from ai_research_agent.core.errors import LLMClientError


@dataclass
class DeepSeekClient:
    """OpenAI-compatible DeepSeek client."""

    api_key: str
    base_url: str
    model_name: str
    timeout_seconds: float = 60.0
    max_retries: int = 2
    initial_backoff_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise LLMClientError("LLM_API_KEY is not set. Add it to your local .env file.")
        if not self.base_url.strip():
            raise LLMClientError("LLM_BASE_URL is not set. Add it to your local .env file.")
        if not self.model_name.strip():
            raise LLMClientError("LLM_MODEL is not set. Add it to your local .env file.")

    def generate_markdown(self, prompt: str) -> str:
        """Generate Markdown through DeepSeek's OpenAI-compatible endpoint."""
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a careful computational social science research analyst.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        return self._post_with_retries(payload=payload, headers=headers)

    def _post_with_retries(self, payload: dict[str, Any], headers: dict[str, str]) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        self._chat_completions_url(),
                        headers=headers,
                        json=payload,
                    )
                if response.status_code in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                if response.status_code >= 400:
                    raise LLMClientError(self._format_http_error(response))
                return self._extract_text(response.json())
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.initial_backoff_seconds * (2**attempt))
            except (ValueError, LLMClientError) as exc:
                last_error = exc
                break

        message = f"LLM analysis failed after retries: {last_error}"
        raise LLMClientError(message) from last_error

    def _chat_completions_url(self) -> str:
        base_url = self.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _extract_text(self, response_json: dict[str, Any]) -> str:
        try:
            content = response_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("LLM response did not include message content.") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("LLM returned an empty analysis.")
        return content.strip()

    def _format_http_error(self, response: httpx.Response) -> str:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        return f"LLM request failed with HTTP {response.status_code}: {detail}"
