"""Provider-agnostic LLM client factory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from ai_research_agent.core.errors import ConfigurationError


class LLMClient(Protocol):
    """Minimal interface required by the research analysis pipeline."""

    model_name: str

    def generate_markdown(self, prompt: str) -> str:
        """Generate Markdown analysis for the assembled prompt."""


@dataclass(frozen=True)
class LLMConfig:
    """Environment-backed LLM provider configuration."""

    provider: str
    api_key: str
    base_url: str
    model_name: str
    timeout_seconds: float = 60.0
    max_retries: int = 2
    initial_backoff_seconds: float = 1.0


def load_llm_config_from_env() -> LLMConfig:
    """Load generic LLM configuration from environment variables."""
    provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    model_name = os.getenv("LLM_MODEL", "").strip()

    if not api_key:
        raise ConfigurationError("LLM_API_KEY is not set. Add it to your local .env file.")
    if not model_name:
        raise ConfigurationError("LLM_MODEL is not set. Add it to your local .env file.")
    if provider == "deepseek" and not base_url:
        raise ConfigurationError("LLM_BASE_URL is not set. Add it to your local .env file.")

    return LLMConfig(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
    )


def create_llm_client(config: LLMConfig) -> LLMClient:
    """Create a provider-specific LLM client from generic configuration."""
    if config.provider == "deepseek":
        from ai_research_agent.llm.providers.deepseek import DeepSeekClient

        return DeepSeekClient(
            api_key=config.api_key,
            base_url=config.base_url,
            model_name=config.model_name,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            initial_backoff_seconds=config.initial_backoff_seconds,
        )
    if config.provider == "gemini":
        from ai_research_agent.llm.providers.gemini import GeminiClient

        return GeminiClient(
            api_key=config.api_key,
            model_name=config.model_name,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            initial_backoff_seconds=config.initial_backoff_seconds,
        )

    raise ConfigurationError(
        f"Unsupported LLM_PROVIDER '{config.provider}'. Use 'deepseek' or 'gemini'."
    )
