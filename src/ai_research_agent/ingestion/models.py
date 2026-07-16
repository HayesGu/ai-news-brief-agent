"""Data models for AI research ingestion."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ResearchSource:
    """Official AI research source configuration."""

    name: str
    page_url: str
    category: str
    feed_url: str = ""
    feed_urls: tuple[str, ...] = ()
    source_priority: int = 50
    research_focus_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class CollectedArticle:
    """Normalized article collected from an official research source."""

    title: str
    source: str
    url: str
    published_date: str
    summary: str
    category: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable representation."""
        return asdict(self)
