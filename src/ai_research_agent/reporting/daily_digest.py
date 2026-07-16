"""Daily AI research briefing generation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ai_research_agent.analysis.output_quality import evaluate_report_quality
from ai_research_agent.core.config import load_prompt
from ai_research_agent.ingestion.models import CollectedArticle
from ai_research_agent.llm import LLMClient

DAILY_OUTPUT_DIR = Path("output/daily")


def save_daily_digest(
    client: LLMClient,
    target_date: date,
    profile: dict,
    collected_articles: Sequence[CollectedArticle],
    scored_articles: Sequence[Any],
    selected_articles: Any,
    enriched_articles: Sequence[Any],
    analyses: Sequence[Any],
    failures: Sequence[str],
    prompt_path: Path = Path("prompts/daily_digest.md"),
    output_dir: Path = DAILY_OUTPUT_DIR,
) -> Path:
    """Generate and save the final daily briefing."""
    prompt = build_daily_digest_prompt(
        base_prompt=load_prompt(prompt_path),
        target_date=target_date,
        profile=profile,
        collected_articles=collected_articles,
        scored_articles=scored_articles,
        selected_articles=selected_articles,
        enriched_articles=enriched_articles,
        analyses=analyses,
        failures=failures,
    )
    markdown = client.generate_markdown(prompt).strip()
    content = ensure_daily_front_matter(
        markdown=markdown,
        target_date=target_date,
        client=client,
        collected_count=len(collected_articles),
        selected_count=len(selected_articles.all_selected),
        report_quality=evaluate_report_quality(scored_articles, selected_articles).to_dict(),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{target_date.isoformat()}_AI_Research_Briefing.md"
    output_path.write_text(content, encoding="utf-8")
    return output_path


def build_daily_digest_prompt(
    base_prompt: str,
    target_date: date,
    profile: dict,
    collected_articles: Sequence[CollectedArticle],
    scored_articles: Sequence[Any],
    selected_articles: Any,
    enriched_articles: Sequence[Any],
    analyses: Sequence[Any],
    failures: Sequence[str],
) -> str:
    """Build the final digest prompt from structured intermediate results."""
    payload = {
        "date": target_date.isoformat(),
        "output_schema": {
            "schema_version": "0.1",
            "target": "obsidian_daily_research_briefing",
            "required_item_fields": [
                "research_question",
                "method",
                "findings",
                "significance",
                "connection_to_user_research_interests",
            ],
        },
        "generation_boundary": (
            "Only selected_detailed, selected_short, detailed_analyses, and failures may be "
            "used as substantive report content. collected_article_count is audit metadata only; "
            "do not introduce unselected collected articles into the daily briefing."
        ),
        "profile": profile,
        "collected_article_count": len(collected_articles),
        "scored_articles": [article.to_dict() for article in scored_articles],
        "selected_detailed": [article.to_dict() for article in selected_articles.detailed],
        "selected_short": [article.to_dict() for article in selected_articles.short],
        "report_quality_score": evaluate_report_quality(
            scored_articles,
            selected_articles,
        ).to_dict(),
        "enriched_articles": [article.to_dict() for article in enriched_articles],
        "detailed_analyses": [analysis.to_dict() for analysis in analyses],
        "failures": list(failures),
    }
    return f"""\
{base_prompt.strip()}

Generate the final daily research briefing from the structured intermediate results below.
Do not add facts that are not present in the sources.
Only selected_detailed, selected_short, detailed_analyses, and failures may be used as substantive report content.
collected_article_count is audit metadata only and must not be used to introduce unselected articles into the briefing.

```json
{json.dumps(payload, ensure_ascii=False, indent=2)}
```
"""


def ensure_daily_front_matter(
    markdown: str,
    target_date: date,
    client: LLMClient,
    collected_count: int,
    selected_count: int,
    report_quality: dict[str, object] | None = None,
) -> str:
    """Ensure required YAML front matter exists for Obsidian."""
    body = _strip_daily_title_heading(_strip_front_matter(markdown))
    generated_at = datetime.now(UTC).isoformat()
    title = f"AI Research Briefing: {target_date.isoformat()}"
    quality = report_quality or {}
    quality_overall = int(quality.get("overall", 0))
    quality_depth = int(quality.get("research_depth", 0))
    quality_method = int(quality.get("methodological_clarity", 0))
    quality_relevance = int(quality.get("relevance_to_user_profile", 0))
    return f"""\
---
title: "{title}"
date: "{target_date.isoformat()}"
generated_at: "{generated_at}"
schema_version: "0.1"
document_type: "ai_research_daily_briefing"
llm_provider: "configured"
model: "{client.model_name}"
sources:
  - Anthropic
  - OpenAI
  - Google DeepMind
  - Microsoft Research
  - Meta AI Research
  - IBM Research AI
article_count_collected: {collected_count}
article_count_selected: {selected_count}
quality_score:
  overall: {quality_overall}
  research_depth: {quality_depth}
  methodological_clarity: {quality_method}
  relevance_to_user_profile: {quality_relevance}
tags:
  - AI Research Briefing
  - Computational Social Science
  - Social Simulation
---

{body.strip()}
"""


def _strip_front_matter(markdown: str) -> str:
    text = markdown.strip()
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) == 3:
        return parts[2].strip()
    return text


def _strip_daily_title_heading(markdown: str) -> str:
    """Remove the top daily H1 so the title and Markdown H1 do not duplicate."""
    lines = markdown.strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and _is_daily_title_heading(lines[0]):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).strip()


def _is_daily_title_heading(line: str) -> bool:
    normalized = line.strip()
    return normalized.startswith("# ") and (
        "AI Research Briefing" in normalized or "AI研究日报" in normalized
    )
