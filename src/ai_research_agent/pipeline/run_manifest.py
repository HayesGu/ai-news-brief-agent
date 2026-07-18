"""Run state and manifest persistence for briefing workflows."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

STATE_PATH = Path("data/state/pipeline_state.json")
RUNS_DIR = Path("data/runs")


@dataclass
class PipelineState:
    """Persistent state updated only after successful runs."""

    previous_successful_run_at: str | None = None
    current_run_id: str | None = None
    last_successful_run_id: str | None = None
    last_collected_count: int = 0
    last_fresh_count: int = 0
    last_duplicate_count: int = 0
    last_quarantine_count: int = 0
    last_scored_count: int = 0
    last_selected_count: int = 0


@dataclass
class RunManifest:
    """Audit manifest for one daily run."""

    run_id: str
    started_at: str
    completed_at: str | None
    requested_report_date: str
    previous_successful_run_at: str | None
    collected_article_ids: list[str] = field(default_factory=list)
    fresh_article_ids: list[str] = field(default_factory=list)
    duplicate_article_ids: list[str] = field(default_factory=list)
    historical_article_ids: list[str] = field(default_factory=list)
    quarantined_article_ids: list[str] = field(default_factory=list)
    scored_article_ids: list[str] = field(default_factory=list)
    selected_article_ids: list[str] = field(default_factory=list)
    material_update_article_ids: list[str] = field(default_factory=list)
    excluded_reasons: dict[str, str] = field(default_factory=dict)
    configuration_snapshot: dict[str, Any] = field(default_factory=dict)


def new_run_id(target_date: date) -> str:
    """Create an opaque run id."""
    return f"{target_date.isoformat()}-{uuid.uuid4().hex[:8]}"


def utc_now_iso() -> str:
    """Return current UTC timestamp."""
    return datetime.now(UTC).isoformat()


def load_pipeline_state(path: Path = STATE_PATH) -> PipelineState:
    """Load persistent pipeline state."""
    if not path.exists():
        return PipelineState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return PipelineState(**data)


def save_pipeline_state(state: PipelineState, path: Path = STATE_PATH) -> Path:
    """Save persistent pipeline state as UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_run_manifest(manifest: RunManifest, runs_dir: Path = RUNS_DIR) -> Path:
    """Save one run manifest."""
    path = runs_dir / manifest.run_id / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
