from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from creator_intelligence.ui.table_utils import resize_readable_columns


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "0"):
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: int | str) -> None:
        self.value_label.setText(str(value))


class CreatorDashboardPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service

        outer = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Creator Dashboard")
        title.setObjectName("pageTitle")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        cards = QGridLayout()
        self.total_card = MetricCard("All content")
        self.vod_card = MetricCard("VODs")
        self.video_card = MetricCard("Videos")
        self.short_card = MetricCard("Shorts")
        self.clip_card = MetricCard("Clips")
        for index, card in enumerate(
            (self.total_card, self.vod_card, self.video_card, self.short_card, self.clip_card)
        ):
            cards.addWidget(card, 0, index)
        self.body_layout.addLayout(cards)

        self.queue_table = self._table(
            "Today's Work Queue",
            ["Title", "Type", "Platform", "Status", "Editor", "Due / Updated"],
        )
        self.recent_table = self._table(
            "Recent Activity",
            ["Title", "Type", "Platform", "Status", "Updated"],
        )
        self.upcoming_table = self._table(
            "Upcoming Publications",
            ["Title", "Type", "Platform", "Status", "Scheduled"],
        )
        self.body_layout.addStretch()
        self.refresh()

    def _table(self, heading: str, columns: list[str]) -> QTableWidget:
        label = QLabel(heading)
        label.setStyleSheet("font-size:18px;font-weight:700;padding-top:12px;")
        self.body_layout.addWidget(label)
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(190)
        self.body_layout.addWidget(table)
        return table

    def refresh(self) -> None:
        snapshot = self.service.snapshot()
        self.total_card.set_value(snapshot.total_content)
        self.vod_card.set_value(self._type_count(snapshot.counts_by_type, "vod"))
        self.video_card.set_value(self._type_count(snapshot.counts_by_type, "video", "long-form"))
        self.short_card.set_value(self._type_count(snapshot.counts_by_type, "short"))
        self.clip_card.set_value(self._type_count(snapshot.counts_by_type, "clip"))

        self._fill(
            self.queue_table,
            snapshot.work_queue,
            ("title", "content_type", "platform", "status", "editor", "due_at"),
        )
        self._fill(
            self.recent_table,
            snapshot.recent_activity,
            ("title", "content_type", "platform", "status", "updated_at"),
        )
        self._fill(
            self.upcoming_table,
            snapshot.upcoming,
            ("title", "content_type", "platform", "status", "published_at"),
        )

    @staticmethod
    def _type_count(counts: dict[str, int], *tokens: str) -> int:
        total = 0
        for label, count in counts.items():
            normalized = label.casefold()
            if any(token in normalized for token in tokens):
                total += count
        return total

    @staticmethod
    def _fill(table: QTableWidget, rows: list[dict], keys: tuple[str, ...]) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, key in enumerate(keys):
                value = row.get(key)
                item = QTableWidgetItem("" if value is None else str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row_index, column_index, item)
        resize_readable_columns(table)
