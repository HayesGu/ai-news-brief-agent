"""End-to-end workflow orchestration."""

__all__ = ["DailyPipeline", "run_daily_pipeline"]


def __getattr__(name: str) -> object:
    if name in __all__:
        from ai_research_agent.pipeline.daily import DailyPipeline, run_daily_pipeline

        return {
            "DailyPipeline": DailyPipeline,
            "run_daily_pipeline": run_daily_pipeline,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
