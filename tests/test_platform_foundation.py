from __future__ import annotations

from pathlib import Path
import logging
import sqlite3

import pytest

from creator_intelligence.core.config import AppConfig, ConfigService
from creator_intelligence.core.lifecycle import ApplicationLifecycle
from creator_intelligence.core.logging import configure_logging
from creator_intelligence.core.settings import SettingsValidationError
from creator_intelligence.data.migration_manager import MigrationManager


def test_settings_are_versioned_and_round_trip(tmp_path: Path):
    service = ConfigService(tmp_path / "settings.json")
    expected = AppConfig(
        channel_name="Tester",
        backup_retention=7,
        theme="light",
        accent_color="#2563eb",
    )
    service.save(expected)
    loaded = service.load()
    assert loaded.channel_name == "Tester"
    assert loaded.backup_retention == 7
    assert loaded.theme == "light"
    assert loaded.accent_color == "#2563eb"
    assert '"schema_version": 1' in service.path.read_text(encoding="utf-8")


def test_invalid_settings_are_rejected(tmp_path: Path):
    service = ConfigService(tmp_path / "settings.json")
    with pytest.raises(SettingsValidationError):
        service.save(AppConfig(backup_retention=0))
    with pytest.raises(SettingsValidationError, match="accent_color"):
        service.save(AppConfig(accent_color="purple"))


def test_migrations_apply_once_and_report_history():
    connection = sqlite3.connect(":memory:")
    manager = MigrationManager(((1, "first", "CREATE TABLE example(id INTEGER);"),))
    assert len(manager.apply(connection)) == 1
    assert manager.apply(connection) == []
    assert manager.history(connection)[0].name == "first"
    assert manager.pending(connection) == []


def test_lifecycle_reports_duration():
    lifecycle = ApplicationLifecycle()
    lifecycle.add_startup_step("ready", lambda: "ok")
    report = lifecycle.start()
    assert report.duration_ms >= 0
    assert report.steps[0].duration_ms >= 0


def test_logging_configuration_is_idempotent_and_quiets_matplotlib(tmp_path: Path):
    configure_logging(tmp_path)
    configure_logging(tmp_path)
    managed = [
        handler for handler in logging.getLogger().handlers
        if getattr(handler, "creator_intelligence_managed", False)
    ]
    assert len(managed) == 2
    assert logging.getLogger("matplotlib.category").level == logging.WARNING
