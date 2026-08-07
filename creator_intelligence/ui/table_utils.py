from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

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


def configure_readable_table(table: QTableView) -> None:
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
