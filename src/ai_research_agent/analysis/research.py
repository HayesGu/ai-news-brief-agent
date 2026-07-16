"""Analysis model placeholders for computational social science material."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ResearchAnalysis:
    """Structured summary of a future research analysis result."""

    research_question: str
    methods: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
