from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
import json
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


class SettingsValidationError(ValueError):
    pass


class SettingsManager:
    """Atomic, versioned settings storage for one workspace."""

    CURRENT_VERSION = 1

    def __init__(self, path: Path, model: type[T]):
        self.path = Path(path)
        self.model = model
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not is_dataclass(model):
            raise TypeError("Settings model must be a dataclass type.")

    def load(self) -> T:
        if not self.path.exists():
            value = self.model()
            self.save(value)
            return value
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            data = payload.get("settings", payload)
            allowed = {field.name for field in fields(self.model)}
            value = self.model(**{key: val for key, val in data.items() if key in allowed})
            self.validate(value)
            return value
        except Exception as exc:
            raise SettingsValidationError(f"Invalid settings file {self.path}: {exc}") from exc

    def save(self, value: T) -> None:
        self.validate(value)
        payload = {
            "schema_version": self.CURRENT_VERSION,
            "settings": asdict(value),
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)

    def export(self, destination: Path, value: T) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(asdict(value), indent=2, sort_keys=True), encoding="utf-8")
        return destination

    def validate(self, value: T) -> None:
        if hasattr(value, "backup_retention") and value.backup_retention < 1:
            raise SettingsValidationError("backup_retention must be at least 1.")
        if hasattr(value, "short_duration_threshold_seconds") and value.short_duration_threshold_seconds < 1:
            raise SettingsValidationError("short_duration_threshold_seconds must be positive.")
        if hasattr(value, "theme") and value.theme not in {"dark", "light", "system"}:
            raise SettingsValidationError("theme must be dark, light, or system.")
        if hasattr(value, "currency") and len(str(value.currency)) != 3:
            raise SettingsValidationError("currency must be a three-letter code.")

    def get(self, value: T, key: str, default: Any = None) -> Any:
        return getattr(value, key, default)
