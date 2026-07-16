"""End-to-end daily AI research briefing pipeline."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from ai_research_agent.analysis.output_quality import validate_relevance_output
from ai_research_agent.analysis.pipeline import analyze_article
from ai_research_agent.analysis.relevance import (
    ResearchRelevanceScore,
    evaluate_article_relevance,
)
from ai_research_agent.core.config import load_research_profile
from ai_research_agent.core.errors import ResearchAgentError
from ai_research_agent.ingestion.collector import collect_and_save_research_updates
from ai_research_agent.ingestion.freshness import (
    FreshArticle,
    filter_fresh_articles,
    load_freshness_config,
    save_quarantine,
)
from ai_research_agent.ingestion.models import CollectedArticle
from ai_research_agent.llm import LLMClient
from ai_research_agent.pipeline.run_manifest import (
    PipelineState,
    RunManifest,
    load_pipeline_state,
    new_run_id,
    save_pipeline_state,
    save_run_manifest,
    utc_now_iso,
)
from ai_research_agent.reporting.daily_digest import save_daily_digest
from ai_research_agent.storage.article_registry import ArticleRegistry

LOGGER = logging.getLogger(__name__)

RAW_ARTICLES_DIR = Path("data/raw_articles")
SCORED_ARTICLES_DIR = Path("data/scored_articles")
ENRICHED_ARTICLES_DIR = Path("data/enriched_articles")
DAILY_OUTPUT_DIR = Path("output/daily")
QUARANTINE_DIR = Path("data/quarantine")
STATE_PATH = Path("data/state/pipeline_state.json")
RUNS_DIR = Path("data/runs")
DEFAULT_PROFILE_PATH = Path("config/profile.yaml")
DEFAULT_ANALYSIS_PROMPT_PATH = Path("prompts/research_analysis.md")
DEFAULT_DAILY_DIGEST_PROMPT_PATH = Path("prompts/daily_digest.md")


@dataclass(frozen=True)
class DailyDigestConfig:
    """Configurable limits and thresholds for daily digest selection."""

    max_detailed_articles: int = 5
    max_short_articles: int = 2
    minimum_detailed_score: int = 6
    minimum_short_score: int = 3
    max_enriched_text_chars: int = 12000
    max_articles_to_score: int = 35


@dataclass(frozen=True)
class ScoredArticle:
    """Collected article with CSS relevance score."""

    article: CollectedArticle
    relevance: ResearchRelevanceScore
    article_id: str = ""
    canonical_url: str = ""
    published_at: str = ""
    first_seen_at: str = ""
    freshness_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the required scored JSON shape."""
        return {
            "title": self.article.title,
            "source": self.article.source,
            "url": self.article.url,
            "published_date": self.article.published_date,
            "score": self.relevance.score,
            "categories": self.relevance.categories,
            "reason": self.relevance.reason,
            "research_question": self.relevance.research_question,
            "method": self.relevance.method,
            "main_result": self.relevance.main_result,
            "research_value": self.relevance.research_value,
            "research_value_score": self.relevance.research_value_score.to_dict(),
            "why_relevant_to_user": self.relevance.why_relevant_to_user,
            "research_intelligence": {
                "research_question": self.relevance.research_question,
                "method": self.relevance.method,
                "findings": self.relevance.main_result,
                "significance": self.relevance.research_value,
                "connection_to_user_research_interests": self.relevance.why_relevant_to_user,
            },
            "output_quality": validate_relevance_output(self.relevance).to_dict(),
            "obsidian_schema": {
                "type": "ai_research_article",
                "schema_version": "0.1",
                "properties": [
                    "title",
                    "source",
                    "url",
                    "published_date",
                    "score",
                    "categories",
                    "research_intelligence",
                    "output_quality",
                ],
            },
            "decision": self.relevance.decision,
            "summary": self.article.summary,
            "category": self.article.category,
            "article_id": self.article_id,
            "canonical_url": self.canonical_url or self.article.url,
            "published_at": self.published_at or self.article.published_date,
            "first_seen_at": self.first_seen_at,
            "freshness_status": self.freshness_status,
        }


@dataclass(frozen=True)
class SelectedArticles:
    """Selected articles by analysis depth."""

    detailed: list[ScoredArticle]
    short: list[ScoredArticle]
    excluded: list[ScoredArticle]

    @property
    def all_selected(self) -> list[ScoredArticle]:
        """Return selected detailed and short articles."""
        return [*self.detailed, *self.short]


@dataclass(frozen=True)
class EnrichedArticle:
    """Selected article with saved text for analysis or digest context."""

    scored_article: ScoredArticle
    text: str
    path: Path
    used_fallback: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a compact JSON-friendly representation."""
        return {
            **self.scored_article.to_dict(),
            "enriched_text_path": self.path.as_posix(),
            "used_fallback": self.used_fallback,
        }


@dataclass(frozen=True)
class ArticleAnalysisRecord:
    """Detailed article analysis result or transparent failure."""

    scored_article: ScoredArticle
    markdown: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a compact representation for digest prompts."""
        return {
            "article": self.scored_article.to_dict(),
            "analysis": self.markdown,
            "error": self.error,
        }


@dataclass(frozen=True)
class DailyRunResult:
    """Artifacts produced by one daily pipeline run."""

    target_date: date
    collected_articles: list[CollectedArticle]
    scored_articles: list[ScoredArticle]
    selected_articles: SelectedArticles
    enriched_articles: list[EnrichedArticle]
    analyses: list[ArticleAnalysisRecord]
    raw_path: Path
    scored_path: Path
    report_path: Path | None
    manifest_path: Path
    state_path: Path
    registry_path: Path
    failures: list[str]
    dry_run: bool


class DailyPipeline:
    """Coordinate collection, relevance scoring, selection, analysis, and digest writing."""

    def __init__(
        self,
        client: LLMClient,
        profile_path: Path = DEFAULT_PROFILE_PATH,
        analysis_prompt_path: Path = DEFAULT_ANALYSIS_PROMPT_PATH,
        digest_prompt_path: Path = DEFAULT_DAILY_DIGEST_PROMPT_PATH,
        raw_dir: Path = RAW_ARTICLES_DIR,
        scored_dir: Path = SCORED_ARTICLES_DIR,
        enriched_root_dir: Path = ENRICHED_ARTICLES_DIR,
        output_dir: Path = DAILY_OUTPUT_DIR,
        quarantine_dir: Path = QUARANTINE_DIR,
        state_path: Path = STATE_PATH,
        runs_dir: Path = RUNS_DIR,
        registry: ArticleRegistry | None = None,
        collect_func: Callable[[date, Path], list[CollectedArticle]] | None = None,
        relevance_func: Callable[[CollectedArticle, LLMClient, Path], ResearchRelevanceScore]
        | None = None,
        analysis_func: Callable[[Path, LLMClient, Path, Path], Any] | None = None,
        digest_func: Callable[..., Path] | None = None,
        enricher: Callable[[ScoredArticle, date, Path, int], EnrichedArticle] | None = None,
    ) -> None:
        self.client = client
        self.profile_path = profile_path
        self.analysis_prompt_path = analysis_prompt_path
        self.digest_prompt_path = digest_prompt_path
        self.raw_dir = raw_dir
        self.scored_dir = scored_dir
        self.enriched_root_dir = enriched_root_dir
        self.output_dir = output_dir
        self.quarantine_dir = quarantine_dir
        self.state_path = state_path
        self.runs_dir = runs_dir
        self.registry = registry or ArticleRegistry()
        self.collect_func = collect_func or _default_collect
        self.relevance_func = relevance_func or evaluate_article_relevance
        self.analysis_func = analysis_func or _default_analyze
        self.digest_func = digest_func or save_daily_digest
        self.enricher = enricher or enrich_selected_article

    def run(
        self,
        target_date: date | None = None,
        max_detailed: int | None = None,
        dry_run: bool = False,
        explain_filtering: bool = False,
    ) -> DailyRunResult:
        """Run the daily workflow."""
        run_date = target_date or datetime.now(UTC).date()
        profile = load_research_profile(self.profile_path)
        config = load_daily_digest_config(profile, max_detailed=max_detailed)
        freshness_config = load_freshness_config(profile)
        state = load_pipeline_state(self.state_path)
        run_id = new_run_id(run_date)
        started_at = utc_now_iso()
        manifest = RunManifest(
            run_id=run_id,
            started_at=started_at,
            completed_at=None,
            requested_report_date=run_date.isoformat(),
            previous_successful_run_at=state.previous_successful_run_at,
            configuration_snapshot={
                "daily_digest": asdict(config),
                "freshness": asdict(freshness_config),
            },
        )
        state.current_run_id = run_id
        save_pipeline_state(state, self.state_path)
        failures: list[str] = []

        collected = self.collect_func(run_date, self.raw_dir)
        raw_path = self.raw_dir / f"{run_date.isoformat()}.json"
        if not collected:
            failures.append("未收集到任何官方AI研究更新。")

        freshness = filter_fresh_articles(
            articles=collected,
            registry=self.registry,
            config=freshness_config,
            manifest=manifest,
            now=datetime.now(UTC),
            previous_successful_run_at=state.previous_successful_run_at,
        )
        save_quarantine(freshness.quarantined_articles, self.quarantine_dir, run_date)

        scoring_candidates = prepare_scoring_candidates(
            [fresh.article for fresh in freshness.fresh_articles],
            config,
        )
        fresh_by_url = {fresh.article.url: fresh for fresh in freshness.fresh_articles}
        scoring_fresh_articles = [
            fresh_by_url[article.url]
            for article in scoring_candidates
            if article.url in fresh_by_url
        ]

        scored = self._score_articles(scoring_fresh_articles, failures)
        scored_path = save_scored_articles(scored, self.scored_dir, run_date)
        selected = select_articles(scored, config)
        manifest.scored_article_ids = [article.article_id for article in scored]
        manifest.selected_article_ids = [article.article_id for article in selected.all_selected]
        manifest.completed_at = utc_now_iso()
        manifest_path = save_run_manifest(manifest, self.runs_dir)

        if explain_filtering:
            print_filtering_explanation(collected, freshness, scored, selected)

        if dry_run:
            save_pipeline_state(
                PipelineState(
                    previous_successful_run_at=state.previous_successful_run_at,
                    current_run_id=run_id,
                    last_successful_run_id=state.last_successful_run_id,
                    last_collected_count=len(collected),
                    last_fresh_count=len(freshness.fresh_articles),
                    last_duplicate_count=len(freshness.duplicate_articles),
                    last_quarantine_count=len(freshness.quarantined_articles),
                    last_scored_count=len(scored),
                    last_selected_count=len(selected.all_selected),
                ),
                self.state_path,
            )
            return DailyRunResult(
                target_date=run_date,
                collected_articles=collected,
                scored_articles=scored,
                selected_articles=selected,
                enriched_articles=[],
                analyses=[],
                raw_path=raw_path,
                scored_path=scored_path,
                report_path=None,
                manifest_path=manifest_path,
                state_path=self.state_path,
                registry_path=self.registry.path,
                failures=failures,
                dry_run=True,
            )

        enriched = self._enrich_selected(selected.detailed, run_date, config, failures)
        analyses = self._analyze_enriched(enriched, failures)

        if not collected and not analyses and not selected.short:
            raise ResearchAgentError("Daily workflow could not produce any meaningful report.")

        report_path = self.digest_func(
            client=self.client,
            target_date=run_date,
            profile=profile,
            collected_articles=collected,
            scored_articles=scored,
            selected_articles=selected,
            enriched_articles=enriched,
            analyses=analyses,
            failures=failures,
            prompt_path=self.digest_prompt_path,
            output_dir=self.output_dir,
        )
        completed_at = utc_now_iso()
        for selected_article in selected.all_selected:
            self.registry.update_processed(
                article_id=selected_article.article_id,
                processed_at=completed_at,
                score=selected_article.relevance.score,
                report_date=run_date.isoformat(),
                status="reported",
            )
        save_pipeline_state(
            PipelineState(
                previous_successful_run_at=completed_at,
                current_run_id=run_id,
                last_successful_run_id=run_id,
                last_collected_count=len(collected),
                last_fresh_count=len(freshness.fresh_articles),
                last_duplicate_count=len(freshness.duplicate_articles),
                last_quarantine_count=len(freshness.quarantined_articles),
                last_scored_count=len(scored),
                last_selected_count=len(selected.all_selected),
            ),
            self.state_path,
        )

        return DailyRunResult(
            target_date=run_date,
            collected_articles=collected,
            scored_articles=scored,
            selected_articles=selected,
            enriched_articles=enriched,
            analyses=analyses,
            raw_path=raw_path,
            scored_path=scored_path,
            report_path=report_path,
            manifest_path=manifest_path,
            state_path=self.state_path,
            registry_path=self.registry.path,
            failures=failures,
            dry_run=False,
        )

    def _score_articles(
        self,
        articles: Iterable[FreshArticle],
        failures: list[str],
    ) -> list[ScoredArticle]:
        scored: list[ScoredArticle] = []
        for fresh_article in articles:
            article = fresh_article.article
            try:
                relevance = self.relevance_func(article, self.client, self.profile_path)
            except Exception as exc:  # noqa: BLE001
                message = f"相关性评分失败：{article.title} ({exc})"
                LOGGER.warning(message)
                failures.append(message)
                continue
            quality_check = validate_relevance_output(relevance)
            if not quality_check.passed:
                message = (
                    "Research output quality check failed: "
                    f"{article.title} ({', '.join(quality_check.issues)})"
                )
                LOGGER.warning(message)
                failures.append(message)
            scored.append(
                ScoredArticle(
                    article=article,
                    relevance=relevance,
                    article_id=fresh_article.article_id,
                    canonical_url=fresh_article.canonical.canonical_url,
                    published_at=fresh_article.published_at,
                    first_seen_at=datetime.now(UTC).isoformat(),
                    freshness_status=fresh_article.freshness_status,
                )
            )
        return scored

    def _enrich_selected(
        self,
        selected: Iterable[ScoredArticle],
        run_date: date,
        config: DailyDigestConfig,
        failures: list[str],
    ) -> list[EnrichedArticle]:
        enriched: list[EnrichedArticle] = []
        output_dir = self.enriched_root_dir / run_date.isoformat()
        for scored_article in selected:
            try:
                enriched.append(
                    self.enricher(
                        scored_article,
                        run_date,
                        output_dir,
                        config.max_enriched_text_chars,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                message = f"文章富集失败，已跳过深度分析：{scored_article.article.title} ({exc})"
                LOGGER.warning(message)
                failures.append(message)
        return enriched

    def _analyze_enriched(
        self,
        enriched_articles: Iterable[EnrichedArticle],
        failures: list[str],
    ) -> list[ArticleAnalysisRecord]:
        analyses: list[ArticleAnalysisRecord] = []
        for enriched in enriched_articles:
            try:
                result = self.analysis_func(
                    enriched.path,
                    self.client,
                    self.profile_path,
                    self.analysis_prompt_path,
                )
                analyses.append(
                    ArticleAnalysisRecord(
                        scored_article=enriched.scored_article,
                        markdown=str(result.markdown),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                message = f"文章深度分析失败：{enriched.scored_article.article.title} ({exc})"
                LOGGER.warning(message)
                failures.append(message)
                analyses.append(
                    ArticleAnalysisRecord(
                        scored_article=enriched.scored_article,
                        markdown="",
                        error=str(exc),
                    )
                )
        return analyses


def run_daily_pipeline(
    client: LLMClient,
    target_date: date | None = None,
    max_detailed: int | None = None,
    dry_run: bool = False,
    explain_filtering: bool = False,
) -> DailyRunResult:
    """Convenience wrapper for the default daily pipeline."""
    return DailyPipeline(client=client).run(
        target_date=target_date,
        max_detailed=max_detailed,
        dry_run=dry_run,
        explain_filtering=explain_filtering,
    )


def load_daily_digest_config(profile: dict, max_detailed: int | None = None) -> DailyDigestConfig:
    """Load daily digest config from profile YAML with conservative defaults."""
    values = profile.get("daily_digest", {})
    if not isinstance(values, dict):
        values = {}

    config = DailyDigestConfig(
        max_detailed_articles=_int_config(values, "max_detailed_articles", 5),
        max_short_articles=_int_config(values, "max_short_articles", 2),
        minimum_detailed_score=_int_config(values, "minimum_detailed_score", 6),
        minimum_short_score=_int_config(values, "minimum_short_score", 3),
        max_enriched_text_chars=_int_config(values, "max_enriched_text_chars", 12000),
        max_articles_to_score=_int_config(values, "max_articles_to_score", 35),
    )
    if max_detailed is None:
        return config
    return DailyDigestConfig(
        max_detailed_articles=max(0, max_detailed),
        max_short_articles=config.max_short_articles,
        minimum_detailed_score=config.minimum_detailed_score,
        minimum_short_score=config.minimum_short_score,
        max_enriched_text_chars=config.max_enriched_text_chars,
        max_articles_to_score=config.max_articles_to_score,
    )


def prepare_scoring_candidates(
    articles: list[CollectedArticle],
    config: DailyDigestConfig,
) -> list[CollectedArticle]:
    """Remove obvious page chrome and cap LLM relevance scoring volume."""
    candidates = [
        article
        for article in articles
        if article.title.strip()
        and article.summary.strip()
        and not _looks_like_navigation(article)
        and _normalize_url_key(article.url)
    ]
    deduped: list[CollectedArticle] = []
    seen: set[str] = set()
    for article in candidates:
        key = _normalize_url_key(article.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(article)
    ranked = sorted(
        deduped,
        key=lambda article: (_date_sort_key(article.published_date), len(article.summary)),
        reverse=True,
    )
    return ranked[: config.max_articles_to_score]


def save_scored_articles(
    scored_articles: list[ScoredArticle],
    output_dir: Path = SCORED_ARTICLES_DIR,
    target_date: date | None = None,
) -> Path:
    """Save scored article JSON for inspection."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_date = target_date or datetime.now(UTC).date()
    path = output_dir / f"{output_date.isoformat()}.json"
    payload = [article.to_dict() for article in scored_articles]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def select_articles(
    scored_articles: list[ScoredArticle],
    config: DailyDigestConfig,
) -> SelectedArticles:
    """Rank and select articles by relevance, recency, and near-duplicate filtering."""
    ranked = sorted(
        scored_articles,
        key=lambda item: (item.relevance.score, _date_sort_key(item.article.published_date)),
        reverse=True,
    )
    unique = _remove_near_duplicates(ranked)
    detailed: list[ScoredArticle] = []
    short: list[ScoredArticle] = []
    excluded: list[ScoredArticle] = []

    for item in unique:
        score = item.relevance.score
        if score >= config.minimum_detailed_score and len(detailed) < config.max_detailed_articles:
            detailed.append(item)
        elif score >= config.minimum_short_score and len(short) < config.max_short_articles:
            short.append(item)
        else:
            excluded.append(item)
    return SelectedArticles(detailed=detailed, short=short, excluded=excluded)


def print_filtering_explanation(
    collected: list[CollectedArticle],
    freshness: Any,
    scored: list[ScoredArticle],
    selected: SelectedArticles,
) -> None:
    """Print human-readable filtering counts for dry-run inspection."""
    print("Filtering explanation:")
    print(f"- total links discovered: {len(collected)}")
    valid_count = (
        len(freshness.fresh_articles)
        + len(freshness.historical_articles)
        + len(freshness.duplicate_articles)
    )
    print(f"- valid article pages: {valid_count}")
    print(f"- fresh articles: {len(freshness.fresh_articles)}")
    print(f"- historical articles excluded: {len(freshness.historical_articles)}")
    print(f"- exact/near duplicates excluded: {len(freshness.duplicate_articles)}")
    print(f"- unknown-date items quarantined: {len(freshness.quarantined_articles)}")
    print(f"- articles sent to relevance scoring: {len(scored)}")
    print(f"- selected articles: {len(selected.all_selected)}")


def enrich_selected_article(
    scored_article: ScoredArticle,
    target_date: date,
    output_dir: Path,
    max_text_chars: int,
    timeout_seconds: int = 20,
) -> EnrichedArticle:
    """Fetch selected official article text, falling back to collected summary on failure."""
    article = scored_article.article
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{_safe_stem(article.source)}_{_safe_stem(article.title)}.md"
    try:
        if not _is_official_url(article):
            raise ResearchAgentError(f"Not an official source URL: {article.url}")
        text = _fetch_article_text(article.url, timeout_seconds=timeout_seconds)
        if not text:
            raise ResearchAgentError("Official page did not contain extractable article text.")
        used_fallback = False
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Enrichment failed for %s; using summary fallback: %s", article.title, exc)
        text = article.summary or article.title
        used_fallback = True

    text = text[:max_text_chars].strip()
    content = _format_enriched_article(scored_article, text, target_date, used_fallback)
    path.write_text(content, encoding="utf-8")
    return EnrichedArticle(
        scored_article=scored_article,
        text=text,
        path=path,
        used_fallback=used_fallback,
    )


def _default_collect(target_date: date, output_dir: Path) -> list[CollectedArticle]:
    return collect_and_save_research_updates(output_dir=output_dir, today=target_date)


def _default_analyze(
    article_path: Path,
    client: LLMClient,
    profile_path: Path,
    prompt_path: Path,
) -> Any:
    return analyze_article(
        article_path=article_path,
        client=client,
        profile_path=profile_path,
        prompt_path=prompt_path,
    )


def _fetch_article_text(url: str, timeout_seconds: int) -> str:
    response = requests.get(
        url,
        timeout=timeout_seconds,
        headers={"User-Agent": "AIResearchAgent/0.1 daily briefing enricher"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for selector in ("nav", "footer", "header", "script", "style", "noscript", "form"):
        for node in soup.select(selector):
            node.decompose()
    for node in soup.find_all(string=re.compile("cookie|subscribe|newsletter", re.IGNORECASE)):
        parent = getattr(node, "parent", None)
        if parent:
            parent.decompose()

    main = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = [
        " ".join(element.get_text(" ", strip=True).split())
        for element in main.find_all(["h1", "h2", "h3", "p", "li"])
    ]
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def _format_enriched_article(
    scored_article: ScoredArticle,
    text: str,
    target_date: date,
    used_fallback: bool,
) -> str:
    article = scored_article.article
    return f"""\
---
date: "{target_date.isoformat()}"
source: "{article.source}"
url: "{article.url}"
published_date: "{article.published_date}"
score: {scored_article.relevance.score}
used_summary_fallback: {str(used_fallback).lower()}
---

# {article.title}

{text}
"""


def _remove_near_duplicates(scored_articles: list[ScoredArticle]) -> list[ScoredArticle]:
    selected: list[ScoredArticle] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    for item in scored_articles:
        url_key = _normalize_url_key(item.article.url)
        title_key = _normalize_title(item.article.title)
        if url_key in seen_urls:
            continue
        if any(SequenceMatcher(None, title_key, prior).ratio() >= 0.88 for prior in seen_titles):
            continue
        seen_urls.add(url_key)
        seen_titles.append(title_key)
        selected.append(item)
    return selected


def _date_sort_key(value: str) -> str:
    return value or "0000-00-00"


def _is_official_url(article: CollectedArticle) -> bool:
    host = urlparse(article.url).netloc.lower()
    official_hosts = {
        "Anthropic": ("anthropic.com", "www.anthropic.com"),
        "OpenAI": ("openai.com", "www.openai.com"),
        "Google DeepMind": ("deepmind.google",),
        "Microsoft Research": ("microsoft.com", "www.microsoft.com"),
        "Meta AI Research": ("ai.meta.com",),
        "IBM Research AI": ("research.ibm.com",),
    }
    return host in official_hosts.get(article.source, ())


def _normalize_url_key(url: str) -> str:
    parsed = urlparse(url.strip())
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".lower().rstrip("/")


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", title.lower()).strip()


def _looks_like_navigation(article: CollectedArticle) -> bool:
    title = article.title.strip().lower()
    path = urlparse(article.url).path.strip("/").lower()
    blocked_titles = {
        "skip to main content",
        "policy",
        "careers",
        "contact",
        "about",
        "news",
        "research",
        "blog",
        "privacy",
        "terms",
        "security",
        "menu",
        "home",
    }
    if title in blocked_titles:
        return True
    if len(title) < 8 and path in {"", "research", "blog", "discover/blog"}:
        return True
    return False


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff._-]+", "-", value.strip()).strip("-._")
    return (stem or "article")[:90]


def _int_config(values: dict[str, object], key: str, default: int) -> int:
    try:
        return int(values.get(key, default))
    except (TypeError, ValueError):
        return default
