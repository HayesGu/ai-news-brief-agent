from dataclasses import dataclass
from pathlib import Path

from ai_research_agent.analysis.pipeline import analyze_article


@dataclass
class MockLLMClient:
    model_name: str = "test-llm-model"

    def generate_markdown(self, prompt: str) -> str:
        assert "Research profile YAML" in prompt
        assert "Article text" in prompt
        assert "Do not invent citations" in prompt
        return "# Research Analysis\n\n## Executive Summary\n\nMocked result."


def test_successful_mocked_analysis(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    prompt_path = tmp_path / "research_analysis.md"
    article_path = tmp_path / "sample_article.md"

    profile_path.write_text(
        "topics:\n  primary:\n    - computational social science\n    - labor markets\n",
        encoding="utf-8",
    )
    prompt_path.write_text("# Prompt\n\nAnalyze this article.", encoding="utf-8")
    article_path.write_text("# Article\n\nAI and labor institutions.", encoding="utf-8")

    result = analyze_article(
        article_path=article_path,
        client=MockLLMClient(),
        profile_path=profile_path,
        prompt_path=prompt_path,
    )

    assert result.model == "test-llm-model"
    assert result.source_file == article_path
    assert result.tags == ["computational social science", "labor markets"]
    assert "Mocked result" in result.markdown
