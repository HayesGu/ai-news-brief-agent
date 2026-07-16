from pathlib import Path

import pytest

from ai_research_agent.core.config import load_prompt, load_research_profile
from ai_research_agent.core.errors import ConfigurationError


def test_profile_loading(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "topics:\n  primary:\n    - computational social science\n",
        encoding="utf-8",
    )

    profile = load_research_profile(profile_path)

    assert profile["topics"]["primary"] == ["computational social science"]


def test_profile_loading_rejects_invalid_yaml(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("topics: [broken\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Invalid YAML"):
        load_research_profile(profile_path)


def test_prompt_loading(tmp_path: Path) -> None:
    prompt_path = tmp_path / "research_analysis.md"
    prompt_path.write_text("# Prompt\n\nAnalyze carefully.", encoding="utf-8")

    prompt = load_prompt(prompt_path)

    assert "Analyze carefully." in prompt


def test_prompt_loading_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Analysis prompt not found"):
        load_prompt(tmp_path / "missing.md")
