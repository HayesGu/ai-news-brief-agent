"""Application-specific exceptions with user-facing messages."""


class ResearchAgentError(Exception):
    """Base error for expected application failures."""


class ConfigurationError(ResearchAgentError):
    """Raised when configuration files or environment values are invalid."""


class InputFileError(ResearchAgentError):
    """Raised when an article input file cannot be analyzed."""


class LLMClientError(ResearchAgentError):
    """Raised when LLM analysis fails after handled retries."""
