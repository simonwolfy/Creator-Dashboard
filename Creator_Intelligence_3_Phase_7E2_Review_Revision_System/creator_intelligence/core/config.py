from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json
from creator_intelligence.utils.paths import CONFIG_DIR

@dataclass
class AppConfig:
    channel_name: str = "SimonWolfy"
    timezone: str = "America/Chicago"
    currency: str = "USD"
    theme: str = "dark"
    auto_backup_on_start: bool = True
    auto_backup_before_write: bool = True
    backup_retention: int = 30
    prediction_training_window_days: int = 0
    exclude_outliers: bool = False
    short_duration_threshold_seconds: int = 180

class ConfigService:
    def __init__(self, path: Path | None = None):
        self.path = path or (CONFIG_DIR / "settings.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppConfig:
        if not self.path.exists():
            config = AppConfig()
            self.save(config)
            return config
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            valid = {k: v for k, v in data.items() if k in AppConfig.__annotations__}
            return AppConfig(**valid)
        except Exception:
            config = AppConfig()
            self.save(config)
            return config

    def save(self, config: AppConfig):
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
        temp.replace(self.path)
