"""Quality checks for research-intelligence outputs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ai_research_agent.analysis.relevance import ResearchRelevanceScore

GENERIC_METHOD_MARKERS = {
    "",
    "n/a",
    "na",
    "none",
    "unknown",
    "unclear",
    "not specified",
    "not provided",
    "general analysis",
    "ai analysis",
    "research",
    "analysis",
    "原文未提供明确方法",
    "原文未提供相关信息",
    "未提供",
    "不明确",
    "无",
}


@dataclass(frozen=True)
class OutputQualityCheck:
    """Validation result for one article-level research-intelligence output."""

    passed: bool
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "issues": self.issues}


@dataclass(frozen=True)
class ReportQualityScore:
    """Aggregate quality score for a daily research briefing."""

    research_depth: int
    methodological_clarity: int
    relevance_to_user_profile: int
    overall: int
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "research_depth": self.research_depth,
            "methodological_clarity": self.methodological_clarity,
            "relevance_to_user_profile": self.relevance_to_user_profile,
            "overall": self.overall,
            "issues": self.issues,
        }


def validate_relevance_output(relevance: ResearchRelevanceScore) -> OutputQualityCheck:
    """Validate required research-intelligence fields before report generation."""
    issues: list[str] = []
    if not relevance.research_question.strip():
        issues.append("research_question_empty")
    if _is_generic_method(relevance.method):
        issues.append("method_generic_or_empty")
    if relevance.score >= 7 and not relevance.main_result.strip():
        issues.append("main_result_missing_for_high_score_article")
    if not relevance.why_relevant_to_user.strip():
        issues.append("why_relevant_to_user_empty")
    return OutputQualityCheck(passed=not issues, issues=issues)


def evaluate_report_quality(
    scored_articles: Sequence[Any],
    selected_articles: Any,
) -> ReportQualityScore:
    """Score the structured daily-briefing input before the final LLM report."""
    selected = list(getattr(selected_articles, "all_selected", []) or [])
    candidates = selected or list(scored_articles)
    if not candidates:
        return ReportQualityScore(
            research_depth=0,
            methodological_clarity=0,
            relevance_to_user_profile=0,
            overall=0,
            issues=["no_scored_articles"],
        )

    checks = [validate_relevance_output(item.relevance) for item in candidates]
    issues = [
        f"{getattr(item.article, 'title', 'untitled')}: {issue}"
        for item, check in zip(candidates, checks, strict=True)
        for issue in check.issues
    ]
    research_depth = _average(
        _article_research_depth(item.relevance) for item in candidates
    )
    methodological_clarity = _average(
        _article_methodological_clarity(item.relevance) for item in candidates
    )
    relevance_to_user_profile = _average(
        _article_user_relevance(item.relevance) for item in candidates
    )
    penalty = min(3, len(issues))
    overall = _clamp_score(
        round((research_depth + methodological_clarity + relevance_to_user_profile) / 3)
        - penalty
    )
    return ReportQualityScore(
        research_depth=research_depth,
        methodological_clarity=methodological_clarity,
        relevance_to_user_profile=relevance_to_user_profile,
        overall=overall,
        issues=issues,
    )


def _article_research_depth(relevance: ResearchRelevanceScore) -> int:
    value_score = relevance.research_value_score
    text_bonus = sum(
        1
        for value in (
            relevance.research_question,
            relevance.main_result,
            relevance.research_value,
        )
        if len(value.strip()) >= 20
    )
    return _clamp_score(
        round((value_score.novelty + value_score.proposal_potential + relevance.score) / 3)
        + text_bonus
        - 1
    )


def _article_methodological_clarity(relevance: ResearchRelevanceScore) -> int:
    if _is_generic_method(relevance.method):
        return 2
    score = relevance.research_value_score.methodological_contribution
    method = relevance.method.lower()
    if any(
        term in method
        for term in (
            "agent-based",
            "abm",
            "llm-based",
            "multi-agent",
            "social simulation",
            "network",
            "nlp",
            "digital trace",
            "human-ai interaction",
            "platform behavior",
        )
    ):
        score += 1
    if any(
        term in relevance.method
        for term in (
            "社会模拟",
            "主体建模",
            "多智能体",
            "网络",
            "数字痕迹",
            "文本分析",
            "人机交互",
            "平台行为",
        )
    ):
        score += 1
    return _clamp_score(score)


def _article_user_relevance(relevance: ResearchRelevanceScore) -> int:
    score = round((relevance.score + relevance.research_value_score.css_relevance) / 2)
    if relevance.why_relevant_to_user.strip():
        score += 1
    return _clamp_score(score)


def _is_generic_method(method: str) -> bool:
    normalized = " ".join(method.strip().lower().split())
    if normalized in GENERIC_METHOD_MARKERS:
        return True
    if len(normalized) < 8:
        return True
    weak_markers = (
        "not specified",
        "not provided",
        "原文未提供",
        "未提供",
        "不明确",
    )
    return any(marker in normalized for marker in weak_markers)


def _average(values: Sequence[int] | Any) -> int:
    numbers = list(values)
    if not numbers:
        return 0
    return _clamp_score(round(sum(numbers) / len(numbers)))


def _clamp_score(value: int) -> int:
    return max(0, min(10, int(value)))
