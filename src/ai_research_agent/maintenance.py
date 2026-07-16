"""Local maintenance helpers for cache and log cleanup."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class CleanupPolicy:
    """Retention windows for generated local artifacts."""

    logs_days: int = 30
    raw_articles_days: int = 90
    scored_articles_days: int = 90
    enriched_articles_days: int = 90
    quarantine_days: int = 90
    runs_days: int = 60
    delete_before_rerun_backups: bool = True


@dataclass
class CleanupResult:
    """Summary of a cleanup preview or execution."""

    dry_run: bool
    deleted_files: list[Path] = field(default_factory=list)
    deleted_dirs: list[Path] = field(default_factory=list)
    bytes_deleted: int = 0

    @property
    def total_items(self) -> int:
        """Return number of files and directories affected."""
        return len(self.deleted_files) + len(self.deleted_dirs)


def cleanup_generated_artifacts(
    project_root: Path = Path("."),
    policy: CleanupPolicy | None = None,
    dry_run: bool = True,
    now: datetime | None = None,
) -> CleanupResult:
    """Clean local generated artifacts without touching registry or final reports."""
    root = project_root.resolve()
    active_policy = policy or CleanupPolicy()
    current_time = now or datetime.now(UTC)
    result = CleanupResult(dry_run=dry_run)

    _collect_old_files(
        root / "logs",
        active_policy.logs_days,
        current_time,
        result,
        dry_run,
    )
    _collect_old_files(
        root / "data" / "raw_articles",
        active_policy.raw_articles_days,
        current_time,
        result,
        dry_run,
    )
    _collect_old_files(
        root / "data" / "scored_articles",
        active_policy.scored_articles_days,
        current_time,
        result,
        dry_run,
    )
    _collect_old_files(
        root / "data" / "quarantine",
        active_policy.quarantine_days,
        current_time,
        result,
        dry_run,
    )
    _collect_old_dirs(
        root / "data" / "runs",
        active_policy.runs_days,
        current_time,
        result,
        dry_run,
    )
    _collect_old_dirs(
        root / "data" / "enriched_articles",
        active_policy.enriched_articles_days,
        current_time,
        result,
        dry_run,
    )

    if active_policy.delete_before_rerun_backups:
        _collect_matching_files(
            root / "output" / "daily",
            "*.before-rerun.*",
            result,
            dry_run,
        )
    return result


def _collect_old_files(
    directory: Path,
    retention_days: int,
    now: datetime,
    result: CleanupResult,
    dry_run: bool,
) -> None:
    if not directory.exists():
        return
    cutoff = now - timedelta(days=max(0, retention_days))
    for path in sorted(directory.glob("*")):
        if path.is_file() and _modified_before(path, cutoff):
            _delete_file(path, result, dry_run)


def _collect_old_dirs(
    directory: Path,
    retention_days: int,
    now: datetime,
    result: CleanupResult,
    dry_run: bool,
) -> None:
    if not directory.exists():
        return
    cutoff = now - timedelta(days=max(0, retention_days))
    for path in sorted(directory.iterdir()):
        if path.is_dir() and _modified_before(path, cutoff):
            _delete_dir(path, result, dry_run)


def _collect_matching_files(
    directory: Path,
    pattern: str,
    result: CleanupResult,
    dry_run: bool,
) -> None:
    if not directory.exists():
        return
    for path in sorted(directory.glob(pattern)):
        if path.is_file():
            _delete_file(path, result, dry_run)


def _delete_file(path: Path, result: CleanupResult, dry_run: bool) -> None:
    size = path.stat().st_size
    result.deleted_files.append(path)
    result.bytes_deleted += size
    if not dry_run:
        path.unlink()


def _delete_dir(path: Path, result: CleanupResult, dry_run: bool) -> None:
    size = sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    result.deleted_dirs.append(path)
    result.bytes_deleted += size
    if not dry_run:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()


def _modified_before(path: Path, cutoff: datetime) -> bool:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return modified < cutoff
