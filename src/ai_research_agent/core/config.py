"""Configuration and prompt loading utilities."""

from pathlib import Path
from typing import Any

import yaml

from ai_research_agent.core.errors import ConfigurationError


def load_research_profile(path: Path) -> dict[str, Any]:
    """Load and validate the computational social science profile YAML."""
    if not path.exists():
        raise ConfigurationError(f"Research profile not found: {path}")
    if not path.is_file():
        raise ConfigurationError(f"Research profile path is not a file: {path}")

    try:
        with path.open("r", encoding="utf-8") as profile_file:
            profile = yaml.safe_load(profile_file)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in research profile {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigurationError(f"Could not read research profile {path}: {exc}") from exc

    if not isinstance(profile, dict):
        raise ConfigurationError(f"Research profile must be a YAML mapping: {path}")
    return profile


def load_prompt(path: Path) -> str:
    """Load analysis instructions from a Markdown prompt file."""
    if not path.exists():
        raise ConfigurationError(f"Analysis prompt not found: {path}")
    if not path.is_file():
        raise ConfigurationError(f"Analysis prompt path is not a file: {path}")

    try:
        prompt = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"Could not read analysis prompt {path}: {exc}") from exc

    if not prompt.strip():
        raise ConfigurationError(f"Analysis prompt is empty: {path}")
    return prompt
