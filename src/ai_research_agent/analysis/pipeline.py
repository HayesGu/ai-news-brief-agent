"""Research analysis pipeline orchestration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from ai_research_agent.core.config import load_prompt, load_research_profile
from ai_research_agent.ingestion.articles import load_article_text


class AnalysisClient(Protocol):
    """Minimal protocol implemented by LLM and test clients."""

    model_name: str

    def generate_markdown(self, prompt: str) -> str:
        """Generate Markdown analysis for the assembled prompt."""


@dataclass(frozen=True)
class AnalysisResult:
    """Generated analysis and source metadata."""

    markdown: str
    source_file: Path
    model: str
    tags: list[str]


REQUIRED_REPORT_SECTIONS = [
    "# Research Analysis",
    "## Executive Summary",
    "## Technical Contribution",
    "## Computational Social Science Relevance",
    "## Connections to Inequality, Institutions, Labor, Governance, or Human Behavior",
    "## Potential Research Questions",
    "## Related Literature and Theories",
    "## Critical Assessment",
    "## Relevance Score",
]


def build_analysis_prompt(research_prompt: str, profile: dict, article_text: str) -> str:
    """Combine reusable instructions, YAML profile, and article text for the LLM."""
    profile_yaml = yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)
    required_sections = "\n".join(REQUIRED_REPORT_SECTIONS)
    return f"""\
{research_prompt.strip()}

Additional output requirements:

- Return structured Markdown using exactly these top-level sections:

{required_sections}

- Do not invent citations, papers, authors, datasets, or publication venues.
- If you are uncertain about a paper, theory, dataset, method, or citation, label it as
  "requires verification".
- Keep the analysis grounded in the supplied article text and the research profile.

Research profile YAML:

```yaml
{profile_yaml.strip()}
```

Article text:

```markdown
{article_text.strip()}
```
"""


def extract_tags(profile: dict) -> list[str]:
    """Extract report keywords while preserving Chinese and English terms."""
    tags: list[str] = []

    topics = profile.get("topics")
    if isinstance(topics, dict):
        primary = topics.get("primary")
        if isinstance(primary, list):
            tags.extend(_clean_keyword(topic) for topic in primary)

    research_keywords = profile.get("research_keywords")
    if isinstance(research_keywords, dict):
        for priority in ("high_priority", "medium_priority", "low_priority"):
            values = research_keywords.get(priority)
            if isinstance(values, list):
                tags.extend(_clean_keyword(value) for value in values)

    deduplicated = list(dict.fromkeys(tag for tag in tags if tag))
    return deduplicated or ["计算社会科学", "Computational Social Science"]


def _clean_keyword(value: object) -> str:
    return str(value).strip()


def analyze_article(
    article_path: Path,
    client: AnalysisClient,
    profile_path: Path = Path("config/profile.yaml"),
    prompt_path: Path = Path("prompts/research_analysis.md"),
) -> AnalysisResult:
    """Run the minimum working local-file research analysis pipeline."""
    profile = load_research_profile(profile_path)
    research_prompt = load_prompt(prompt_path)
    article_text = load_article_text(article_path)
    llm_prompt = build_analysis_prompt(research_prompt, profile, article_text)
    markdown = client.generate_markdown(llm_prompt)
    return AnalysisResult(
        markdown=markdown,
        source_file=article_path,
        model=client.model_name,
        tags=extract_tags(profile),
    )
