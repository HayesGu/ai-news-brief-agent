"""Local article file loading for analysis."""

from pathlib import Path

from ai_research_agent.core.errors import InputFileError

SUPPORTED_ARTICLE_SUFFIXES = {".md", ".txt"}


def load_article_text(path: Path) -> str:
    """Load a local UTF-8 Markdown or text article."""
    if path.suffix.lower() not in SUPPORTED_ARTICLE_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_ARTICLE_SUFFIXES))
        message = f"Unsupported article file type '{path.suffix}'. Use one of: {supported}"
        raise InputFileError(message)
    if not path.exists():
        raise InputFileError(f"Article file not found: {path}")
    if not path.is_file():
        raise InputFileError(f"Article path is not a file: {path}")

    try:
        article_text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InputFileError(f"Article must be a UTF-8 text or Markdown file: {path}") from exc
    except OSError as exc:
        raise InputFileError(f"Could not read article file {path}: {exc}") from exc

    if not article_text.strip():
        raise InputFileError(f"Article file is empty: {path}")
    return article_text
