from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from creator_intelligence.core.config import AppConfig
from creator_intelligence.core.contracts import ModuleMetadata, NavigationItem
from creator_intelligence.ui.main_window import (
    NAVIGATION_GROUP_ORDER,
    NAVIGATION_LABEL_GROUPS,
    MainWindow,
)
from creator_intelligence.ui.pages.goals import GoalsPage
from creator_intelligence.ui.table_utils import friendly_header
from creator_intelligence.ui.theme import (
    DEFAULT_ACCENT,
    build_stylesheet,
    is_valid_accent,
    normalize_accent,
)


def test_table_headers_are_human_readable():
    assert friendly_header("id") == "ID"
    assert friendly_header("content_type") == "Content type"
    assert friendly_header("planned_publish_at") == "Planned publish time"
    assert friendly_header("average_viewers") == "Average viewers"


def test_light_and_dark_styles_use_selected_accent():
    light = build_stylesheet("light", "#2563eb")
    dark = build_stylesheet("dark", "#059669")
    assert "#f4f6fb" in light
    assert "#2563eb" in light
    assert "#0d1018" in dark
    assert "#059669" in dark


def test_invalid_accent_falls_back_to_creator_purple():
    assert is_valid_accent("#a1B2c3") is True
    assert is_valid_accent("purple") is False
    assert normalize_accent("not-a-color") == DEFAULT_ACCENT


def test_navigation_uses_compact_top_level_groups():
    assert NAVIGATION_GROUP_ORDER == (
        "Overview",
        "Platforms",
        "Content",
        "Intelligence",
        "Production",
        "System",
    )
    assert NAVIGATION_LABEL_GROUPS["Twitch"] == "Platforms"
    assert NAVIGATION_LABEL_GROUPS["Transcripts"] == "Content"
    assert NAVIGATION_LABEL_GROUPS["Creator Intelligence"] == "Intelligence"
    assert NAVIGATION_LABEL_GROUPS["Publishing"] == "Production"
    assert NAVIGATION_LABEL_GROUPS["Settings"] == "System"


def test_main_window_builds_nested_navigation(tmp_path):
    app = QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    class Registry:
        modules = {
            "analytics": ModuleMetadata("analytics", "Analytics", "1", "analytics"),
            "system": ModuleMetadata("system", "System", "1", "system"),
        }
        failures = []

        @staticmethod
        def build_navigation():
            return [
                NavigationItem("Home", QWidget, order=1, module_id="analytics"),
                NavigationItem("Twitch", QWidget, order=2, module_id="analytics"),
                NavigationItem("Settings", QWidget, order=3, module_id="system"),
            ]

        @staticmethod
        def emit(_event):
            return []

    runtime = SimpleNamespace(
        db=None,
        context=SimpleNamespace(services={}),
        registry=Registry(),
        settings=AppConfig(auto_check_updates=False),
        workspace=SimpleNamespace(paths=SimpleNamespace(root=tmp_path)),
        health_checks=[],
    )
    window = MainWindow(runtime)
    groups = [
        window.nav.topLevelItem(index).text(0)
        for index in range(window.nav.topLevelItemCount())
    ]
    assert groups == ["Overview", "Platforms", "System"]
    assert window.nav.topLevelItem(0).child(0).text(0) == "Home"
    window.close()
    app.processEvents()


def test_theme_switch_can_repolish_goals_page():
    app = QApplication.instance() or QApplication([])

    class EmptyDB:
        @staticmethod
        def frame(_query):
            return pd.DataFrame(columns=["period", "metric", "target", "platform"])

    window = QMainWindow()
    page = GoalsPage(EmptyDB())
    window.setCentralWidget(page)
    window.setStyleSheet(build_stylesheet("dark", DEFAULT_ACCENT))
    window.setStyleSheet(build_stylesheet("light", "#2563eb"))
    assert page.metric_selector.currentText() == "average_viewers"
    window.close()
    app.processEvents()
