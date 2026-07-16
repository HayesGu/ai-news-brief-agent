from pathlib import Path

import pytest

from ai_research_agent.core.errors import InputFileError
from ai_research_agent.ingestion.articles import load_article_text


def test_unsupported_input_type(tmp_path: Path) -> None:
    article_path = tmp_path / "article.pdf"
    article_path.write_text("not really a PDF", encoding="utf-8")

    with pytest.raises(InputFileError, match="Unsupported article file type"):
        load_article_text(article_path)


def test_empty_input(tmp_path: Path) -> None:
    article_path = tmp_path / "article.md"
    article_path.write_text("   \n", encoding="utf-8")

    with pytest.raises(InputFileError, match="Article file is empty"):
        load_article_text(article_path)
