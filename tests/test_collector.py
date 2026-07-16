import json
from datetime import date
from pathlib import Path

import pytest
import requests

from ai_research_agent.ingestion.collector import (
    ResearchUpdateCollector,
    save_raw_articles,
)
from ai_research_agent.ingestion.models import ResearchSource
from ai_research_agent.ingestion.sources import get_default_sources


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse | Exception]) -> None:
        self.responses = responses
        self.requested_urls: list[str] = []

    def get(self, url: str, timeout: int, headers: dict[str, str]) -> FakeResponse:
        assert timeout > 0
        assert headers["User-Agent"]
        self.requested_urls.append(url)
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


def test_successful_collection_from_feed(tmp_path: Path) -> None:
    source = ResearchSource(
        name="Anthropic",
        page_url="https://www.anthropic.com/research",
        category="AI研究机构",
        feed_urls=("https://example.com/feed.xml",),
    )
    session = FakeSession(
        {
            "https://example.com/feed.xml": FakeResponse(
                """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                  <channel>
                    <item>
                      <title>New interpretability research</title>
                      <link>https://www.anthropic.com/research/interpretability</link>
                      <pubDate>Mon, 13 Jul 2026 10:00:00 GMT</pubDate>
                      <description>Research summary</description>
                    </item>
                  </channel>
                </rss>"""
            )
        }
    )

    collector = ResearchUpdateCollector(sources=[source], session=session)
    articles = collector.collect()

    assert len(articles) == 1
    assert articles[0].title == "New interpretability research"
    assert articles[0].source == "Anthropic"
    assert articles[0].published_date == "2026-07-13"

    output_path = save_raw_articles(articles, output_dir=tmp_path, today=date(2026, 7, 13))
    assert output_path.name == "2026-07-13.json"


def test_default_sources_include_ai_research_organization_sources() -> None:
    sources = get_default_sources()
    names = {source.name for source in sources}

    assert "Microsoft Research" in names
    assert "Meta AI Research" in names
    assert "IBM Research AI" in names
    assert "ACM CHI Research" not in names
    assert "ACM CSCW Research" not in names
    assert "ACM FAccT Research" not in names
    assert "ICWSM Research" not in names
    assert all(source.feed_url or source.page_url for source in sources)
    assert all(source.source_priority > 0 for source in sources)
    assert all(source.research_focus_keywords for source in sources)


def test_failed_source_is_logged_and_skipped(caplog: pytest.LogCaptureFixture) -> None:
    source = ResearchSource(
        name="OpenAI",
        page_url="https://openai.com/research/",
        category="AI研究机构",
        feed_urls=("https://example.com/openai-feed.xml",),
    )
    session = FakeSession(
        {
            "https://example.com/openai-feed.xml": requests.Timeout("timeout"),
            "https://openai.com/research/": requests.Timeout("timeout"),
        }
    )

    collector = ResearchUpdateCollector(sources=[source], session=session)
    articles = collector.collect()

    assert articles == []
    assert "Failed to collect OpenAI" in caplog.text


def test_feed_failure_falls_back_to_page() -> None:
    source = ResearchSource(
        name="OpenAI",
        page_url="https://openai.com/research/",
        category="AI研究机构",
        feed_urls=("https://example.com/missing-feed.xml",),
    )
    session = FakeSession(
        {
            "https://example.com/missing-feed.xml": requests.HTTPError("HTTP 404"),
            "https://openai.com/research/": FakeResponse(
                """<html>
                  <head><meta name="description" content="Research page"></head>
                  <body>
                    <article>
                      <h2><a href="/research/frontier-ai">Frontier AI research</a></h2>
                    </article>
                  </body>
                </html>"""
            ),
        }
    )

    collector = ResearchUpdateCollector(sources=[source], session=session)
    articles = collector.collect()

    assert len(articles) == 1
    assert articles[0].title == "Frontier AI research"
    assert articles[0].url == "https://openai.com/research/frontier-ai"


def test_duplicate_filtering() -> None:
    source = ResearchSource(
        name="Google DeepMind",
        page_url="https://deepmind.google/discover/blog/",
        category="AI研究机构",
        feed_urls=("https://example.com/deepmind-feed.xml",),
    )
    session = FakeSession(
        {
            "https://example.com/deepmind-feed.xml": FakeResponse(
                """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                  <channel>
                    <item>
                      <title>Alpha research</title>
                      <link>https://deepmind.google/blog/alpha/</link>
                      <description>First copy</description>
                    </item>
                    <item>
                      <title>Alpha research duplicate</title>
                      <link>https://deepmind.google/blog/alpha</link>
                      <description>Second copy</description>
                    </item>
                  </channel>
                </rss>"""
            )
        }
    )

    collector = ResearchUpdateCollector(sources=[source], session=session)
    articles = collector.collect()

    assert len(articles) == 1
    assert articles[0].url == "https://deepmind.google/blog/alpha/"


def test_source_keyword_filtering_removes_irrelevant_feed_items() -> None:
    source = ResearchSource(
        name="ACM FAccT Research",
        page_url="https://facctconference.org/",
        category="AI Governance",
        feed_url="https://example.com/facct.xml",
        research_focus_keywords=("fairness", "governance", "bias", "accountability"),
    )
    session = FakeSession(
        {
            "https://example.com/facct.xml": FakeResponse(
                """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                  <channel>
                    <item>
                      <title>Algorithmic fairness in public services</title>
                      <link>https://dl.acm.org/doi/10.1145/fairness</link>
                      <description>Fairness and accountability in AI systems.</description>
                    </item>
                    <item>
                      <title>GPU kernel optimization for rendering</title>
                      <link>https://dl.acm.org/doi/10.1145/gpu</link>
                      <description>Low-level graphics engineering benchmark.</description>
                    </item>
                  </channel>
                </rss>"""
            )
        }
    )

    articles = ResearchUpdateCollector(sources=[source], session=session).collect()

    assert len(articles) == 1
    assert articles[0].title == "Algorithmic fairness in public services"


def test_icwsm_page_fallback_collects_h4_ojs_articles() -> None:
    source = ResearchSource(
        name="ICWSM Research",
        page_url="https://ojs.aaai.org/index.php/ICWSM",
        category="Computational Social Science",
        research_focus_keywords=("large language model", "online behavior"),
    )
    session = FakeSession(
        {
            "https://ojs.aaai.org/index.php/ICWSM": FakeResponse(
                """<html>
                  <head><meta name="description" content="ICWSM current issue"></head>
                  <body>
                    <time datetime="2026-05-25">May 25, 2026</time>
                    <h4>
                      <a href="/index.php/ICWSM/article/view/123">
                        Large Language Models and Online Behavior
                      </a>
                    </h4>
                    <h4>
                      <a href="/index.php/ICWSM/article/view/456">
                        Weather Photography Contest
                      </a>
                    </h4>
                  </body>
                </html>"""
            )
        }
    )

    articles = ResearchUpdateCollector(sources=[source], session=session).collect()

    assert len(articles) == 1
    assert articles[0].title == "Large Language Models and Online Behavior"
    assert articles[0].published_date == "2026-05-25"


def test_save_raw_articles_json(tmp_path: Path) -> None:
    source = ResearchSource(
        name="Anthropic",
        page_url="https://www.anthropic.com/research",
        category="AI研究机构",
        feed_urls=("https://example.com/feed.xml",),
    )
    session = FakeSession(
        {
            "https://example.com/feed.xml": FakeResponse(
                """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                  <channel>
                    <item>
                      <title>AI治理 update</title>
                      <link>https://www.anthropic.com/research/governance</link>
                      <description>中文摘要</description>
                    </item>
                  </channel>
                </rss>"""
            )
        }
    )

    articles = ResearchUpdateCollector(sources=[source], session=session).collect()
    output_path = tmp_path / "2026-07-13.json"
    output_path.write_text(
        json.dumps([article.to_dict() for article in articles], ensure_ascii=False),
        encoding="utf-8",
    )

    assert "AI治理 update" in output_path.read_text(encoding="utf-8")
