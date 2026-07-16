from datetime import date

from ai_research_agent.analysis.output_quality import (
    evaluate_report_quality,
    validate_relevance_output,
)
from ai_research_agent.analysis.relevance import ResearchRelevanceScore, ResearchValueScore
from ai_research_agent.ingestion.models import CollectedArticle
from ai_research_agent.pipeline.daily import ScoredArticle, SelectedArticles
from ai_research_agent.reporting.daily_digest import (
    build_daily_digest_prompt,
    ensure_daily_front_matter,
)


class FakeClient:
    model_name = "fake-model"


def test_relevance_quality_requires_research_question() -> None:
    check = validate_relevance_output(_relevance(research_question=""))

    assert check.passed is False
    assert "research_question_empty" in check.issues


def test_relevance_quality_rejects_generic_method() -> None:
    check = validate_relevance_output(_relevance(method="原文未提供明确方法"))

    assert check.passed is False
    assert "method_generic_or_empty" in check.issues


def test_high_score_article_requires_main_result() -> None:
    check = validate_relevance_output(_relevance(score=9, main_result=""))

    assert check.passed is False
    assert "main_result_missing_for_high_score_article" in check.issues


def test_report_quality_scores_depth_method_and_user_relevance() -> None:
    scored = _scored(_relevance(score=9))
    selected = SelectedArticles(detailed=[scored], short=[], excluded=[])

    quality = evaluate_report_quality([scored], selected)

    assert quality.research_depth >= 8
    assert quality.methodological_clarity >= 8
    assert quality.relevance_to_user_profile >= 8
    assert quality.overall >= 8


def test_daily_digest_prompt_contains_obsidian_schema_and_research_fields() -> None:
    scored = _scored(_relevance(score=8))
    selected = SelectedArticles(detailed=[scored], short=[], excluded=[])
    unselected = CollectedArticle(
        title="Unselected historical model update",
        source="OpenAI",
        url="https://openai.com/research/unselected",
        published_date="2026-07-13",
        summary="This should not be available to the final digest prompt.",
        category="AI Research",
    )

    prompt = build_daily_digest_prompt(
        base_prompt="生成日报",
        target_date=date(2026, 7, 14),
        profile={},
        collected_articles=[scored.article, unselected],
        scored_articles=[scored],
        selected_articles=selected,
        enriched_articles=[],
        analyses=[],
        failures=[],
    )

    assert "obsidian_daily_research_briefing" in prompt
    assert "research_question" in prompt
    assert "connection_to_user_research_interests" in prompt
    assert "report_quality_score" in prompt
    assert "collected_article_count" in prompt
    assert "Unselected historical model update" not in prompt


def test_daily_front_matter_contains_quality_score_schema() -> None:
    content = ensure_daily_front_matter(
        markdown="## 1. AI Industry News Brief\n\n- Test",
        target_date=date(2026, 7, 14),
        client=FakeClient(),
        collected_count=3,
        selected_count=1,
        report_quality={
            "overall": 8,
            "research_depth": 9,
            "methodological_clarity": 8,
            "relevance_to_user_profile": 9,
        },
    )

    assert 'schema_version: "0.1"' in content
    assert 'document_type: "ai_research_daily_briefing"' in content
    assert "quality_score:" in content
    assert "overall: 8" in content


def _scored(relevance: ResearchRelevanceScore) -> ScoredArticle:
    return ScoredArticle(
        article=CollectedArticle(
            title="AI governance and organizations",
            source="Anthropic",
            url="https://www.anthropic.com/research/governance",
            published_date="2026-07-14",
            summary="A research update about AI governance in organizations.",
            category="AI研究机构",
        ),
        relevance=relevance,
    )


def _relevance(
    *,
    score: int = 8,
    research_question: str = "How does AI governance change organizational accountability?",
    method: str = (
        "Agent-based modeling with digital trace data, network analysis, and "
        "human-AI interaction experiments."
    ),
    main_result: str = (
        "Governance mechanisms may change disclosure, evaluation, and accountability."
    ),
) -> ResearchRelevanceScore:
    return ResearchRelevanceScore(
        score=score,
        categories=["AI治理"],
        research_value="This can support a computational social science research proposal.",
        decision="full_research_analysis" if score >= 7 else "short_analysis",
        research_question=research_question,
        method=method,
        main_result=main_result,
        why_relevant_to_user=(
            "It matches the user's AI-based CSS, social simulation, and governance interests."
        ),
        research_value_score=ResearchValueScore(
            novelty=8,
            methodological_contribution=8,
            css_relevance=9,
            proposal_potential=9,
        ),
        reason="Strong CSS relevance.",
    )
