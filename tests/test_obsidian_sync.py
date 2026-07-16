from pathlib import Path

import pytest

from ai_research_agent.core.errors import ResearchAgentError
from ai_research_agent.reporting.obsidian import (
    DailyKnowledgeBaseSyncConfig,
    load_daily_kb_config_from_env,
    sync_daily_report_to_knowledge_base,
)


def test_sync_daily_report_to_knowledge_base(tmp_path: Path) -> None:
    report = tmp_path / "2026-07-14_AI_Research_Briefing.md"
    report.write_text("# Test briefing\n", encoding="utf-8")
    destination_dir = tmp_path / "daily_notes"

    synced = sync_daily_report_to_knowledge_base(
        report,
        DailyKnowledgeBaseSyncConfig(daily_kb_path=destination_dir, sync_enabled=True),
    )

    assert synced == destination_dir / report.name
    assert synced.read_text(encoding="utf-8") == "# Test briefing\n"


def test_sync_rejects_non_markdown(tmp_path: Path) -> None:
    report = tmp_path / "report.txt"
    report.write_text("not markdown", encoding="utf-8")

    with pytest.raises(ResearchAgentError, match="Only Markdown reports"):
        sync_daily_report_to_knowledge_base(
            report,
            DailyKnowledgeBaseSyncConfig(daily_kb_path=tmp_path / "kb"),
        )


def test_load_daily_kb_config_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OBSIDIAN_DAILY_KB_SYNC_ENABLED", "true")
    monkeypatch.setenv("OBSIDIAN_DAILY_KB_PATH", str(tmp_path / "daily_notes"))

    config = load_daily_kb_config_from_env()

    assert config.sync_enabled is True
    assert config.daily_kb_path == tmp_path / "daily_notes"
