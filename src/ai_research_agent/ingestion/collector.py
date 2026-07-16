"""RSS and official-page ingestion for frontier AI research updates."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from time import struct_time
from urllib.parse import urljoin, urlparse, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup

from ai_research_agent.ingestion.models import CollectedArticle, ResearchSource
from ai_research_agent.ingestion.sources import get_default_sources

LOGGER = logging.getLogger(__name__)
RAW_ARTICLES_DIR = Path("data/raw_articles")
REQUEST_TIMEOUT_SECONDS = 20
MAX_PAGE_LINKS_PER_SOURCE = 25


class ResearchUpdateCollector:
    """Collect AI research updates from official feeds and public pages."""

    def __init__(
        self,
        sources: Iterable[ResearchSource] | None = None,
        timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        self.sources = sorted(
            list(sources or get_default_sources()),
            key=lambda source: source.source_priority,
            reverse=True,
        )
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def collect(self) -> list[CollectedArticle]:
        """Collect and deduplicate articles across all configured sources."""
        articles: list[CollectedArticle] = []
        for source in self.sources:
            try:
                source_articles = self._collect_source(source)
            except requests.RequestException as exc:
                LOGGER.warning("Failed to collect %s: %s", source.name, exc)
                continue
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Unexpected ingestion error for %s: %s", source.name, exc)
                continue
            articles.extend(source_articles)
        return _deduplicate_articles(articles)

    def _collect_source(self, source: ResearchSource) -> list[CollectedArticle]:
        for feed_url in _source_feed_urls(source):
            try:
                articles = self._collect_feed(feed_url, source)
            except requests.RequestException as exc:
                LOGGER.info("Feed unavailable for %s via %s: %s", source.name, feed_url, exc)
                continue
            if articles:
                return _filter_by_source_keywords(articles, source)
        return _filter_by_source_keywords(self._collect_page(source), source)

    def _collect_feed(self, feed_url: str, source: ResearchSource) -> list[CollectedArticle]:
        response = self._get(feed_url)
        parsed_feed = feedparser.parse(response.content)
        entries = getattr(parsed_feed, "entries", [])
        articles = [
            article
            for entry in entries
            if (article := self._article_from_feed_entry(entry, source)) is not None
        ]
        if not articles:
            LOGGER.info("No feed entries found for %s via %s", source.name, feed_url)
        return articles

    def _collect_page(self, source: ResearchSource) -> list[CollectedArticle]:
        response = self._get(source.page_url)
        soup = BeautifulSoup(response.text, "html.parser")
        page_summary = _clean_text(_meta_content(soup, "description")) or source.name
        page_date = _extract_page_date(soup)
        articles: list[CollectedArticle] = []

        for link in soup.select(
            "article a[href], h1 a[href], h2 a[href], h3 a[href], h4 a[href], a[href]"
        ):
            title = _clean_text(link.get_text(" ", strip=True))
            url = _normalize_url(urljoin(source.page_url, link.get("href", "")))
            if not title or not _is_http_url(url):
                continue
            articles.append(
                CollectedArticle(
                    title=title,
                    source=source.name,
                    url=url,
                    published_date=page_date,
                    summary=page_summary,
                    category=source.category,
                )
            )
            if len(articles) >= MAX_PAGE_LINKS_PER_SOURCE:
                break

        if not articles:
            LOGGER.warning("No article links found on %s", source.page_url)
        return _deduplicate_articles(articles)

    def _article_from_feed_entry(
        self,
        entry: object,
        source: ResearchSource,
    ) -> CollectedArticle | None:
        title = _clean_text(_entry_get(entry, "title"))
        url = _normalize_url(_entry_get(entry, "link"))
        summary = _clean_text(
            _entry_get(entry, "summary")
            or _entry_get(entry, "description")
            or _entry_get(entry, "subtitle")
            or title
        )
        published_date = _entry_published_date(entry)

        if not title or not summary or not _is_http_url(url):
            return None

        return CollectedArticle(
            title=title,
            source=source.name,
            url=url,
            published_date=published_date,
            summary=summary,
            category=source.category,
        )

    def _get(self, url: str) -> requests.Response:
        response = self.session.get(
            url,
            timeout=self.timeout_seconds,
            headers={
                "User-Agent": (
                    "AIResearchAgent/0.1 "
                    "(personal computational social science research collector)"
                )
            },
        )
        response.raise_for_status()
        return response


def collect_and_save_research_updates(
    output_dir: Path = RAW_ARTICLES_DIR,
    sources: Iterable[ResearchSource] | None = None,
    today: date | None = None,
) -> list[CollectedArticle]:
    """Collect official AI research updates and save them as daily JSON."""
    collector = ResearchUpdateCollector(sources=sources)
    articles = collector.collect()
    save_raw_articles(articles, output_dir=output_dir, today=today)
    return articles


def save_raw_articles(
    articles: list[CollectedArticle],
    output_dir: Path = RAW_ARTICLES_DIR,
    today: date | None = None,
) -> Path:
    """Save collected articles as UTF-8 JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_date = today or datetime.now(UTC).date()
    output_path = output_dir / f"{output_date.isoformat()}.json"
    payload = [article.to_dict() for article in articles]
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def _deduplicate_articles(articles: Iterable[CollectedArticle]) -> list[CollectedArticle]:
    seen: set[str] = set()
    deduplicated: list[CollectedArticle] = []
    for article in articles:
        key = _dedupe_key(article)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(article)
    return deduplicated


def _source_feed_urls(source: ResearchSource) -> tuple[str, ...]:
    urls = [source.feed_url, *source.feed_urls]
    return tuple(dict.fromkeys(url for url in urls if url))


def _filter_by_source_keywords(
    articles: Iterable[CollectedArticle],
    source: ResearchSource,
) -> list[CollectedArticle]:
    keywords = tuple(keyword.strip().lower() for keyword in source.research_focus_keywords)
    if not keywords:
        return list(articles)

    filtered = [
        article
        for article in articles
        if _matches_source_keywords(article, keywords)
    ]
    if not filtered:
        LOGGER.info("No source-keyword matches for %s", source.name)
    return filtered


def _matches_source_keywords(article: CollectedArticle, keywords: tuple[str, ...]) -> bool:
    text = f"{article.title} {article.summary}".lower()
    return any(keyword in text for keyword in keywords)


def _dedupe_key(article: CollectedArticle) -> str:
    if article.url:
        return _normalize_url(article.url).lower().rstrip("/")
    return f"{article.source}:{article.title}".lower()


def _entry_get(entry: object, key: str) -> str:
    if isinstance(entry, dict):
        value = entry.get(key, "")
    else:
        value = getattr(entry, key, "")
    return str(value or "").strip()


def _entry_published_date(entry: object) -> str:
    parsed = _entry_get_raw(entry, "published_parsed") or _entry_get_raw(entry, "updated_parsed")
    if isinstance(parsed, struct_time):
        return date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday).isoformat()

    for key in ("published", "updated", "created"):
        value = _entry_get(entry, key)
        if not value:
            continue
        parsed_date = _parse_date_string(value)
        if parsed_date:
            return parsed_date
    return datetime.now(UTC).date().isoformat()


def _entry_get_raw(entry: object, key: str) -> object:
    if isinstance(entry, dict):
        return entry.get(key)
    return getattr(entry, key, None)


def _parse_date_string(value: str) -> str | None:
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        pass

    if len(value) >= 10:
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def _extract_page_date(soup: BeautifulSoup) -> str:
    time_element = soup.find("time")
    if time_element:
        raw_date = time_element.get("datetime") or time_element.get_text(" ", strip=True)
        if isinstance(raw_date, str):
            parsed_date = _parse_date_string(raw_date)
            if parsed_date:
                return parsed_date
    return datetime.now(UTC).date().isoformat()


def _meta_content(soup: BeautifulSoup, name: str) -> str:
    element = soup.find("meta", attrs={"name": name}) or soup.find(
        "meta",
        attrs={"property": f"og:{name}"},
    )
    value = element.get("content", "") if element else ""
    return str(value)


def _clean_text(value: str) -> str:
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())


def _normalize_url(url: str) -> str:
    parsed = urlparse(str(url).strip())
    if not parsed.scheme and parsed.netloc:
        parsed = parsed._replace(scheme="https")
    return urlunparse(parsed._replace(fragment=""))


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
