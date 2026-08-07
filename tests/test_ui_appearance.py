from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMainWindow,
    QTableWidget,
    QTreeWidgetItem,
    QWidget,
)

from creator_intelligence.core.config import AppConfig
from creator_intelligence.core.contracts import ModuleMetadata, NavigationItem
from creator_intelligence.ui.main_window import (
    HierarchicalNavigation,
    NAVIGATION_GROUP_ORDER,
    NAVIGATION_LABEL_GROUPS,
    MainWindow,
)
from creator_intelligence.ui.pages.goals import GoalsPage
from creator_intelligence.ui.table_utils import (
    MINIMUM_COLUMN_WIDTH,
    configure_readable_table,
    friendly_header,
    resize_readable_columns,
)
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


def test_empty_tables_keep_readable_header_widths():
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(0, 6)
    table.setHorizontalHeaderLabels(
        ["Title", "Type", "Platform", "Status", "Editor", "Due / Updated"]
    )
    table.resizeColumnsToContents()

    configure_readable_table(table)

    assert all(
        table.columnWidth(column) >= MINIMUM_COLUMN_WIDTH
        for column in range(table.columnCount())
    )
    due_width = table.horizontalHeader().fontMetrics().horizontalAdvance("Due / Updated")
    assert table.columnWidth(5) > due_width
    table.close()
    app.processEvents()


def test_readable_widths_are_restored_after_a_refresh_resize():
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(0, 2)
    table.setHorizontalHeaderLabels(["Title", "Scheduled publish time"])
    configure_readable_table(table)
    table.setColumnWidth(0, 20)
    table.setColumnWidth(1, 20)

    resize_readable_columns(table)

    assert table.columnWidth(0) >= MINIMUM_COLUMN_WIDTH
    assert table.columnWidth(1) > table.horizontalHeader().fontMetrics().horizontalAdvance(
        "Scheduled publish time"
    )
    table.close()
    app.processEvents()


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
    ui_settings = QSettings(
        str(tmp_path / "creator-os.ini"),
        QSettings.Format.IniFormat,
    )

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
                NavigationItem("YouTube", QWidget, order=3, module_id="analytics"),
                NavigationItem("Settings", QWidget, order=4, module_id="system"),
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
        ui_settings=ui_settings,
    )
    window = MainWindow(runtime)
    groups = [
        window.nav.topLevelItem(index).text(0)
        for index in range(window.nav.topLevelItemCount())
    ]
    assert groups == ["Overview", "Platforms", "System"]
    assert window.nav.topLevelItem(0).child(0).text(0) == "Home"
    assert window.nav.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove

    system_group = window.nav.takeTopLevelItem(2)
    window.nav.insertTopLevelItem(0, system_group)
    platforms_group = window.nav.topLevelItem(2)
    youtube_item = platforms_group.takeChild(1)
    platforms_group.insertChild(0, youtube_item)
    window._navigation_reordered()
    window.close()
    app.processEvents()

    restored = MainWindow(runtime)
    restored_groups = [
        restored.nav.topLevelItem(index).text(0)
        for index in range(restored.nav.topLevelItemCount())
    ]
    assert restored_groups == ["System", "Overview", "Platforms"]
    restored_platforms = restored.nav.topLevelItem(2)
    assert [
        restored_platforms.child(index).text(0)
        for index in range(restored_platforms.childCount())
    ] == ["YouTube", "Twitch"]
    restored.close()
    app.processEvents()


def test_navigation_drop_destinations_keep_items_in_scope():
    app = QApplication.instance() or QApplication([])
    navigation = HierarchicalNavigation()
    first_group = QTreeWidgetItem(["First"])
    second_group = QTreeWidgetItem(["Second"])
    first_tab = QTreeWidgetItem(["First tab"])
    second_tab = QTreeWidgetItem(["Second tab"])
    other_tab = QTreeWidgetItem(["Other tab"])
    first_group.addChildren([first_tab, second_tab])
    second_group.addChild(other_tab)
    navigation.addTopLevelItems([first_group, second_group])

    above = QAbstractItemView.DropIndicatorPosition.AboveItem
    below = QAbstractItemView.DropIndicatorPosition.BelowItem
    on_item = QAbstractItemView.DropIndicatorPosition.OnItem

    assert navigation.drop_destination(first_group, second_group, below) == (None, 2)
    assert navigation.drop_destination(first_tab, second_tab, below) == (first_group, 2)
    assert navigation.drop_destination(first_tab, first_group, on_item) == (first_group, 2)
    assert navigation.drop_destination(first_tab, second_group, on_item) is None
    assert navigation.drop_destination(first_group, first_tab, above) is None
    navigation.close()
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
