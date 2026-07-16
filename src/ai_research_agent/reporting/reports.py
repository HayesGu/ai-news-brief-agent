"""Markdown report generation."""

from datetime import UTC, datetime
from pathlib import Path

from ai_research_agent.analysis.pipeline import AnalysisResult
from ai_research_agent.analysis.research import ResearchAnalysis

REPORTS_DIR = Path("output/reports")


def render_markdown_report(analysis: ResearchAnalysis) -> str:
    """Render a minimal Markdown report from a structured analysis object."""
    sections = [
        "# AI Research Analysis",
        f"## Research Question\n\n{analysis.research_question}",
        "## Methods\n\n" + "\n".join(f"- {item}" for item in analysis.methods),
        "## Findings\n\n" + "\n".join(f"- {item}" for item in analysis.findings),
        "## Limitations\n\n" + "\n".join(f"- {item}" for item in analysis.limitations),
        "## Open Questions\n\n" + "\n".join(f"- {item}" for item in analysis.open_questions),
    ]
    return "\n\n".join(sections)


def create_report_markdown(result: AnalysisResult, generated_at: datetime | None = None) -> str:
    """Create a UTF-8 Markdown report with Obsidian-friendly front matter."""
    timestamp = generated_at or datetime.now(UTC)
    keywords = _yaml_list(result.tags)
    methods = _yaml_list(_extract_related_methods(result.tags))
    body = _normalize_report_headings(result.markdown)
    return f"""\
---
date: "{timestamp.strftime("%Y-%m-%d")}"
source: "{result.source_file.as_posix()}"
research_fields:
{keywords}
related_methods:
{methods}
keywords:
{keywords}
relevance_score: ""
---

{body.strip()}
"""


def save_markdown_report(
    result: AnalysisResult,
    output_dir: Path = REPORTS_DIR,
    generated_at: datetime | None = None,
) -> Path:
    """Save an analysis report under output/reports."""
    timestamp = generated_at or datetime.now(UTC)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{timestamp.strftime('%Y-%m-%d')}_AI_Research_Analysis.md"
    report_path.write_text(
        create_report_markdown(result, generated_at=timestamp),
        encoding="utf-8",
    )
    return report_path


def _yaml_list(values: list[str]) -> str:
    if not values:
        return "  - Uncategorized"
    return "\n".join(f'  - "{value}"' for value in values)


def _extract_related_methods(keywords: list[str]) -> list[str]:
    method_terms = [
        "AI-based CSS methods",
        "LLM-based social simulation",
        "Agent-based model",
        "Agent-Based Model",
        "multi-agent systems",
        "social simulation",
        "network analysis",
        "NLP",
        "digital trace data",
        "human-AI interaction experiments",
        "platform behavior modeling",
        "reinforcement learning",
        "experiments",
        "causal inference",
        "DID",
        "IV",
    ]
    normalized_keywords = [keyword.lower() for keyword in keywords]
    methods = [
        term
        for term in method_terms
        if any(term.lower() in keyword for keyword in normalized_keywords)
    ]
    return list(dict.fromkeys(methods))


def _normalize_report_headings(markdown: str) -> str:
    """Convert legacy analysis headings into public English headings."""
    replacements = {
        "# Research Analysis": "# AI Research Analysis",
        "# AI研究日报": "# AI Research Analysis",
        "## Executive Summary": "## Executive Summary",
        "## Technical Contribution": "## Technical Contribution",
        "## Computational Social Science Relevance": (
            "## Computational Social Science Relevance"
        ),
        (
            "## Connections to Inequality, Institutions, Labor, Governance, "
            "or Human Behavior"
        ): "## Social Implications",
        "## Potential Research Questions": "## Potential Research Questions",
        "## Related Literature and Theories": "## Related Literature and Theories",
        "## Critical Assessment": "## Critical Assessment",
        "## Relevance Score": "## Relevance Score",
    }
    return "\n".join(replacements.get(line, line) for line in markdown.splitlines())
