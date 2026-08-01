from __future__ import annotations
import json
import pandas as pd
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QTabWidget,
    QAbstractItemView,QMessageBox,QInputDialog,QFileDialog,QPlainTextEdit
)
from creator_intelligence.ui.pages.twitch import FrameModel

class SceneIntelligencePage(QWidget):
    def __init__(self,service):
        super().__init__()
        self.service=service
        layout=QVBoxLayout(self)
        title=QLabel("Scene and Chapter Intelligence")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        controls=QHBoxLayout()
        actions=[
            ("Analyze transcript",self.analyze),
            ("Detect silence",self.detect_silence),
            ("Rebuild timeline",self.rebuild_timeline),
            ("Refresh",self.refresh)
        ]
        for label,handler in actions:
            button=QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)

        self.summary=QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(180)
        layout.addWidget(self.summary)

        self.tabs=QTabWidget()
        self.transcripts_table=QTableView()
        self.transcripts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.transcripts_table,"Transcripts")
        self.scenes_table=QTableView()
        self.tabs.addTab(self.scenes_table,"Scenes")
        self.low_table=QTableView()
        self.tabs.addTab(self.low_table,"Low-value intervals")
        self.silence_table=QTableView()
        self.tabs.addTab(self.silence_table,"Silence")
        self.timeline_table=QTableView()
        self.tabs.addTab(self.timeline_table,"Unified timeline")
        self.jobs_table=QTableView()
        self.tabs.addTab(self.jobs_table,"Analysis jobs")
        layout.addWidget(self.tabs)

        self.transcripts_table.clicked.connect(lambda _:self.refresh_details())
        self.refresh()

    def selected_transcript_id(self):
        index=self.transcripts_table.currentIndex()
        if not index.isValid():
            return None
        return int(self.transcripts_table.model().frame.iloc[index.row()]["id"])

    def selected_media_asset_id(self):
        transcript_id=self.selected_transcript_id()
        if not transcript_id:
            return None
        transcript=self.service.transcript_service.transcript(transcript_id)
        value=transcript.get("media_asset_id")
        return int(value) if value is not None and not pd.isna(value) else None

    def refresh(self):
        self.transcripts_table.setModel(
            FrameModel(self.service.transcript_service.transcripts())
        )
        self.jobs_table.setModel(FrameModel(self.service.jobs()))
        self.refresh_details()

    def refresh_details(self):
        transcript_id=self.selected_transcript_id()
        if not transcript_id:
            blank=FrameModel(pd.DataFrame())
            self.scenes_table.setModel(blank)
            self.low_table.setModel(FrameModel(pd.DataFrame()))
            self.timeline_table.setModel(FrameModel(pd.DataFrame()))
            self.silence_table.setModel(FrameModel(pd.DataFrame()))
            self.summary.setPlainText("Select a transcript.")
            return
        media_asset_id=self.selected_media_asset_id()
        self.scenes_table.setModel(
            FrameModel(self.service.scene_segments(transcript_id))
        )
        self.low_table.setModel(
            FrameModel(self.service.low_value_intervals(
                transcript_id=transcript_id
            ))
        )
        self.timeline_table.setModel(
            FrameModel(self.service.timeline(transcript_id))
        )
        self.silence_table.setModel(
            FrameModel(
                self.service.silence_intervals(media_asset_id)
                if media_asset_id else pd.DataFrame()
            )
        )
        summary=self.service.editor_summary(transcript_id)
        self.summary.setPlainText(
            json.dumps(summary,indent=2,default=str)
        )

    def analyze(self):
        transcript_id=self.selected_transcript_id()
        if not transcript_id:
            return
        minutes,ok=QInputDialog.getInt(
            self,"Scene target","Target scene length in minutes",
            12,5,60
        )
        if not ok:
            return
        try:
            scenes=self.service.analyze(
                transcript_id,
                self.selected_media_asset_id(),
                target_segment_minutes=minutes
            )
            QMessageBox.information(
                self,"Analysis complete",
                f"{len(scenes)} scene sections were created."
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self,"Analysis failed",str(exc))

    def detect_silence(self):
        media_asset_id=self.selected_media_asset_id()
        if not media_asset_id:
            QMessageBox.warning(
                self,"No media asset",
                "This transcript is not linked to a Video Processing media asset."
            )
            return
        try:
            intervals=self.service.detect_silence(media_asset_id)
            QMessageBox.information(
                self,"Silence detection",
                f"{len(intervals)} silence intervals were detected."
            )
            self.refresh_details()
        except Exception as exc:
            QMessageBox.critical(self,"Silence detection failed",str(exc))

    def rebuild_timeline(self):
        transcript_id=self.selected_transcript_id()
        if transcript_id:
            self.service.rebuild_timeline(
                transcript_id,self.selected_media_asset_id()
            )
            self.refresh_details()
