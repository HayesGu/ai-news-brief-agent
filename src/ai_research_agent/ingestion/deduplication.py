"""URL canonicalization and deterministic article deduplication helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ai_research_agent.ingestion.models import CollectedArticle

TRACKING_PARAMETERS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "ref",
    "source",
}

SOURCE_RULES = {
    "Anthropic": {
        "domains": {"anthropic.com", "www.anthropic.com"},
        "blocked_paths": {
            "",
            "research",
            "policy",
            "careers",
            "contact",
            "about",
            "privacy",
            "terms",
            "security",
        },
        "asset_extensions": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css"},
    },
    "OpenAI": {
        "domains": {"openai.com", "www.openai.com"},
        "blocked_paths": {"", "research", "news", "careers", "about", "privacy", "policies"},
        "asset_extensions": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css"},
    },
    "Google DeepMind": {
        "domains": {"deepmind.google"},
        "blocked_paths": {"", "discover", "discover/blog", "about", "careers", "privacy"},
        "asset_extensions": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css"},
    },
    "Microsoft Research": {
        "domains": {"microsoft.com", "www.microsoft.com"},
        "blocked_paths": {
            "",
            "en-us",
            "en-us/research",
            "en-us/research/blog",
            "en-us/research/people",
            "en-us/research/careers",
        },
        "asset_extensions": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css"},
    },
    "Meta AI Research": {
        "domains": {"ai.meta.com"},
        "blocked_paths": {"", "research", "blog"},
        "asset_extensions": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css"},
    },
    "IBM Research AI": {
        "domains": {"research.ibm.com"},
        "blocked_paths": {"", "artificial-intelligence", "blog"},
        "asset_extensions": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css"},
    },
    "ACM CHI Research": {
        "domains": {"dl.acm.org", "chi.acm.org"},
        "blocked_paths": {"", "action/showfeed", "conference", "program"},
        "asset_extensions": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css"},
    },
    "ACM CSCW Research": {
        "domains": {"dl.acm.org", "cscw.acm.org"},
        "blocked_paths": {"", "action/showfeed", "conference", "program"},
        "asset_extensions": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css"},
    },
    "ACM FAccT Research": {
        "domains": {"dl.acm.org", "facctconference.org"},
        "blocked_paths": {"", "action/showfeed", "conference", "program"},
        "asset_extensions": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css"},
    },
    "ICWSM Research": {
        "domains": {"ojs.aaai.org", "icwsm.org", "www.icwsm.org"},
        "blocked_paths": {"", "index.php/icwsm", "index.php/icwsm/issue/current"},
        "asset_extensions": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css"},
    },
}


@dataclass(frozen=True)
class CanonicalArticle:
    """Article plus deterministic identity fields."""

    article: CollectedArticle
    article_id: str
    canonical_url: str
    normalized_title: str
    content_hash: str


def canonicalize_url(url: str) -> str:
    """Return deterministic canonical URL or raise ValueError for unsupported URLs."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Unsupported article URL: {url}")

    host = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")

    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() not in TRACKING_PARAMETERS
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))


def is_allowed_official_article(article: CollectedArticle) -> bool:
    """Return whether the URL is an official article-like page for its source."""
    try:
        canonical_url = canonicalize_url(article.url)
    except ValueError:
        return False

    parsed = urlparse(canonical_url)
    rules = SOURCE_RULES.get(article.source)
    if not rules:
        return False
    if parsed.netloc.lower() not in rules["domains"]:
        return False

    path = parsed.path.strip("/").lower()
    if path in rules["blocked_paths"]:
        return False
    if any(path.endswith(extension) for extension in rules["asset_extensions"]):
        return False
    title = normalize_title(article.title)
    if title in {"skip to main content", "privacy", "careers", "policy", "terms", "menu"}:
        return False
    return bool(title and article.summary.strip())


def canonical_article(article: CollectedArticle) -> CanonicalArticle:
    """Build deterministic article identity from collected metadata."""
    canonical_url = canonicalize_url(article.url)
    normalized_title = normalize_title(article.title)
    content_hash = hash_article_content(article)
    article_id = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]
    return CanonicalArticle(
        article=article,
        article_id=article_id,
        canonical_url=canonical_url,
        normalized_title=normalized_title,
        content_hash=content_hash,
    )


def hash_article_content(article: CollectedArticle) -> str:
    """Hash normalized title plus summary."""
    text = normalize_content(f"{article.title}\n{article.summary}")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    """Normalize title for near-duplicate comparison."""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", title.lower()).strip()


def normalize_content(text: str) -> str:
    """Normalize substantive text for exact-content hashing."""
    return " ".join(text.lower().split())


def title_jaccard_similarity(left: str, right: str) -> float:
    """Compute deterministic token Jaccard similarity."""
    left_tokens = {_soft_stem(token) for token in normalize_title(left).split()}
    right_tokens = {_soft_stem(token) for token in normalize_title(right).split()}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _soft_stem(token: str) -> str:
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token
