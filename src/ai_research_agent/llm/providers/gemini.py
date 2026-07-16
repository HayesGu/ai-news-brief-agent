"""Optional Gemini provider behind the generic LLM interface."""

from __future__ import annotations

import time
from dataclasses import dataclass

from ai_research_agent.core.errors import LLMClientError


@dataclass
class GeminiClient:
    """Google Gen AI SDK implementation of the generic LLM interface."""

    api_key: str
    model_name: str
    timeout_seconds: float = 60.0
    max_retries: int = 2
    initial_backoff_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise LLMClientError("LLM_API_KEY is not set. Add it to your local .env file.")
        if not self.model_name.strip():
            raise LLMClientError("LLM_MODEL is not set. Add it to your local .env file.")

    def generate_markdown(self, prompt: str) -> str:
        """Generate Markdown with Gemini if the optional SDK is installed."""
        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as exc:
            raise LLMClientError(
                "Gemini provider requires the optional google-genai package."
            ) from exc

        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                client_args={"timeout": self.timeout_seconds},
            ),
        )
        try:
            return self._generate_with_retries(client, prompt, errors.APIError)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _generate_with_retries(
        self,
        client: object,
        prompt: str,
        api_error: type[Exception],
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config={"temperature": 0.2},
                )
                text = getattr(response, "text", None)
                if not isinstance(text, str) or not text.strip():
                    raise LLMClientError("LLM returned an empty analysis.")
                return text.strip()
            except (TimeoutError, api_error, OSError, LLMClientError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.initial_backoff_seconds * (2**attempt))

        message = f"LLM analysis failed after retries: {last_error}"
        raise LLMClientError(message) from last_error
