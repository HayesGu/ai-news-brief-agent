from datetime import UTC, datetime
from pathlib import Path

from ai_research_agent.analysis.pipeline import AnalysisResult
from ai_research_agent.reporting.reports import create_report_markdown, save_markdown_report


def test_markdown_report_creation(tmp_path: Path) -> None:
    result = AnalysisResult(
        markdown="# Research Analysis\n\n## Executive Summary\n\nEnglish analysis.",
        source_file=Path("examples/sample_article.md"),
        model="deepseek-test",
        tags=["计算社会科学", "Computational Social Science", "Agent-based model", "AI治理"],
    )
    generated_at = datetime(2026, 7, 13, 10, 30, tzinfo=UTC)

    markdown = create_report_markdown(result, generated_at=generated_at)
    report_path = save_markdown_report(result, output_dir=tmp_path, generated_at=generated_at)

    assert 'date: "2026-07-13"' in markdown
    assert 'source: "examples/sample_article.md"' in markdown
    assert "research_fields:" in markdown
    assert '  - "计算社会科学"' in markdown
    assert '  - "Computational Social Science"' in markdown
    assert '  - "Agent-based model"' in markdown
    assert "related_methods:" in markdown
    assert '  - "Agent-based model"' in markdown
    assert "keywords:" in markdown
    assert 'relevance_score: ""' in markdown
    assert "# AI Research Analysis" in markdown
    assert "## Executive Summary" in markdown
    assert "English analysis." in report_path.read_text(encoding="utf-8")
    assert report_path.name == "2026-07-13_AI_Research_Analysis.md"
