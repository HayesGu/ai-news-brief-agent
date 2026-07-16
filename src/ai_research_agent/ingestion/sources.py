"""Official AI research organization sources for feed and page ingestion."""

from ai_research_agent.ingestion.models import ResearchSource


def get_default_sources() -> list[ResearchSource]:
    """Return official AI research organization sources."""
    return [
        ResearchSource(
            name="Anthropic",
            page_url="https://www.anthropic.com/research",
            category="AI Research",
            feed_url="https://www.anthropic.com/research/rss.xml",
            feed_urls=(
                "https://www.anthropic.com/research/rss.xml",
                "https://www.anthropic.com/rss.xml",
            ),
            source_priority=100,
            research_focus_keywords=(
                "AI safety",
                "interpretability",
                "alignment",
                "AI governance",
                "AI agents",
                "frontier models",
            ),
        ),
        ResearchSource(
            name="OpenAI",
            page_url="https://openai.com/research/",
            category="AI Research",
            feed_url="https://openai.com/research/rss.xml",
            feed_urls=(
                "https://openai.com/research/rss.xml",
                "https://openai.com/news/rss.xml",
            ),
            source_priority=100,
            research_focus_keywords=(
                "AI",
                "LLM",
                "AI agents",
                "safety",
                "governance",
                "human",
            ),
        ),
        ResearchSource(
            name="Google DeepMind",
            page_url="https://deepmind.google/discover/blog/",
            category="AI Research",
            feed_url="https://deepmind.google/discover/blog/rss.xml",
            feed_urls=(
                "https://deepmind.google/discover/blog/rss.xml",
                "https://deepmind.google/blog/rss.xml",
            ),
            source_priority=95,
            research_focus_keywords=(
                "AI",
                "agents",
                "safety",
                "responsible AI",
                "science",
                "human",
            ),
        ),
        ResearchSource(
            name="Microsoft Research",
            category="AI Research",
            page_url="https://www.microsoft.com/en-us/research/blog/",
            feed_url="https://www.microsoft.com/en-us/research/feed/",
            source_priority=90,
            research_focus_keywords=(
                "human AI interaction",
                "AI agents",
                "social computing",
                "responsible AI",
                "AI governance",
                "machine learning",
            ),
        ),
        ResearchSource(
            name="Meta AI Research",
            category="AI Research",
            page_url="https://ai.meta.com/research/",
            feed_url="https://ai.meta.com/blog/",
            source_priority=85,
            research_focus_keywords=(
                "open source AI",
                "LLM",
                "AI agents",
                "social impact",
                "human AI interaction",
            ),
        ),
        ResearchSource(
            name="IBM Research AI",
            category="AI Governance",
            page_url="https://research.ibm.com/artificial-intelligence",
            feed_url="https://research.ibm.com/blog",
            source_priority=85,
            research_focus_keywords=(
                "trustworthy AI",
                "AI ethics",
                "AI governance",
                "explainability",
                "fairness",
            ),
        ),
    ]
