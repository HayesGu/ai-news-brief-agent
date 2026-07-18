"""Command-line interface for AI Research Agent."""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from ai_research_agent.analysis.pipeline import analyze_article
from ai_research_agent.core.errors import ResearchAgentError
from ai_research_agent.ingestion.collector import collect_and_save_research_updates
from ai_research_agent.llm import create_llm_client
from ai_research_agent.llm.client import load_llm_config_from_env
from ai_research_agent.maintenance import CleanupPolicy, cleanup_generated_artifacts
from ai_research_agent.pipeline.daily import run_daily_pipeline
from ai_research_agent.reporting.obsidian import (
    load_daily_kb_config_from_env,
    sync_daily_report_to_knowledge_base,
)
from ai_research_agent.reporting.reports import save_markdown_report
from ai_research_agent.storage.article_registry import ArticleRegistry


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m ai_research_agent",
        description="Personal AI research intelligence tools.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze a local UTF-8 .txt or .md research article with an LLM provider.",
    )
    analyze_parser.add_argument("article_file", type=Path, help="Local .txt or .md article file")
    analyze_parser.add_argument(
        "--profile",
        type=Path,
        default=Path("config/profile.yaml"),
        help="Path to research profile YAML.",
    )
    analyze_parser.add_argument(
        "--prompt",
        type=Path,
        default=Path("prompts/research_analysis.md"),
        help="Path to Markdown analysis prompt.",
    )
    analyze_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/reports"),
        help="Directory where Markdown reports will be saved.",
    )

    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect frontier AI research updates from official sources.",
    )
    collect_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw_articles"),
        help="Directory where raw collected article JSON will be saved.",
    )

    daily_parser = subparsers.add_parser(
        "daily",
        help="Run the end-to-end three-day AI research briefing workflow.",
    )
    daily_parser.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to today's UTC date.",
    )
    daily_parser.add_argument(
        "--max-detailed",
        type=int,
        help="Override maximum number of detailed articles.",
    )
    daily_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Collect, score, and select articles without full analysis "
            "or final digest generation."
        ),
    )
    daily_parser.add_argument(
        "--explain-filtering",
        action="store_true",
        help="Print freshness, novelty, quarantine, and selection counts.",
    )
    daily_parser.add_argument(
        "--sync-daily-kb",
        action="store_true",
        help="Copy the generated three-day report to the configured daily knowledge base.",
    )
    daily_parser.add_argument(
        "--daily-kb-path",
        type=Path,
        help=r"Daily knowledge-base folder. Defaults to D:\path\to\your\obsidian\vault\01 Daily.",
    )

    registry_parser = subparsers.add_parser(
        "registry",
        help="Inspect or reset the local article registry.",
    )
    registry_subparsers = registry_parser.add_subparsers(dest="registry_command", required=True)
    registry_subparsers.add_parser("stats", help="Print article registry statistics.")
    reset_parser = registry_subparsers.add_parser("reset", help="Reset development registry state.")
    reset_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required confirmation for registry reset.",
    )
    bootstrap_reset_parser = registry_subparsers.add_parser(
        "bootstrap-reset",
        help="Clear processing state while keeping discovered article records.",
    )
    bootstrap_reset_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required confirmation for bootstrap reset.",
    )
    maintenance_parser = subparsers.add_parser(
        "maintenance",
        help="Inspect or clean local generated artifacts.",
    )
    maintenance_subparsers = maintenance_parser.add_subparsers(
        dest="maintenance_command",
        required=True,
    )
    cleanup_parser = maintenance_subparsers.add_parser(
        "cleanup",
        help="Preview or delete old logs and generated pipeline caches.",
    )
    cleanup_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete matching artifacts. Omit for dry-run preview.",
    )
    cleanup_parser.add_argument("--logs-days", type=int, default=30)
    cleanup_parser.add_argument("--raw-days", type=int, default=90)
    cleanup_parser.add_argument("--scored-days", type=int, default=90)
    cleanup_parser.add_argument("--enriched-days", type=int, default=90)
    cleanup_parser.add_argument("--quarantine-days", type=int, default=90)
    cleanup_parser.add_argument("--runs-days", type=int, default=60)
    cleanup_parser.add_argument(
        "--keep-rerun-backups",
        action="store_true",
        help="Keep output/daily/*.before-rerun.* backup files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)

    load_dotenv()

    try:
        if args.command == "analyze":
            client = create_llm_client(load_llm_config_from_env())
            result = analyze_article(
                article_path=args.article_file,
                client=client,
                profile_path=args.profile,
                prompt_path=args.prompt,
            )
            report_path = save_markdown_report(result, output_dir=args.output_dir)
            print(f"Report saved: {report_path}")
            return 0
        if args.command == "collect":
            articles = collect_and_save_research_updates(output_dir=args.output_dir)
            print(f"Collected {len(articles)} AI research updates.")
            return 0
        if args.command == "daily":
            from datetime import date

            target_date = date.fromisoformat(args.date) if args.date else None
            client = create_llm_client(load_llm_config_from_env())
            result = run_daily_pipeline(
                client=client,
                target_date=target_date,
                max_detailed=args.max_detailed,
                dry_run=args.dry_run,
                explain_filtering=args.explain_filtering,
            )
            if args.dry_run:
                print(
                    "Dry run complete: "
                    f"collected {len(result.collected_articles)}, "
                    f"scored {len(result.scored_articles)}, "
                    f"selected {len(result.selected_articles.all_selected)}."
                )
            else:
                print(f"Three-day report saved: {result.report_path}")
                kb_config = load_daily_kb_config_from_env(
                    daily_kb_path=args.daily_kb_path,
                    sync_enabled=True if args.sync_daily_kb else None,
                )
                if kb_config.sync_enabled and result.report_path is not None:
                    synced_path = sync_daily_report_to_knowledge_base(
                        result.report_path,
                        kb_config,
                    )
                    print(f"Daily knowledge base synced: {synced_path}")
            return 0
        if args.command == "registry":
            registry = ArticleRegistry()
            if args.registry_command == "stats":
                stats = registry.stats()
                print(f"total registered articles: {stats.total_registered_articles}")
                print("articles by source:")
                for source, count in sorted(stats.articles_by_source.items()):
                    print(f"  {source}: {count}")
                print(f"previously reported articles: {stats.previously_reported_articles}")
                print(f"quarantined articles: {stats.quarantined_articles}")
                print(f"material updates: {stats.material_updates}")
                return 0
            if args.registry_command == "reset":
                if not args.confirm:
                    parser.exit(status=1, message="Error: registry reset requires --confirm\n")
                registry.reset()
                print("Registry reset complete.")
                return 0
            if args.registry_command == "bootstrap-reset":
                if not args.confirm:
                    parser.exit(
                        status=1,
                        message="Error: registry bootstrap-reset requires --confirm\n",
                    )
                from ai_research_agent.pipeline.run_manifest import (
                    PipelineState,
                    load_pipeline_state,
                    save_pipeline_state,
                )

                registry.bootstrap_reset_processing_state()
                state = load_pipeline_state()
                state.previous_successful_run_at = None
                state.last_successful_run_id = None
                save_pipeline_state(
                    PipelineState(
                        previous_successful_run_at=state.previous_successful_run_at,
                        current_run_id=state.current_run_id,
                        last_successful_run_id=state.last_successful_run_id,
                        last_collected_count=state.last_collected_count,
                        last_fresh_count=state.last_fresh_count,
                        last_duplicate_count=state.last_duplicate_count,
                        last_quarantine_count=state.last_quarantine_count,
                        last_scored_count=state.last_scored_count,
                        last_selected_count=state.last_selected_count,
                    )
                )
                print("Registry bootstrap reset complete.")
                return 0
        if args.command == "maintenance":
            if args.maintenance_command == "cleanup":
                policy = CleanupPolicy(
                    logs_days=args.logs_days,
                    raw_articles_days=args.raw_days,
                    scored_articles_days=args.scored_days,
                    enriched_articles_days=args.enriched_days,
                    quarantine_days=args.quarantine_days,
                    runs_days=args.runs_days,
                    delete_before_rerun_backups=not args.keep_rerun_backups,
                )
                result = cleanup_generated_artifacts(
                    project_root=Path("."),
                    policy=policy,
                    dry_run=not args.confirm,
                )
                mode = "Dry run" if result.dry_run else "Cleanup"
                print(f"{mode} complete.")
                print(f"matched files: {len(result.deleted_files)}")
                print(f"matched directories: {len(result.deleted_dirs)}")
                print(f"bytes affected: {result.bytes_deleted}")
                for path in [*result.deleted_files, *result.deleted_dirs][:20]:
                    print(f"  {path}")
                if result.total_items > 20:
                    print(f"  ... and {result.total_items - 20} more")
                if result.dry_run:
                    print("No files were deleted. Re-run with --confirm to delete.")
                return 0
    except ResearchAgentError as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")

    parser.exit(status=1, message="Error: unknown command\n")


if __name__ == "__main__":
    raise SystemExit(main())

