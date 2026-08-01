from __future__ import annotations
import json
import pandas as pd
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,
    QAbstractItemView,QMessageBox,QInputDialog,QPlainTextEdit
)
from creator_intelligence.ui.pages.twitch import FrameModel

class HighlightLearningPage(QWidget):
    def __init__(self,service):
        super().__init__()
        self.service=service
        layout=QVBoxLayout(self)
        title=QLabel("Highlight Learning Engine")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        row=QHBoxLayout()
        actions=[
            ("Add approval feedback",lambda:self.review_feedback(True)),
            ("Add rejection feedback",lambda:self.review_feedback(False)),
            ("Add performance result",self.performance_feedback),
            ("Train personalized model",self.train),
            ("Personalize all highlights",self.personalize_all),
            ("Refresh",self.refresh)
        ]
        for label,handler in actions:
            button=QPushButton(label)
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)

        self.summary=QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(180)
        layout.addWidget(self.summary)

        self.highlights=QTableView()
        self.highlights.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.highlights)

        self.personalized=QTableView()
        layout.addWidget(self.personalized)

        self.weights=QTableView()
        layout.addWidget(self.weights)

        self.refresh()

    def selected_highlight_id(self):
        index=self.highlights.currentIndex()
        if not index.isValid():
            return None
        return int(self.highlights.model().frame.iloc[index.row()]["id"])

    def refresh(self):
        self.highlights.setModel(
            FrameModel(self.service.scoring_service.highlights())
        )
        self.personalized.setModel(
            FrameModel(self.service.personalized_scores())
        )
        self.weights.setModel(FrameModel(self.service.weights()))
        self.summary.setPlainText(
            json.dumps(self.service.insights(),indent=2,default=str)
        )

    def review_feedback(self,approved):
        highlight_id=self.selected_highlight_id()
        if not highlight_id:
            return
        notes,ok=QInputDialog.getMultiLineText(
            self,"Feedback","Why was this highlight accepted or rejected?"
        )
        if ok:
            self.service.add_review_feedback(
                highlight_id,approved,notes=notes or None
            )
            self.refresh()

    def performance_feedback(self):
        highlight_id=self.selected_highlight_id()
        if not highlight_id:
            return
        views,ok=QInputDialog.getDouble(
            self,"Published performance","Views",1000,0,1_000_000_000,0
        )
        if not ok: return
        retention,ok=QInputDialog.getDouble(
            self,"Published performance","Retention rate (0–1)",
            0.6,0,1,3
        )
        if not ok: return
        engagement,ok=QInputDialog.getDouble(
            self,"Published performance","Engagement rate (0–1)",
            0.08,0,1,3
        )
        if ok:
            self.service.add_performance_feedback(
                highlight_id,views=views,
                retention_rate=retention,
                engagement_rate=engagement,
                published=True
            )
            self.refresh()

    def train(self):
        try:
            metrics=self.service.train()
            QMessageBox.information(
                self,"Training complete",
                json.dumps(metrics,indent=2)
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self,"Cannot train",str(exc))

    def personalize_all(self):
        rows=self.service.personalize_all()
        QMessageBox.information(
            self,"Personalized scores",
            f"{len(rows)} highlights were rescored."
        )
        self.refresh()
