"""Freshness, novelty, quarantine, and cross-run filtering."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from ai_research_agent.ingestion.deduplication import (
    CanonicalArticle,
    canonical_article,
    is_allowed_official_article,
    title_jaccard_similarity,
)
from ai_research_agent.ingestion.models import CollectedArticle
from ai_research_agent.pipeline.run_manifest import RunManifest
from ai_research_agent.storage.article_registry import ArticleRegistry

DateConfidence = Literal["high", "medium", "low", "unknown"]
PipelineMode = Literal["daily", "bootstrap"]
FreshnessStatus = Literal[
    "newly_published",
    "newly_discovered_within_window",
    "material_update",
]


@dataclass(frozen=True)
class FreshnessConfig:
    """Freshness and novelty policy."""

    mode: PipelineMode = "daily"
    bootstrap_lookback_days: int = 30
    normal_lookback_hours: int = 36
    academic_lookback_days: int = 180
    future_date_tolerance_hours: int = 6
    allow_unknown_dates_in_daily: bool = False
    allow_low_confidence_dates_in_daily: bool = False
    material_update_minimum_age_hours: int = 12
    title_similarity_threshold: float = 0.88
    same_source_similarity_threshold: float = 0.82


@dataclass(frozen=True)
class FreshArticle:
    """Article accepted for current relevance scoring."""

    article: CollectedArticle
    canonical: CanonicalArticle
    published_at: str
    publication_date_source: str
    publication_date_confidence: DateConfidence
    freshness_status: FreshnessStatus

    @property
    def article_id(self) -> str:
        return self.canonical.article_id


@dataclass
class FreshnessFilterResult:
    """Output of pre-LLM freshness filtering."""

    fresh_articles: list[FreshArticle] = field(default_factory=list)
    duplicate_articles: list[FreshArticle] = field(default_factory=list)
    historical_articles: list[FreshArticle] = field(default_factory=list)
    quarantined_articles: list[dict[str, Any]] = field(default_factory=list)
    material_updates: list[FreshArticle] = field(default_factory=list)
    excluded_reasons: dict[str, str] = field(default_factory=dict)


def load_freshness_config(profile: dict) -> FreshnessConfig:
    """Load freshness and deduplication config from profile."""
    pipeline = profile.get("pipeline", {})
    freshness = profile.get("freshness", {})
    deduplication = profile.get("deduplication", {})
    if not isinstance(pipeline, dict):
        pipeline = {}
    if not isinstance(freshness, dict):
        freshness = {}
    if not isinstance(deduplication, dict):
        deduplication = {}
    mode = str(pipeline.get("mode", "daily")).strip().lower()
    if mode not in {"daily", "bootstrap"}:
        mode = "daily"
    return FreshnessConfig(
        mode=mode,  # type: ignore[arg-type]
        bootstrap_lookback_days=_int(
            pipeline,
            "bootstrap_days",
            _int(freshness, "bootstrap_lookback_days", 30),
        ),
        normal_lookback_hours=_int(freshness, "normal_lookback_hours", 36),
        academic_lookback_days=_int(freshness, "academic_lookback_days", 180),
        future_date_tolerance_hours=_int(freshness, "future_date_tolerance_hours", 6),
        allow_unknown_dates_in_daily=bool(freshness.get("allow_unknown_dates_in_daily", False)),
        allow_low_confidence_dates_in_daily=bool(
            freshness.get("allow_low_confidence_dates_in_daily", False)
        ),
        material_update_minimum_age_hours=_int(
            freshness,
            "material_update_minimum_age_hours",
            12,
        ),
        title_similarity_threshold=_float(deduplication, "title_similarity_threshold", 0.88),
        same_source_similarity_threshold=_float(
            deduplication,
            "same_source_similarity_threshold",
            0.82,
        ),
    )


def filter_fresh_articles(
    articles: list[CollectedArticle],
    registry: ArticleRegistry,
    config: FreshnessConfig,
    manifest: RunManifest,
    now: datetime,
    previous_successful_run_at: str | None,
) -> FreshnessFilterResult:
    """Filter collected articles before any LLM relevance scoring."""
    result = FreshnessFilterResult()
    previous_run = _parse_datetime(previous_successful_run_at)
    seen_current_hashes: set[str] = set()
    seen_current_titles: list[FreshArticle] = []

    for article in articles:
        try:
            if not is_allowed_official_article(article):
                raise ValueError("invalid_or_non_article_url")
            canonical = canonical_article(article)
        except ValueError as exc:
            article_id = _fallback_article_id(article)
            manifest.quarantined_article_ids.append(article_id)
            result.excluded_reasons[article_id] = str(exc)
            result.quarantined_articles.append(_quarantine_payload(article, str(exc)))
            continue

        manifest.collected_article_ids.append(canonical.article_id)
        published_at, date_source, confidence = resolve_publication_date(article)

        fresh_article = FreshArticle(
            article=article,
            canonical=canonical,
            published_at=published_at or "",
            publication_date_source=date_source,
            publication_date_confidence=confidence,
            freshness_status="newly_published",
        )

        quarantine_reason = _date_quarantine_reason(published_at, confidence, config, now)
        if quarantine_reason:
            _register(registry, fresh_article, manifest, now, "quarantined")
            manifest.quarantined_article_ids.append(canonical.article_id)
            result.excluded_reasons[canonical.article_id] = quarantine_reason
            result.quarantined_articles.append(_quarantine_payload(article, quarantine_reason))
            continue

        existing = registry.get_by_url(canonical.canonical_url)
        retry_existing_unprocessed = False
        same_content = registry.get_by_content_hash(canonical.content_hash)
        if existing:
            if existing.get("last_report_date"):
                if _is_material_update(existing, canonical.content_hash, published_at, config, now):
                    fresh_article = _replace_status(fresh_article, "material_update")
                    result.material_updates.append(fresh_article)
                    manifest.material_update_article_ids.append(canonical.article_id)
                else:
                    _register(registry, fresh_article, manifest, now, "previously_reported")
                    manifest.duplicate_article_ids.append(canonical.article_id)
                    result.excluded_reasons[canonical.article_id] = "previously_reported"
                    result.duplicate_articles.append(fresh_article)
                    continue
            elif _is_unprocessed_record(existing):
                retry_existing_unprocessed = True
            elif _is_bootstrap_reprocessable(existing, published_at, config, now):
                fresh_article = _replace_status(fresh_article, "newly_discovered_within_window")
            elif existing.get("content_hash") == canonical.content_hash:
                _register(registry, fresh_article, manifest, now, "discovered")
                manifest.duplicate_article_ids.append(canonical.article_id)
                result.excluded_reasons[canonical.article_id] = "exact_url_duplicate"
                result.duplicate_articles.append(fresh_article)
                continue
            else:
                fresh_article = _replace_status(fresh_article, "material_update")
                result.material_updates.append(fresh_article)
                manifest.material_update_article_ids.append(canonical.article_id)
        elif same_content:
            registry.add_alias(canonical.canonical_url, same_content["article_id"], now.isoformat())
            _register(registry, fresh_article, manifest, now, "duplicate")
            manifest.duplicate_article_ids.append(canonical.article_id)
            result.excluded_reasons[canonical.article_id] = "exact_content_duplicate"
            result.duplicate_articles.append(fresh_article)
            continue
        elif _is_near_duplicate(fresh_article, seen_current_titles, registry, config):
            _register(registry, fresh_article, manifest, now, "duplicate")
            manifest.duplicate_article_ids.append(canonical.article_id)
            result.excluded_reasons[canonical.article_id] = "near_duplicate_title"
            result.duplicate_articles.append(fresh_article)
            continue

        if canonical.content_hash in seen_current_hashes:
            manifest.duplicate_article_ids.append(canonical.article_id)
            result.excluded_reasons[canonical.article_id] = "same_run_content_duplicate"
            result.duplicate_articles.append(fresh_article)
            continue

        if not _is_fresh(
            published_at,
            previous_run,
            config,
            now,
            source=article.source,
            category=article.category,
        ):
            _register(registry, fresh_article, manifest, now, "discovered")
            manifest.historical_article_ids.append(canonical.article_id)
            result.excluded_reasons[canonical.article_id] = "historical_unprocessed"
            result.historical_articles.append(fresh_article)
            continue

        if (
            (previous_run is None or config.mode == "bootstrap")
            and fresh_article.freshness_status != "material_update"
        ):
            fresh_article = _replace_status(fresh_article, "newly_discovered_within_window")
        elif retry_existing_unprocessed and fresh_article.freshness_status != "material_update":
            fresh_article = _replace_status(fresh_article, "newly_discovered_within_window")

        _register(registry, fresh_article, manifest, now, fresh_article.freshness_status)
        manifest.fresh_article_ids.append(canonical.article_id)
        result.fresh_articles.append(fresh_article)
        seen_current_hashes.add(canonical.content_hash)
        seen_current_titles.append(fresh_article)

    result.fresh_articles = sorted(
        result.fresh_articles,
        key=lambda item: (
            item.published_at,
            _confidence_rank(item.publication_date_confidence),
            _source_priority(item.article.source),
        ),
        reverse=True,
    )
    return result


def resolve_publication_date(article: CollectedArticle) -> tuple[str | None, str, DateConfidence]:
    """Resolve publication timestamp from collected metadata."""
    explicit = _parse_date_from_text(f"{article.title} {article.summary}")
    if explicit:
        return explicit.isoformat(), "explicit_article_text_date", "high"
    if _looks_like_page_fallback(article):
        return None, "missing", "unknown"
    parsed = _parse_date(article.published_date)
    if parsed:
        return parsed.isoformat(), "feed_or_collected_metadata", "medium"
    return None, "missing", "unknown"


def save_quarantine(
    quarantined_items: list[dict[str, Any]],
    output_dir: Path,
    target_date: date,
) -> Path:
    """Save quarantined items as UTF-8 JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{target_date.isoformat()}.json"
    path.write_text(json.dumps(quarantined_items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _register(
    registry: ArticleRegistry,
    fresh_article: FreshArticle,
    manifest: RunManifest,
    now: datetime,
    status: str,
) -> None:
    registry.upsert_article(
        {
            "article_id": fresh_article.article_id,
            "canonical_url": fresh_article.canonical.canonical_url,
            "normalized_title": fresh_article.canonical.normalized_title,
            "source": fresh_article.article.source,
            "published_at": fresh_article.published_at or None,
            "publication_date_source": fresh_article.publication_date_source,
            "publication_date_confidence": fresh_article.publication_date_confidence,
            "first_seen_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "first_processed_at": None,
            "last_processed_at": None,
            "content_hash": fresh_article.canonical.content_hash,
            "previous_content_hash": None,
            "processing_status": status,
            "last_relevance_score": None,
            "last_report_date": None,
            "discovered_run_id": manifest.run_id,
            "updated_run_id": manifest.run_id,
        }
    )


def _is_fresh(
    published_at: str | None,
    previous_run: datetime | None,
    config: FreshnessConfig,
    now: datetime,
    source: str = "",
    category: str = "",
) -> bool:
    if not published_at:
        return False
    published = _parse_datetime(published_at)
    if not published:
        return False
    if config.mode == "bootstrap":
        return published >= now - timedelta(days=config.bootstrap_lookback_days)
    if _uses_academic_lookback(source, category):
        return published >= now - timedelta(days=config.academic_lookback_days)
    if previous_run is None:
        return published >= now - timedelta(hours=config.normal_lookback_hours)
    return published > previous_run - timedelta(hours=config.normal_lookback_hours)


def _is_bootstrap_reprocessable(
    existing: dict[str, Any],
    published_at: str | None,
    config: FreshnessConfig,
    now: datetime,
) -> bool:
    if config.mode != "bootstrap":
        return False
    if existing.get("first_processed_at") or existing.get("last_processed_at"):
        return False
    if existing.get("last_report_date"):
        return False
    return _is_fresh(
        published_at,
        previous_run=None,
        config=config,
        now=now,
        source=str(existing.get("source") or ""),
    )


def _uses_academic_lookback(source: str, category: str) -> bool:
    academic_sources = {
        "ACM CHI Research",
        "ACM CSCW Research",
        "ACM FAccT Research",
        "ICWSM Research",
    }
    return source in academic_sources or category == "Computational Social Science"


def _is_unprocessed_record(existing: dict[str, Any]) -> bool:
    return not (
        existing.get("first_processed_at")
        or existing.get("last_processed_at")
        or existing.get("last_report_date")
    )


def _date_quarantine_reason(
    published_at: str | None,
    confidence: DateConfidence,
    config: FreshnessConfig,
    now: datetime,
) -> str | None:
    if not published_at or confidence == "unknown":
        if not config.allow_unknown_dates_in_daily:
            return "unknown_or_missing_publication_date"
        return None
    if confidence == "low" and not config.allow_low_confidence_dates_in_daily:
        return "low_confidence_publication_date"
    published = _parse_datetime(published_at)
    if not published:
        return "unparseable_publication_date"
    if published > now + timedelta(hours=config.future_date_tolerance_hours):
        return "future_publication_date"
    return None


def _is_material_update(
    existing: dict[str, Any],
    new_content_hash: str,
    published_at: str | None,
    config: FreshnessConfig,
    now: datetime,
) -> bool:
    if existing.get("content_hash") == new_content_hash:
        return False
    first_seen = _parse_datetime(existing.get("first_seen_at"))
    if first_seen and now - first_seen < timedelta(hours=config.material_update_minimum_age_hours):
        return False
    return bool(published_at)


def _is_near_duplicate(
    article: FreshArticle,
    current_articles: list[FreshArticle],
    registry: ArticleRegistry,
    config: FreshnessConfig,
) -> bool:
    for other in current_articles:
        threshold = (
            config.same_source_similarity_threshold
            if other.article.source == article.article.source
            else config.title_similarity_threshold
        )
        if (
            title_jaccard_similarity(article.article.title, other.article.title)
            >= threshold
        ):
            return True
    for record in registry.list_title_records(article.article.source):
        if (
            title_jaccard_similarity(article.canonical.normalized_title, record["normalized_title"])
            >= config.same_source_similarity_threshold
        ):
            return True
    return False


def _replace_status(article: FreshArticle, status: FreshnessStatus) -> FreshArticle:
    return FreshArticle(
        article=article.article,
        canonical=article.canonical,
        published_at=article.published_at,
        publication_date_source=article.publication_date_source,
        publication_date_confidence=article.publication_date_confidence,
        freshness_status=status,
    )


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_date = date.fromisoformat(value[:10])
        except ValueError:
            return None
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_date_from_text(text: str) -> datetime | None:
    month_pattern = (
        r"\b("
        r"Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|"
        r"Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December"
        r")\s+(\d{1,2}),\s+(\d{4})\b"
    )
    match = re.search(month_pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    month_lookup = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    month = month_lookup[match.group(1).lower()]
    day = int(match.group(2))
    year = int(match.group(3))
    return datetime(year, month, day, tzinfo=UTC)


def _looks_like_page_fallback(article: CollectedArticle) -> bool:
    generic_summaries = {
        (
            "anthropic is an ai safety and research company that's working to build reliable, "
            "interpretable, and steerable ai systems."
        ),
    }
    return article.summary.strip().lower() in generic_summaries


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return _parse_date(value)


def _confidence_rank(confidence: DateConfidence) -> int:
    return {"high": 3, "medium": 2, "low": 1, "unknown": 0}[confidence]


def _source_priority(source: str) -> int:
    return {"Anthropic": 3, "OpenAI": 2, "Google DeepMind": 1}.get(source, 0)


def _quarantine_payload(article: CollectedArticle, reason: str) -> dict[str, str]:
    return {**article.to_dict(), "quarantine_reason": reason}


def _fallback_article_id(article: CollectedArticle) -> str:
    return f"{article.source}:{article.url}:{article.title}"


def _int(values: dict[str, object], key: str, default: int) -> int:
    try:
        return int(values.get(key, default))
    except (TypeError, ValueError):
        return default


def _float(values: dict[str, object], key: str, default: float) -> float:
    try:
        return float(values.get(key, default))
    except (TypeError, ValueError):
        return default
