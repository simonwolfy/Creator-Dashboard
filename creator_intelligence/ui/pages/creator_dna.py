from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.ui.pages.twitch import FrameModel


class CreatorDNAPage(QWidget):
    """Dashboard for the creator's local learning profile and next actions."""

    def __init__(self, service):
        super().__init__()
        self.service = service

        layout = QVBoxLayout(self)
        title = QLabel("Creator Intelligence")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "A local profile built from approved, rejected, and revised clip decisions."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        actions = QHBoxLayout()
        rebuild = QPushButton("Rebuild Creator DNA")
        rebuild.clicked.connect(self.rebuild)
        actions.addWidget(rebuild)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        complete = QPushButton("Mark recommendation complete")
        complete.clicked.connect(self.complete_selected)
        actions.addWidget(complete)
        actions.addStretch()
        layout.addLayout(actions)

        self.cards = QGroupBox("Creator DNA")
        card_layout = QGridLayout(self.cards)
        self.card_labels = {}
        card_names = [
            ("approved_clips", "Approved clips"),
            ("average_clip_length", "Average clip length"),
            ("average_hook", "Average hook"),
            ("average_emotion", "Average emotion"),
            ("average_humor", "Average humor"),
            ("average_viral", "Average viral"),
            ("average_retention", "Average retention"),
            ("preferred_title_style", "Preferred title style"),
            ("preferred_caption_style", "Preferred caption style"),
            ("packaging_confidence", "Packaging confidence"),
        ]
        for index, (key, label) in enumerate(card_names):
            box = QGroupBox(label)
            inner = QVBoxLayout(box)
            value = QLabel("—")
            value.setObjectName("metricValue")
            inner.addWidget(value)
            card_layout.addWidget(box, index // 5, index % 5)
            self.card_labels[key] = value
        layout.addWidget(self.cards)

        self.hashtags = QLabel("Top hashtags: Not enough data")
        self.hashtags.setWordWrap(True)
        layout.addWidget(self.hashtags)

        self.tabs = QTabWidget()
        self.recommendations = self._table()
        self.patterns_table = self._table()
        self.events = self._table()
        self.tabs.addTab(self.recommendations, "Recommendations")
        self.tabs.addTab(self.patterns_table, "Patterns")
        self.tabs.addTab(self.events, "Learning events")
        layout.addWidget(self.tabs, 1)

        self.refresh()

    @staticmethod
    def _table() -> QTableView:
        table = QTableView()
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        return table

    def refresh(self) -> None:
        profile = self.service.creator_dna()
        self._show_profile(profile)
        self.recommendations.setModel(FrameModel(self.service.recommendations()))
        self.patterns_table.setModel(FrameModel(self.service.patterns()))
        self.events.setModel(FrameModel(self.service.learning_events()))
        for table in (self.recommendations, self.patterns_table, self.events):
            table.resizeColumnsToContents()

    def rebuild(self) -> None:
        try:
            profile = self.service.rebuild_profile()
        except Exception as exc:
            QMessageBox.critical(self, "Creator DNA rebuild failed", str(exc))
            return
        self._show_profile(profile)
        self.refresh()
        QMessageBox.information(
            self,
            "Creator DNA rebuilt",
            f"Profile rebuilt from {profile.get('approved_clips', 0)} approved clip(s).",
        )

    def complete_selected(self) -> None:
        index = self.recommendations.currentIndex()
        model = self.recommendations.model()
        if not index.isValid() or model is None or not hasattr(model, "frame"):
            QMessageBox.information(
                self, "Recommendations", "Select a recommendation first."
            )
            return
        recommendation_id = int(model.frame.iloc[index.row()]["id"])
        self.service.complete_recommendation(recommendation_id)
        self.refresh()

    def _show_profile(self, profile) -> None:
        formats = {
            "average_clip_length": lambda v: f"{float(v or 0):.1f}s",
            "average_hook": lambda v: f"{float(v or 0):.1f}",
            "average_emotion": lambda v: f"{float(v or 0):.1f}",
            "average_humor": lambda v: f"{float(v or 0):.1f}",
            "average_viral": lambda v: f"{float(v or 0):.1f}",
            "average_retention": lambda v: f"{float(v or 0):.1f}%",
            "packaging_confidence": lambda v: f"{float(v or 0):.1f}%",
        }
        for key, label in self.card_labels.items():
            value = profile.get(key, 0 if key.startswith("average_") else "—")
            label.setText(formats.get(key, str)(value))
        tags = profile.get("favorite_hashtags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        self.hashtags.setText(
            "Top hashtags: " + (" ".join(tags) if tags else "Not enough data")
        )
