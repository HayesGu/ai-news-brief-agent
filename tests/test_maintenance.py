from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_research_agent.maintenance import CleanupPolicy, cleanup_generated_artifacts


def test_cleanup_dry_run_does_not_delete_files(tmp_path: Path) -> None:
    old_log = _file(tmp_path / "logs" / "old.log", days_old=40)
    state = _file(tmp_path / "data" / "state" / "article_registry.sqlite3", days_old=400)

    result = cleanup_generated_artifacts(
        project_root=tmp_path,
        policy=CleanupPolicy(logs_days=30),
        dry_run=True,
        now=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert old_log in result.deleted_files
    assert old_log.exists()
    assert state.exists()
    assert state not in result.deleted_files


def test_cleanup_confirm_deletes_old_generated_artifacts(tmp_path: Path) -> None:
    old_log = _file(tmp_path / "logs" / "old.log", days_old=40)
    new_log = _file(tmp_path / "logs" / "new.log", days_old=2)
    backup = _file(tmp_path / "output" / "daily" / "2026-07-15_AI.before-rerun.md", days_old=1)
    run_dir = tmp_path / "data" / "runs" / "old-run"
    old_manifest = _file(run_dir / "manifest.json", days_old=90)
    _touch(run_dir, days_old=90)
    state = _file(tmp_path / "data" / "state" / "pipeline_state.json", days_old=90)

    result = cleanup_generated_artifacts(
        project_root=tmp_path,
        policy=CleanupPolicy(logs_days=30, runs_days=60),
        dry_run=False,
        now=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert old_log in result.deleted_files
    assert backup in result.deleted_files
    assert run_dir in result.deleted_dirs
    assert not old_log.exists()
    assert not backup.exists()
    assert not old_manifest.exists()
    assert new_log.exists()
    assert state.exists()


def test_cleanup_can_keep_before_rerun_backups(tmp_path: Path) -> None:
    backup = _file(tmp_path / "output" / "daily" / "2026-07-15_AI.before-rerun.md", days_old=1)

    result = cleanup_generated_artifacts(
        project_root=tmp_path,
        policy=CleanupPolicy(delete_before_rerun_backups=False),
        dry_run=False,
        now=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert backup.exists()
    assert backup not in result.deleted_files


def _file(path: Path, days_old: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    _touch(path, days_old=days_old)
    return path


def _touch(path: Path, days_old: int) -> None:
    timestamp = (datetime(2026, 7, 16, tzinfo=UTC) - timedelta(days=days_old)).timestamp()
    path.touch(exist_ok=True)
    os.utime(path, (timestamp, timestamp))
