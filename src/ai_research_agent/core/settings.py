"""Settings placeholders for future configuration loading."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettings:
    """Minimal application settings shared across future modules."""

    app_env: str = "development"
    log_level: str = "INFO"
    profile_config_path: str = "config/profile.yaml"
    prompts_dir: str = "prompts"
    data_dir: str = "data"
