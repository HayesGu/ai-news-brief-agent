from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
import requests

from ai_research_agent.analysis.pipeline import AnalysisResult
from ai_research_agent.analysis.relevance import ResearchRelevanceScore
from ai_research_agent.ingestion.collector import save_raw_articles
from ai_research_agent.ingestion.models import CollectedArticle
from ai_research_agent.pipeline.daily import (
    DailyPipeline,
    EnrichedArticle,
    ScoredArticle,
    enrich_selected_article,
    select_articles,
)
from ai_research_agent.reporting.daily_digest import save_daily_digest
from ai_research_agent.storage.article_registry import ArticleRegistry


@dataclass
class FakeClient:
    response: str = (
        "# AI Research Three-Day Briefing: 2026-07-14\n\n"
        "## 1. AI Industry News Brief\n\n"
        "- English briefing generated."
    )
    model_name: str = "fake-model"

    def generate_markdown(self, prompt: str) -> str:
        assert "AI Research Three-Day Briefing" in prompt or "structured intermediate results" in prompt
        return self.response


def test_successful_complete_daily_workflow(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)

    result = pipeline.run(target_date=date(2026, 7, 14))

    assert result.report_path is not None
    assert result.report_path.exists()
    assert len(result.collected_articles) == 3
    assert len(result.selected_articles.detailed) == 2
    assert len(result.analyses) == 2
    assert result.scored_path.name == "2026-07-14.json"


def test_one_source_failure_still_generates_report(tmp_path: Path) -> None:
    articles = [_article("OpenAI", "AI agents in organizations", "https://openai.com/research/a")]
    pipeline = _pipeline(tmp_path, articles=articles)

    result = pipeline.run(target_date=date(2026, 7, 14))

    assert result.report_path is not None
    assert result.report_path.exists()
    assert len(result.collected_articles) == 1


def test_no_high_relevance_articles_still_generates_digest(tmp_path: Path) -> None:
    articles = [_article("OpenAI", "Foundation model update", "https://openai.com/research/f")]
    pipeline = _pipeline(tmp_path, articles=articles, score=5)

    result = pipeline.run(target_date=date(2026, 7, 14))

    assert result.report_path is not None
    assert result.selected_articles.detailed == []
    assert len(result.selected_articles.short) == 1
    assert result.analyses == []


def test_duplicate_article_selection() -> None:
    first = _scored(_article("Anthropic", "New AI safety system", "https://www.anthropic.com/a"), 9)
    duplicate = _scored(
        _article("Anthropic", "New AI safety systems", "https://www.anthropic.com/a?ref=x"),
        8,
    )

    selected = select_articles(
        [first, duplicate],
        _config(max_detailed_articles=5, max_short_articles=5),
    )

    assert len(selected.detailed) == 1


def test_selection_allows_broader_research_and_limited_general_news() -> None:
    detailed = _scored(_article("Anthropic", "AI methods", "https://www.anthropic.com/ai"), 6)
    short_one = _scored(_article("OpenAI", "General model update", "https://openai.com/g1"), 3)
    short_two = _scored(
        _article("Google DeepMind", "General agent update", "https://deepmind.google/g2"),
        4,
    )
    short_extra = _scored(_article("OpenAI", "Extra model update", "https://openai.com/g3"), 5)

    selected = select_articles(
        [detailed, short_one, short_two, short_extra],
        _config(max_detailed_articles=5, max_short_articles=2),
    )

    assert [item.relevance.score for item in selected.detailed] == [6]
    assert len(selected.short) == 2
    assert len(selected.excluded) == 1


def test_article_enrichment_failure_uses_summary_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scored = _scored(
        _article("Anthropic", "AI safety", "https://www.anthropic.com/research/safety"),
        9,
    )

    def fail_get(*args: object, **kwargs: object) -> object:
        raise requests.Timeout("timeout")

    monkeypatch.setattr(requests, "get", fail_get)
    enriched = enrich_selected_article(
        scored,
        target_date=date(2026, 7, 14),
        output_dir=tmp_path,
        max_text_chars=2000,
    )

    assert enriched.used_fallback is True
    assert "Summary for AI safety" in enriched.path.read_text(encoding="utf-8")


def test_configured_article_limits(tmp_path: Path) -> None:
    articles = [
        _article("Anthropic", "AI safety one", "https://www.anthropic.com/1"),
        _article("OpenAI", "AI safety two", "https://openai.com/research/2"),
        _article("Google DeepMind", "AI safety three", "https://deepmind.google/3"),
    ]
    pipeline = _pipeline(tmp_path, articles=articles)

    result = pipeline.run(target_date=date(2026, 7, 14), max_detailed=1)

    assert len(result.selected_articles.detailed) == 1


def test_english_markdown_output(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)

    result = pipeline.run(target_date=date(2026, 7, 14))

    text = result.report_path.read_text(encoding="utf-8") if result.report_path else ""
    assert 'title: "AI Research Three-Day Briefing: 2026-07-14"' in text
    assert "# AI Research Three-Day Briefing: 2026-07-14" not in text
    assert text.count("## 1. AI Industry News Brief") == 1
    assert "English briefing generated" in text


def test_dry_run_behavior(tmp_path: Path) -> None:
    calls = {"analysis": 0, "digest": 0}
    pipeline = _pipeline(tmp_path, call_counter=calls)

    result = pipeline.run(target_date=date(2026, 7, 14), dry_run=True)

    assert result.report_path is None
    assert result.dry_run is True
    assert calls["analysis"] == 0
    assert calls["digest"] == 0
    assert result.scored_path.exists()


def test_partial_llm_failure_continues(tmp_path: Path) -> None:
    calls = {"analysis": 0}

    def analysis_func(
        article_path: Path,
        client: FakeClient,
        profile_path: Path,
        prompt_path: Path,
    ) -> AnalysisResult:
        calls["analysis"] += 1
        if calls["analysis"] == 1:
            raise RuntimeError("analysis failed")
        return AnalysisResult(
            markdown="# Analysis",
            source_file=article_path,
            model=client.model_name,
            tags=["AI治理"],
        )

    pipeline = _pipeline(tmp_path, analysis_func=analysis_func)
    result = pipeline.run(target_date=date(2026, 7, 14))

    assert result.report_path is not None
    assert any("文章深度分析失败" in failure for failure in result.failures)
    assert len(result.analyses) == 2


def test_final_output_path_and_yaml_front_matter(tmp_path: Path) -> None:
    article = _article("Anthropic", "AI safety", "https://www.anthropic.com/research/safety")
    scored = _scored(article, 9)
    selected = type(
        "Selected",
        (),
        {"detailed": [scored], "short": [], "all_selected": [scored]},
    )()

    path = save_daily_digest(
        client=FakeClient(),
        target_date=date(2026, 7, 14),
        profile={},
        collected_articles=[article],
        scored_articles=[scored],
        selected_articles=selected,
        enriched_articles=[],
        analyses=[],
        failures=[],
        prompt_path=_digest_prompt(tmp_path),
        output_dir=tmp_path,
    )

    text = path.read_text(encoding="utf-8")
    assert path.name == "2026-07-14_AI_Research_Three_Day_Briefing.md"
    assert text.startswith("---")
    assert 'title: "AI Research Three-Day Briefing: 2026-07-14"' in text
    assert 'date: "2026-07-14"' in text
    assert "article_count_collected: 1" in text
    assert "article_count_selected: 1" in text


def _pipeline(
    tmp_path: Path,
    articles: list[CollectedArticle] | None = None,
    score: int = 9,
    call_counter: dict[str, int] | None = None,
    analysis_func: object | None = None,
) -> DailyPipeline:
    articles = articles or [
        _article("Anthropic", "AI safety research", "https://www.anthropic.com/research/safety"),
        _article("OpenAI", "AI agents in organizations", "https://openai.com/research/agents"),
        _article("Google DeepMind", "GPU benchmark", "https://deepmind.google/benchmark"),
    ]

    def collect_func(target_date: date, output_dir: Path) -> list[CollectedArticle]:
        save_raw_articles(articles, output_dir=output_dir, today=target_date)
        return articles

    def relevance_func(
        article: CollectedArticle,
        client: FakeClient,
        profile_path: Path,
    ) -> ResearchRelevanceScore:
        article_score = 2 if "GPU" in article.title else score
        if score == 5:
            article_score = 5
        return ResearchRelevanceScore(
            score=article_score,
            categories=["AI治理"],
            reason="中文原因",
            research_value="中文研究价值",
            decision="full_research_analysis" if article_score >= 7 else "short_analysis",
            research_question="How do AI systems affect organizations and governance?",
            method="Causal inference with digital trace data and organizational records.",
            main_result="The article suggests AI systems may reshape coordination and governance.",
            why_relevant_to_user="It connects to computational social science and AI governance.",
        )

    def enricher(
        scored_article: ScoredArticle,
        target_date: date,
        output_dir: Path,
        max_text_chars: int,
    ) -> EnrichedArticle:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{scored_article.article.source}.md"
        path.write_text(scored_article.article.summary[:max_text_chars], encoding="utf-8")
        return EnrichedArticle(scored_article, scored_article.article.summary, path, False)

    def default_analysis_func(
        article_path: Path,
        client: FakeClient,
        profile_path: Path,
        prompt_path: Path,
    ) -> AnalysisResult:
        if call_counter is not None:
            call_counter["analysis"] += 1
        return AnalysisResult(
            markdown="# Analysis",
            source_file=article_path,
            model=client.model_name,
            tags=["AI治理"],
        )

    def digest_func(**kwargs: object) -> Path:
        if call_counter is not None:
            call_counter["digest"] += 1
        return save_daily_digest(**kwargs)

    return DailyPipeline(
        client=FakeClient(),
        profile_path=_profile(tmp_path),
        analysis_prompt_path=_analysis_prompt(tmp_path),
        digest_prompt_path=_digest_prompt(tmp_path),
        raw_dir=tmp_path / "raw",
        scored_dir=tmp_path / "scored",
        enriched_root_dir=tmp_path / "enriched",
        output_dir=tmp_path / "daily",
        quarantine_dir=tmp_path / "quarantine",
        state_path=tmp_path / "state" / "pipeline_state.json",
        runs_dir=tmp_path / "runs",
        registry=ArticleRegistry(tmp_path / "state" / "registry.sqlite3"),
        collect_func=collect_func,
        relevance_func=relevance_func,
        analysis_func=analysis_func or default_analysis_func,
        digest_func=digest_func,
        enricher=enricher,
    )


def _article(source: str, title: str, url: str) -> CollectedArticle:
    return CollectedArticle(
        title=title,
        source=source,
        url=url,
        published_date="2026-07-14",
        summary=f"Summary for {title}",
        category="AI研究机构",
    )


def _scored(article: CollectedArticle, score: int) -> ScoredArticle:
    return ScoredArticle(
        article=article,
        relevance=ResearchRelevanceScore(
            score=score,
            categories=["AI治理"],
            reason="中文原因",
            research_value="中文研究价值",
            decision="full_research_analysis" if score >= 7 else "short_analysis",
            research_question="How do AI systems affect organizations and governance?",
            method="Causal inference with digital trace data and organizational records.",
            main_result="The article suggests AI systems may reshape coordination and governance.",
            why_relevant_to_user="It connects to computational social science and AI governance.",
        ),
    )


def _config(max_detailed_articles: int, max_short_articles: int) -> object:
    from ai_research_agent.pipeline.daily import DailyDigestConfig

    return DailyDigestConfig(
        max_detailed_articles=max_detailed_articles,
        max_short_articles=max_short_articles,
    )


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(
        """
daily_digest:
  max_detailed_articles: 5
  max_short_articles: 5
  minimum_detailed_score: 7
  minimum_short_score: 4
  max_enriched_text_chars: 12000
  max_articles_to_score: 20
freshness:
  normal_lookback_hours: 240
research_keywords:
  high_priority:
    - AI治理
""",
        encoding="utf-8",
    )
    return path


def _analysis_prompt(tmp_path: Path) -> Path:
    path = tmp_path / "analysis.md"
    path.write_text("分析提示", encoding="utf-8")
    return path


def _digest_prompt(tmp_path: Path) -> Path:
    path = tmp_path / "daily_digest.md"
    path.write_text(
        "# AI Research Three-Day Briefing\n\nGenerate an English three-day briefing.",
        encoding="utf-8",
    )
    return path
