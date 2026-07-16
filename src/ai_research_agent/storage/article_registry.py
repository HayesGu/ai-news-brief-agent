"""Persistent SQLite article registry for cross-run deduplication."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path("data/state/article_registry.sqlite3")


@dataclass(frozen=True)
class RegistryStats:
    """Summary statistics for registry CLI output."""

    total_registered_articles: int
    articles_by_source: dict[str, int]
    previously_reported_articles: int
    quarantined_articles: int
    material_updates: int


class ArticleRegistry:
    """SQLite-backed article registry using safe parameterized SQL."""

    def __init__(self, path: Path = REGISTRY_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS articles (
                    article_id TEXT PRIMARY KEY,
                    canonical_url TEXT NOT NULL UNIQUE,
                    normalized_title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    published_at TEXT,
                    publication_date_source TEXT,
                    publication_date_confidence TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    first_processed_at TEXT,
                    last_processed_at TEXT,
                    content_hash TEXT NOT NULL,
                    previous_content_hash TEXT,
                    processing_status TEXT NOT NULL,
                    last_relevance_score INTEGER,
                    last_report_date TEXT,
                    discovered_run_id TEXT,
                    updated_run_id TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS article_aliases (
                    alias_url TEXT PRIMARY KEY,
                    article_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            for column in ("source", "published_at", "first_seen_at", "content_hash"):
                connection.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_articles_{column} ON articles ({column})"
                )

    def get_by_url(self, canonical_url: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM articles WHERE canonical_url = ?",
                (canonical_url,),
            ).fetchone()
        return dict(row) if row else None

    def get_by_content_hash(self, content_hash: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM articles WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
        return dict(row) if row else None

    def list_title_records(self, source: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT article_id, normalized_title, source, published_at, content_hash "
            "FROM articles"
        )
        params: tuple[str, ...] = ()
        if source:
            query += " WHERE source = ?"
            params = (source,)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def upsert_article(self, record: dict[str, Any]) -> None:
        """Insert or update article while preserving previous content hash."""
        existing = self.get_by_url(record["canonical_url"])
        previous_hash = None
        if existing and existing["content_hash"] != record["content_hash"]:
            previous_hash = existing["content_hash"]
        else:
            previous_hash = existing.get("previous_content_hash") if existing else None

        values = {**record, "previous_content_hash": previous_hash}
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO articles (
                    article_id, canonical_url, normalized_title, source, published_at,
                    publication_date_source, publication_date_confidence,
                    first_seen_at, last_seen_at, first_processed_at, last_processed_at,
                    content_hash, previous_content_hash, processing_status,
                    last_relevance_score, last_report_date, discovered_run_id, updated_run_id
                )
                VALUES (
                    :article_id, :canonical_url, :normalized_title, :source, :published_at,
                    :publication_date_source, :publication_date_confidence,
                    :first_seen_at, :last_seen_at, :first_processed_at, :last_processed_at,
                    :content_hash, :previous_content_hash, :processing_status,
                    :last_relevance_score, :last_report_date, :discovered_run_id, :updated_run_id
                )
                ON CONFLICT(canonical_url) DO UPDATE SET
                    normalized_title = excluded.normalized_title,
                    source = excluded.source,
                    published_at = excluded.published_at,
                    publication_date_source = excluded.publication_date_source,
                    publication_date_confidence = excluded.publication_date_confidence,
                    last_seen_at = excluded.last_seen_at,
                    last_processed_at = COALESCE(
                        excluded.last_processed_at,
                        articles.last_processed_at
                    ),
                    content_hash = excluded.content_hash,
                    previous_content_hash = excluded.previous_content_hash,
                    processing_status = excluded.processing_status,
                    last_relevance_score = COALESCE(
                        excluded.last_relevance_score,
                        articles.last_relevance_score
                    ),
                    last_report_date = COALESCE(
                        excluded.last_report_date,
                        articles.last_report_date
                    ),
                    updated_run_id = excluded.updated_run_id
                """,
                values,
            )

    def update_processed(
        self,
        article_id: str,
        processed_at: str,
        score: int | None,
        report_date: str | None,
        status: str = "reported",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE articles
                SET first_processed_at = COALESCE(first_processed_at, ?),
                    last_processed_at = ?,
                    last_relevance_score = COALESCE(?, last_relevance_score),
                    last_report_date = COALESCE(?, last_report_date),
                    processing_status = ?
                WHERE article_id = ?
                """,
                (processed_at, processed_at, score, report_date, status, article_id),
            )

    def add_alias(self, alias_url: str, article_id: str, created_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO article_aliases (alias_url, article_id, created_at)
                VALUES (?, ?, ?)
                """,
                (alias_url, article_id, created_at),
            )

    def stats(self) -> RegistryStats:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            by_source_rows = connection.execute(
                "SELECT source, COUNT(*) AS count FROM articles GROUP BY source"
            ).fetchall()
            reported = connection.execute(
                "SELECT COUNT(*) FROM articles WHERE last_report_date IS NOT NULL"
            ).fetchone()[0]
            quarantined = connection.execute(
                "SELECT COUNT(*) FROM articles WHERE processing_status = 'quarantined'"
            ).fetchone()[0]
            material_updates = connection.execute(
                "SELECT COUNT(*) FROM articles WHERE processing_status = 'material_update'"
            ).fetchone()[0]
        return RegistryStats(
            total_registered_articles=int(total),
            articles_by_source={str(row["source"]): int(row["count"]) for row in by_source_rows},
            previously_reported_articles=int(reported),
            quarantined_articles=int(quarantined),
            material_updates=int(material_updates),
        )

    def reset(self) -> None:
        with self._connect() as connection:
            connection.execute("DROP TABLE IF EXISTS article_aliases")
            connection.execute("DROP TABLE IF EXISTS articles")
        self._initialize()

    def bootstrap_reset_processing_state(self) -> None:
        """Clear processing/reporting state while preserving discovered article metadata."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE articles
                SET first_processed_at = NULL,
                    last_processed_at = NULL,
                    last_report_date = NULL,
                    processing_status = 'discovered',
                    last_relevance_score = NULL
                """
            )
