from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from creator_intelligence.core.settings import SettingsManager
from creator_intelligence.utils.paths import CONFIG_DIR


@dataclass
class AppConfig:
    channel_name: str = "My Channel"
    timezone: str = "America/Chicago"
    currency: str = "USD"
    theme: str = "dark"
    accent_color: str = "#7137c8"
    auto_backup_on_start: bool = True
    auto_backup_before_write: bool = True
    backup_retention: int = 30
    prediction_training_window_days: int = 0
    exclude_outliers: bool = False
    short_duration_threshold_seconds: int = 180
    auto_check_updates: bool = True
    update_channel: str = "stable"


class ConfigService:
    """Compatibility facade over the workspace SettingsManager."""

    def __init__(self, path: Path | None = None):
        self.path = path or (CONFIG_DIR / "settings.json")
        self.manager = SettingsManager(self.path, AppConfig)

    def load(self) -> AppConfig:
        return self.manager.load()

    def save(self, config: AppConfig) -> None:
        self.manager.save(config)

    def export(self, destination: Path, config: AppConfig) -> Path:
        return self.manager.export(destination, config)
