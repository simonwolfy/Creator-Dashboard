from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMenu,
    QTableView,
)

HEADER_LABELS = {
    "id": "ID",
    "url": "URL",
    "api": "API",
    "content_type": "Content type",
    "production_project_id": "Production project",
    "production_status": "Production status",
    "planned_publish_at": "Planned publish time",
    "scheduled_publish_at": "Scheduled publish time",
    "actual_publish_at": "Actual publish time",
    "description_status": "Description status",
    "thumbnail_status": "Thumbnail status",
    "metadata_status": "Metadata status",
    "upload_status": "Upload status",
}

MINIMUM_COLUMN_WIDTH = 100
MAXIMUM_COLUMN_WIDTH = 360
HEADER_HORIZONTAL_PADDING = 36


def friendly_header(value: object) -> str:
    raw = str(value or "").strip()
    key = raw.lower()
    if key in HEADER_LABELS:
        return HEADER_LABELS[key]
    words = re.sub(r"[_\-]+", " ", raw).strip()
    words = re.sub(r"\s+", " ", words)
    if not words:
        return ""
    return words[0].upper() + words[1:]


class TableEmptyState(QObject):
    """Show a helpful message in a table viewport when its model has no rows."""

    def __init__(self, table: QTableView, text: str):
        super().__init__(table)
        self.table = table
        self.label = QLabel(text, table.viewport())
        self.label.setObjectName("tableEmptyState")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        table.viewport().installEventFilter(self)
        self.update()

    def eventFilter(self, watched, event):
        table = getattr(self, "table", None)
        if table is None:
            return False
        try:
            if watched is table.viewport() and event.type() in {
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.Paint,
                QEvent.Type.LayoutRequest,
            }:
                self.update()
        except RuntimeError:
            return False
        return False

    def update(self) -> None:
        model = self.table.model()
        empty = model is None or model.rowCount() == 0
        self.label.setGeometry(self.table.viewport().rect().adjusted(24, 24, -24, -24))
        self.label.setVisible(empty and self.table.viewport().isVisible())
        if empty:
            self.label.raise_()


class ColumnVisibilityController(QObject):
    """Persist table column visibility and expose it from the header menu."""

    def __init__(
        self,
        table: QTableView,
        settings: QSettings,
        settings_key: str,
    ):
        super().__init__(table)
        self.table = table
        self.settings = settings
        self.settings_key = f"table_columns/{settings_key}/hidden"
        header = table.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_menu)
        header.sectionCountChanged.connect(lambda _old, _new: self.restore())
        header.setToolTip("Right-click a column heading to show or hide columns.")
        self.restore()

    def _header_label(self, column: int) -> str:
        model = self.table.model()
        if model is None:
            return str(column)
        value = model.headerData(
            column,
            Qt.Orientation.Horizontal,
            Qt.ItemDataRole.DisplayRole,
        )
        return str(value or column)

    def _hidden_labels(self) -> set[str]:
        values = self.settings.value(self.settings_key, [], list) or []
        return {str(value) for value in values}

    def restore(self) -> None:
        model = self.table.model()
        if model is None:
            return
        hidden = self._hidden_labels()
        labels = [self._header_label(column) for column in range(model.columnCount())]
        if labels and all(label in hidden for label in labels):
            hidden.discard(labels[0])
        for column in range(model.columnCount()):
            self.table.setColumnHidden(column, self._header_label(column) in hidden)

    def set_column_visible(self, column: int, visible: bool) -> None:
        model = self.table.model()
        if model is None or not 0 <= column < model.columnCount():
            return
        if not visible:
            visible_columns = sum(
                not self.table.isColumnHidden(index)
                for index in range(model.columnCount())
            )
            if visible_columns <= 1:
                return
        self.table.setColumnHidden(column, not visible)
        hidden = [
            self._header_label(index)
            for index in range(model.columnCount())
            if self.table.isColumnHidden(index)
        ]
        self.settings.setValue(self.settings_key, hidden)
        self.settings.sync()

    def _show_menu(self, position) -> None:
        model = self.table.model()
        if model is None or model.columnCount() == 0:
            return
        menu = QMenu(self.table)
        for column in range(model.columnCount()):
            action = menu.addAction(self._header_label(column))
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(column))
            action.toggled.connect(
                lambda visible, index=column: self.set_column_visible(index, visible)
            )
        menu.exec(self.table.horizontalHeader().mapToGlobal(position))


def configure_readable_table(
    table: QTableView,
    *,
    settings: QSettings | None = None,
    settings_key: str | None = None,
    empty_text: str = "No items yet.",
) -> None:
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.verticalHeader().setDefaultSectionSize(32)
    header = table.horizontalHeader()
    header.setMinimumHeight(38)
    header.setMinimumSectionSize(MINIMUM_COLUMN_WIDTH)
    header.setDefaultSectionSize(160)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setSectionsMovable(True)
    header.setStretchLastSection(False)
    resize_readable_columns(table)
    if not hasattr(table, "_empty_state"):
        table._empty_state = TableEmptyState(table, empty_text)
    if settings is not None and settings_key and not hasattr(
        table, "_column_visibility"
    ):
        table._column_visibility = ColumnVisibilityController(
            table, settings, settings_key
        )


def resize_readable_columns(table: QTableView) -> None:
    """Fit cell content without ever collapsing a visible header label."""
    model = table.model()
    if model is None:
        return
    table.resizeColumnsToContents()
    header = table.horizontalHeader()
    metrics = header.fontMetrics()
    for column in range(model.columnCount()):
        label = model.headerData(
            column,
            Qt.Orientation.Horizontal,
            Qt.ItemDataRole.DisplayRole,
        )
        label_width = metrics.horizontalAdvance(str(label or "")) + HEADER_HORIZONTAL_PADDING
        width = max(MINIMUM_COLUMN_WIDTH, label_width, table.columnWidth(column))
        table.setColumnWidth(column, min(width, MAXIMUM_COLUMN_WIDTH))
