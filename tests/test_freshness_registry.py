from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ai_research_agent.ingestion.deduplication import (
    canonicalize_url,
    is_allowed_official_article,
    title_jaccard_similarity,
)
from ai_research_agent.ingestion.freshness import (
    FreshnessConfig,
    filter_fresh_articles,
    load_freshness_config,
)
from ai_research_agent.ingestion.models import CollectedArticle
from ai_research_agent.pipeline.daily import (
    DailyDigestConfig,
    prepare_scoring_candidates,
    select_articles,
)
from ai_research_agent.pipeline.run_manifest import (
    PipelineState,
    RunManifest,
    load_pipeline_state,
    save_pipeline_state,
)
from ai_research_agent.storage.article_registry import ArticleRegistry
from tests.test_daily_pipeline import _scored


def test_first_run_bootstrap_window(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    result = _filter(
        tmp_path,
        [_article("Fresh", "https://www.anthropic.com/research/fresh", "2026-07-13")],
        now=now,
        previous=None,
    )

    assert len(result.fresh_articles) == 1
    assert result.fresh_articles[0].freshness_status == "newly_discovered_within_window"


def test_pipeline_config_loads_bootstrap_mode() -> None:
    config = load_freshness_config(
        {
            "pipeline": {"mode": "bootstrap", "bootstrap_days": 30},
            "freshness": {"normal_lookback_hours": 24},
        }
    )

    assert config.mode == "bootstrap"
    assert config.bootstrap_lookback_days == 30
    assert config.normal_lookback_hours == 24


def test_daily_mode_first_run_uses_normal_window(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    result = _filter(
        tmp_path,
        [_article("Seven days old", "https://www.anthropic.com/research/seven", "2026-07-07")],
        now=now,
        previous=None,
        config=FreshnessConfig(mode="daily", normal_lookback_hours=36),
    )

    assert len(result.fresh_articles) == 0
    assert len(result.historical_articles) == 1


def test_daily_mode_uses_academic_window_for_conference_sources(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    article = CollectedArticle(
        title="Large Language Models and Online Behavior",
        source="ICWSM Research",
        url="https://ojs.aaai.org/index.php/ICWSM/article/view/123",
        published_date="2026-05-25",
        summary="Computational social science research on online behavior.",
        category="Computational Social Science",
    )

    result = _filter(
        tmp_path,
        [article],
        now=now,
        previous="2026-07-13T00:00:00+00:00",
        config=FreshnessConfig(
            mode="daily",
            normal_lookback_hours=36,
            academic_lookback_days=180,
        ),
    )

    assert len(result.fresh_articles) == 1
    assert len(result.historical_articles) == 0


def test_daily_mode_keeps_normal_window_for_non_academic_sources(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    result = _filter(
        tmp_path,
        [_article("Old industry", "https://www.anthropic.com/research/old-industry", "2026-05-25")],
        now=now,
        previous="2026-07-13T00:00:00+00:00",
        config=FreshnessConfig(
            mode="daily",
            normal_lookback_hours=36,
            academic_lookback_days=180,
        ),
    )

    assert len(result.fresh_articles) == 0
    assert len(result.historical_articles) == 1


def test_bootstrap_mode_allows_historical_articles_within_window(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    result = _filter(
        tmp_path,
        [
            _article(
                "Bootstrap old",
                "https://www.anthropic.com/research/bootstrap-old",
                "2026-07-01",
            )
        ],
        now=now,
        previous="2026-07-13T00:00:00+00:00",
        config=FreshnessConfig(mode="bootstrap", bootstrap_lookback_days=30),
    )

    assert len(result.fresh_articles) == 1
    assert result.fresh_articles[0].freshness_status == "newly_discovered_within_window"


def test_bootstrap_mode_reprocesses_unprocessed_registry_records(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    article = _article(
        "Bootstrap replay",
        "https://www.anthropic.com/research/replay",
        "2026-07-01",
    )
    daily = _filter(
        tmp_path,
        [article],
        registry=registry,
        now=datetime(2026, 7, 14, tzinfo=UTC),
        config=FreshnessConfig(mode="daily", normal_lookback_hours=36),
    )
    bootstrap = _filter(
        tmp_path,
        [article],
        registry=registry,
        now=datetime(2026, 7, 14, tzinfo=UTC),
        config=FreshnessConfig(mode="bootstrap", bootstrap_lookback_days=30),
    )

    assert len(daily.historical_articles) == 1
    assert len(bootstrap.fresh_articles) == 1
    assert len(bootstrap.duplicate_articles) == 0


def test_daily_mode_retries_fresh_unprocessed_registry_records(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    article = _article(
        "Daily replay",
        "https://www.anthropic.com/research/daily-replay",
        "2026-07-13",
    )
    _filter(tmp_path, [article], registry=registry, config=FreshnessConfig(mode="daily"))

    second = _filter(tmp_path, [article], registry=registry, config=FreshnessConfig(mode="daily"))

    assert len(second.fresh_articles) == 1
    assert second.fresh_articles[0].freshness_status == "newly_discovered_within_window"


def test_daily_mode_does_not_retry_historical_unprocessed_registry_records(
    tmp_path: Path,
) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    article = _article(
        "Old replay",
        "https://www.anthropic.com/research/old-replay",
        "2026-07-01",
    )
    _filter(
        tmp_path,
        [article],
        registry=registry,
        now=datetime(2026, 7, 14, tzinfo=UTC),
        config=FreshnessConfig(mode="daily"),
    )

    second = _filter(
        tmp_path,
        [article],
        registry=registry,
        now=datetime(2026, 7, 14, tzinfo=UTC),
        config=FreshnessConfig(mode="daily"),
    )

    assert len(second.historical_articles) == 1
    assert second.excluded_reasons[second.historical_articles[0].article_id] == (
        "historical_unprocessed"
    )


def test_previous_run_freshness_filtering(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    previous = "2026-07-13T00:00:00+00:00"
    result = _filter(
        tmp_path,
        [
            _article("New", "https://www.anthropic.com/research/new", "2026-07-13"),
            _article("Old", "https://www.anthropic.com/research/old", "2026-07-10"),
        ],
        now=now,
        previous=previous,
    )

    assert len(result.fresh_articles) == 1
    assert len(result.historical_articles) == 1


def test_canonical_url_normalization() -> None:
    assert (
        canonicalize_url(
            "HTTPS://OpenAI.com//research/test/?b=2&utm_source=x&a=1#fragment"
        )
        == "https://openai.com/research/test?a=1&b=2"
    )


def test_acm_and_icwsm_article_urls_are_allowed() -> None:
    acm = CollectedArticle(
        title="Algorithmic fairness in public services",
        source="ACM FAccT Research",
        url="https://dl.acm.org/doi/10.1145/1234567",
        published_date="2026-06-01",
        summary="Fairness and accountability in AI governance.",
        category="AI Governance",
    )
    icwsm = CollectedArticle(
        title="Large Language Models and Online Behavior",
        source="ICWSM Research",
        url="https://ojs.aaai.org/index.php/ICWSM/article/view/123",
        published_date="2026-05-25",
        summary="Computational social science and online behavior.",
        category="Computational Social Science",
    )

    assert is_allowed_official_article(acm)
    assert is_allowed_official_article(icwsm)


def test_tracking_parameter_removal() -> None:
    assert canonicalize_url("https://openai.com/research/a?ref=x&source=y&id=1").endswith("?id=1")


def test_exact_url_deduplication(tmp_path: Path) -> None:
    article = _article("Duplicate", "https://www.anthropic.com/research/dup", "2026-07-13")
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    first = _filter(tmp_path, [article], registry=registry)
    registry.update_processed(
        first.fresh_articles[0].article_id,
        "2026-07-14T00:00:00+00:00",
        5,
        None,
        status="scored",
    )
    second = _filter(tmp_path, [article], registry=registry)

    assert len(first.fresh_articles) == 1
    assert len(second.duplicate_articles) == 1


def test_exact_content_deduplication(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    first = _article("Same", "https://www.anthropic.com/research/same-a", "2026-07-13")
    second = _article("Same", "https://www.anthropic.com/research/same-b", "2026-07-13")

    _filter(tmp_path, [first], registry=registry)
    result = _filter(tmp_path, [second], registry=registry)

    assert len(result.duplicate_articles) == 1


def test_near_duplicate_title_detection() -> None:
    assert title_jaccard_similarity("New AI safety system", "New AI safety systems") >= 0.75


def test_missing_date_quarantine(tmp_path: Path) -> None:
    result = _filter(tmp_path, [_article("Missing", "https://www.anthropic.com/research/m", "")])

    assert len(result.quarantined_articles) == 1


def test_generic_page_fallback_without_explicit_date_is_quarantined(tmp_path: Path) -> None:
    article = CollectedArticle(
        title="Alignment",
        source="Anthropic",
        url="https://www.anthropic.com/research/team/alignment",
        published_date="2026-07-14",
        summary=(
            "Anthropic is an AI safety and research company that's working to build reliable, "
            "interpretable, and steerable AI systems."
        ),
        category="AI研究机构",
    )

    result = _filter(tmp_path, [article])

    assert len(result.quarantined_articles) == 1


def test_explicit_title_date_overrides_crawl_date(tmp_path: Path) -> None:
    article = CollectedArticle(
        title="Jun 16, 2026 Economic Research Agentic coding",
        source="Anthropic",
        url="https://www.anthropic.com/research/claude-code-expertise",
        published_date="2026-07-14",
        summary="Research summary",
        category="AI研究机构",
    )

    result = _filter(tmp_path, [article], now=datetime(2026, 7, 14, tzinfo=UTC))

    assert len(result.historical_articles) == 1


def test_future_date_quarantine(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    result = _filter(
        tmp_path,
        [_article("Future", "https://www.anthropic.com/research/future", "2026-07-20")],
        now=now,
    )

    assert len(result.quarantined_articles) == 1


def test_weak_date_rejection(tmp_path: Path) -> None:
    result = _filter(tmp_path, [_article("Weak", "https://www.anthropic.com/research/weak", "bad")])

    assert len(result.quarantined_articles) == 1


def test_historical_article_exclusion(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    result = _filter(
        tmp_path,
        [_article("Old", "https://www.anthropic.com/research/old", "2026-07-01")],
        now=now,
    )

    assert len(result.historical_articles) == 1


def test_already_reported_article_exclusion(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    article = _article("Reported", "https://www.anthropic.com/research/reported", "2026-07-13")
    first = _filter(tmp_path, [article], registry=registry)
    registry.update_processed(
        first.fresh_articles[0].article_id,
        "2026-07-14T00:00:00+00:00",
        9,
        "2026-07-14",
    )

    second = _filter(tmp_path, [article], registry=registry)

    assert second.excluded_reasons[first.fresh_articles[0].article_id] == "previously_reported"


def test_material_update_acceptance(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    article = _article("Update", "https://www.anthropic.com/research/update", "2026-07-13")
    first = _filter(tmp_path, [article], registry=registry, now=datetime(2026, 7, 13, tzinfo=UTC))
    registry.update_processed(
        first.fresh_articles[0].article_id,
        "2026-07-13T00:00:00+00:00",
        9,
        "2026-07-13",
    )
    changed = CollectedArticle(
        **{**article.to_dict(), "summary": "Materially changed official content"}
    )

    second = _filter(
        tmp_path,
        [changed],
        registry=registry,
        now=datetime(2026, 7, 14, tzinfo=UTC),
    )

    assert len(second.material_updates) == 1


def test_insignificant_html_change_rejection(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    article = _article("Same", "https://www.anthropic.com/research/same", "2026-07-13")
    first = _filter(tmp_path, [article], registry=registry)
    registry.update_processed(
        first.fresh_articles[0].article_id,
        "2026-07-14T00:00:00+00:00",
        9,
        "2026-07-14",
    )

    second = _filter(tmp_path, [article], registry=registry)

    assert len(second.duplicate_articles) == 1


def test_failed_run_does_not_update_previous_successful_run_at(tmp_path: Path) -> None:
    state = PipelineState(previous_successful_run_at="2026-07-13T00:00:00+00:00")
    path = save_pipeline_state(state, tmp_path / "state.json")

    loaded = load_pipeline_state(path)

    assert loaded.previous_successful_run_at == "2026-07-13T00:00:00+00:00"


def test_successful_run_updates_state(tmp_path: Path) -> None:
    path = save_pipeline_state(
        PipelineState(previous_successful_run_at="2026-07-14T00:00:00+00:00"),
        tmp_path / "state.json",
    )

    assert load_pipeline_state(path).previous_successful_run_at == "2026-07-14T00:00:00+00:00"


def test_scoring_limit_applied_after_freshness_filtering() -> None:
    fresh = [
        _article(str(index), f"https://www.anthropic.com/research/{index}", "2026-07-13")
        for index in range(5)
    ]
    limited = prepare_scoring_candidates(
        fresh,
        DailyDigestConfig(max_articles_to_score=2),
    )

    assert len(limited) == 2


def test_final_digest_receives_only_current_selected_ids() -> None:
    selected = select_articles(
        [
            _scored(_article("A", "https://www.anthropic.com/research/a", "2026-07-13"), 9),
            _scored(_article("B", "https://www.anthropic.com/research/b", "2026-07-13"), 2),
        ],
        DailyDigestConfig(),
    )

    assert len(selected.all_selected) == 1


def test_old_raw_json_files_cannot_leak_into_new_report(tmp_path: Path) -> None:
    old = tmp_path / "data" / "raw_articles" / "2026-07-01.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps([{"title": "old"}]), encoding="utf-8")

    assert old.exists()


def test_run_manifest_audit_fields(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest.fresh_article_ids.append("abc")

    assert manifest.run_id == "run"
    assert manifest.fresh_article_ids == ["abc"]


def test_one_source_failure_does_not_corrupt_registry_state(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")

    assert registry.stats().total_registered_articles == 0


def test_registry_upsert_behavior(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    article = _article("Upsert", "https://www.anthropic.com/research/upsert", "2026-07-13")
    first = _filter(tmp_path, [article], registry=registry)
    changed = CollectedArticle(**{**article.to_dict(), "summary": "Changed"})
    _filter(tmp_path, [changed], registry=registry)

    record = registry.get_by_url(first.fresh_articles[0].canonical.canonical_url)
    assert record is not None
    assert record["previous_content_hash"]


def test_bootstrap_reset_keeps_article_count_unchanged(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    article = _article("Reset", "https://www.anthropic.com/research/reset", "2026-07-13")
    first = _filter(tmp_path, [article], registry=registry)
    registry.update_processed(
        first.fresh_articles[0].article_id,
        "2026-07-14T00:00:00+00:00",
        9,
        "2026-07-14",
    )

    before = registry.stats().total_registered_articles
    registry.bootstrap_reset_processing_state()
    after = registry.stats().total_registered_articles

    assert before == after == 1


def test_bootstrap_reset_preserves_metadata(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    article = _article("Metadata", "https://www.anthropic.com/research/metadata", "2026-07-13")
    first = _filter(tmp_path, [article], registry=registry)
    canonical_url = first.fresh_articles[0].canonical.canonical_url
    before = registry.get_by_url(canonical_url)

    registry.bootstrap_reset_processing_state()
    after = registry.get_by_url(canonical_url)

    assert before is not None
    assert after is not None
    assert after["canonical_url"] == before["canonical_url"]
    assert after["normalized_title"] == before["normalized_title"]
    assert after["source"] == before["source"]
    assert after["published_at"] == before["published_at"]
    assert after["content_hash"] == before["content_hash"]


def test_bootstrap_reset_clears_processing_fields(tmp_path: Path) -> None:
    registry = ArticleRegistry(tmp_path / "registry.sqlite3")
    article = _article("Processed", "https://www.anthropic.com/research/processed", "2026-07-13")
    first = _filter(tmp_path, [article], registry=registry)
    article_id = first.fresh_articles[0].article_id
    canonical_url = first.fresh_articles[0].canonical.canonical_url
    registry.update_processed(article_id, "2026-07-14T00:00:00+00:00", 9, "2026-07-14")

    registry.bootstrap_reset_processing_state()
    record = registry.get_by_url(canonical_url)

    assert record is not None
    assert record["first_processed_at"] is None
    assert record["last_processed_at"] is None
    assert record["last_report_date"] is None
    assert record["processing_status"] == "discovered"
    assert record["last_relevance_score"] is None


def test_bootstrap_reset_pipeline_state(tmp_path: Path) -> None:
    state_path = tmp_path / "pipeline_state.json"
    save_pipeline_state(
        PipelineState(
            previous_successful_run_at="2026-07-14T00:00:00+00:00",
            last_successful_run_id="run-1",
            current_run_id="run-2",
            last_collected_count=10,
        ),
        state_path,
    )
    state = load_pipeline_state(state_path)
    state.previous_successful_run_at = None
    state.last_successful_run_id = None
    save_pipeline_state(state, state_path)

    reset_state = load_pipeline_state(state_path)

    assert reset_state.previous_successful_run_at is None
    assert reset_state.last_successful_run_id is None
    assert reset_state.current_run_id == "run-2"
    assert reset_state.last_collected_count == 10


def _article(title: str, url: str, published_date: str) -> CollectedArticle:
    return CollectedArticle(
        title=f"{title} AI research article",
        source="Anthropic",
        url=url,
        published_date=published_date,
        summary=f"Summary for {title}",
        category="AI研究机构",
    )


def _filter(
    tmp_path: Path,
    articles: list[CollectedArticle],
    registry: ArticleRegistry | None = None,
    now: datetime | None = None,
    previous: str | None = None,
    config: FreshnessConfig | None = None,
):
    return filter_fresh_articles(
        articles=articles,
        registry=registry or ArticleRegistry(tmp_path / "registry.sqlite3"),
        config=config or FreshnessConfig(),
        manifest=_manifest(),
        now=now or datetime(2026, 7, 14, tzinfo=UTC),
        previous_successful_run_at=previous,
    )


def _manifest() -> RunManifest:
    return RunManifest(
        run_id="run",
        started_at="2026-07-14T00:00:00+00:00",
        completed_at=None,
        requested_report_date="2026-07-14",
        previous_successful_run_at=None,
    )
