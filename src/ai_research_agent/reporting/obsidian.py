"""Daily knowledge-base synchronization for generated Markdown reports."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ai_research_agent.core.errors import ResearchAgentError

DEFAULT_DAILY_KB_PATH = Path(r"D:\path\to\your\obsidian\vault\01 Daily")


@dataclass(frozen=True)
class DailyKnowledgeBaseSyncConfig:
    """Local daily knowledge-base sync settings."""

    daily_kb_path: Path = DEFAULT_DAILY_KB_PATH
    sync_enabled: bool = False


def load_daily_kb_config_from_env(
    daily_kb_path: Path | None = None,
    sync_enabled: bool | None = None,
) -> DailyKnowledgeBaseSyncConfig:
    """Load daily knowledge-base sync settings from environment variables and CLI overrides."""
    configured_path = os.getenv("OBSIDIAN_DAILY_KB_PATH", str(DEFAULT_DAILY_KB_PATH))
    raw_daily_kb_path = daily_kb_path or Path(configured_path).expanduser()
    enabled = (
        _env_bool(os.getenv("OBSIDIAN_DAILY_KB_SYNC_ENABLED", "false"))
        if sync_enabled is None
        else sync_enabled
    )
    return DailyKnowledgeBaseSyncConfig(
        daily_kb_path=raw_daily_kb_path,
        sync_enabled=enabled,
    )


def sync_daily_report_to_knowledge_base(
    report_path: Path,
    config: DailyKnowledgeBaseSyncConfig,
) -> Path:
    """Copy a generated daily Markdown report into the daily knowledge base."""
    source = report_path.resolve()
    if not source.exists() or not source.is_file():
        raise ResearchAgentError(f"Daily report does not exist: {report_path}")
    if source.suffix.lower() != ".md":
        raise ResearchAgentError(
            f"Only Markdown reports can be synced to the daily knowledge base: {report_path}"
        )

    destination_dir = config.daily_kb_path
    if destination_dir.exists() and not destination_dir.is_dir():
        raise ResearchAgentError(
            f"Daily knowledge-base path is not a directory: {destination_dir}"
        )
    destination_dir.mkdir(parents=True, exist_ok=True)

    destination = destination_dir / source.name
    shutil.copyfile(source, destination)
    return destination


def _env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}

