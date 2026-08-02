from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.ui.pages.twitch import FrameModel


class JobWorker(QThread):
    completed = Signal(int)
    failed = Signal(str)

    def __init__(self, service, job_id):
        super().__init__()
        self.service = service
        self.job_id = job_id

    def run(self):
        try:
            self.service.run_job(self.job_id)
            self.completed.emit(self.job_id)
        except Exception as exc:
            self.failed.emit(str(exc))


class TranscriptsPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.worker = None

        layout = QVBoxLayout(self)
        title = QLabel("Transcript Engine")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        status = self.service.engine_status()
        self.engine_label = QLabel(status.message)
        self.engine_label.setWordWrap(True)
        layout.addWidget(self.engine_label)

        controls = QHBoxLayout()
        actions = [
            ("Import transcript", self.import_transcript),
            ("Queue transcription", self.queue_transcription),
            ("Run selected job", self.run_job),
            ("Cancel selected job", self.cancel_job),
            ("Build chapters", self.build_chapters),
            ("Export SRT", self.export_srt),
            ("Refresh", self.refresh),
        ]
        for label, handler in actions:
            button = QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)

        search_row = QHBoxLayout()
        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("Search every transcript…")
        self.search_text.returnPressed.connect(self.search)
        search_button = QPushButton("Search")
        search_button.clicked.connect(self.search)
        search_row.addWidget(self.search_text)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        self.action_status = QLabel("Ready")
        self.action_status.setWordWrap(True)
        layout.addWidget(self.action_status)

        self.tabs = QTabWidget()
        self.transcripts_table = QTableView()
        self.transcripts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.transcripts_table, "Transcripts")

        self.segments_table = QTableView()
        self.segments_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.segments_table, "Selected transcript")

        self.search_table = QTableView()
        self.search_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.search_table, "Search results")

        self.chapters_table = QTableView()
        self.chapters_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.chapters_table, "Chapters")

        self.jobs_table = QTableView()
        self.jobs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.jobs_table, "Jobs")
        layout.addWidget(self.tabs)

        self.transcripts_table.clicked.connect(lambda _: self.refresh_details())
        self.refresh()

    def selected_transcript_id(self):
        index = self.transcripts_table.currentIndex()
        if not index.isValid():
            return None
        return int(self.transcripts_table.model().frame.iloc[index.row()]["id"])

    def selected_job_id(self):
        index = self.jobs_table.currentIndex()
        if not index.isValid():
            return None
        return int(self.jobs_table.model().frame.iloc[index.row()]["id"])

    def refresh(self):
        selected_transcript = self.selected_transcript_id()
        selected_job = self.selected_job_id()

        transcripts = self.service.transcripts()
        transcript_model = FrameModel(transcripts)
        self.transcripts_table.setModel(transcript_model)
        if not transcripts.empty:
            row = 0
            if selected_transcript is not None:
                matches = transcripts.index[
                    transcripts["id"] == selected_transcript
                ].tolist()
                if matches:
                    row = int(matches[0])
            self.transcripts_table.selectRow(row)
            self.transcripts_table.setCurrentIndex(transcript_model.index(row, 0))

        jobs = self.service.jobs()
        jobs_model = FrameModel(jobs)
        self.jobs_table.setModel(jobs_model)
        if not jobs.empty:
            row = 0
            if selected_job is not None:
                matches = jobs.index[jobs["id"] == selected_job].tolist()
                if matches:
                    row = int(matches[0])
            self.jobs_table.selectRow(row)
            self.jobs_table.setCurrentIndex(jobs_model.index(row, 0))

        self.refresh_details()

    def refresh_details(self):
        transcript_id = self.selected_transcript_id()
        if not transcript_id:
            self.segments_table.setModel(FrameModel(pd.DataFrame()))
            self.chapters_table.setModel(FrameModel(pd.DataFrame()))
            return

        segments = self.service.segments(transcript_id)
        chapters = self.service.chapters(transcript_id)
        self.segments_table.setModel(FrameModel(segments))
        self.chapters_table.setModel(FrameModel(chapters))
        self._stretch_column(self.segments_table, segments, "text")
        self._stretch_column(self.chapters_table, chapters, "summary")

    @staticmethod
    def _stretch_column(table, frame, column_name):
        if frame.empty or column_name not in frame.columns:
            return
        column = int(frame.columns.get_loc(column_name))
        table.horizontalHeader().setSectionResizeMode(
            column, QHeaderView.ResizeMode.Stretch
        )

    def import_transcript(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import transcript",
            "",
            "Transcripts (*.srt *.vtt *.json *.txt *.md)",
        )
        if not path:
            return
        try:
            transcript = self.service.import_file(path)
            QMessageBox.information(
                self,
                "Transcript imported",
                f'{transcript["segment_count"]} segments are now searchable.',
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))

    def queue_transcription(self):
        if not self.service.video_processing:
            QMessageBox.warning(
                self, "Unavailable", "Video Processing is not connected."
            )
            return
        assets = self.service.video_processing.assets()
        if assets.empty:
            QMessageBox.warning(
                self, "No media assets", "Import a VOD in Video Processing first."
            )
            return
        labels = [
            f'{row["display_name"]} [asset {int(row["id"])}]'
            for _, row in assets.iterrows()
        ]
        label, ok = QInputDialog.getItem(
            self, "Choose VOD", "Media asset", labels, 0, False
        )
        if not ok:
            return
        index = labels.index(label)
        asset_id = int(assets.iloc[index]["id"])
        model, ok = QInputDialog.getItem(
            self,
            "Whisper model",
            "Model",
            ["tiny", "base", "small", "medium", "large"],
            1,
            False,
        )
        if ok:
            job_id = self.service.queue_transcription(asset_id, model_name=model)
            QMessageBox.information(
                self, "Transcription queued", f"Job {job_id} was queued."
            )
            self.refresh()

    def run_job(self):
        job_id = self.selected_job_id()
        if not job_id:
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(
                self, "Job running", "Wait for the current job to finish."
            )
            return
        self.worker = JobWorker(self.service, job_id)
        self.worker.completed.connect(lambda _: self.refresh())
        self.worker.failed.connect(
            lambda message: QMessageBox.critical(self, "Job failed", message)
        )
        self.worker.start()

    def cancel_job(self):
        job_id = self.selected_job_id()
        if job_id:
            self.service.cancel_job(job_id)
            self.refresh()

    def build_chapters(self):
        transcript_id = self.selected_transcript_id()
        if not transcript_id:
            QMessageBox.information(
                self, "Build chapters", "Select a transcript first."
            )
            return
        minutes, ok = QInputDialog.getInt(
            self,
            "Chapter target",
            "Target chapter length in minutes",
            20,
            5,
            90,
        )
        if not ok:
            return
        try:
            chapters = self.service.build_chapters(
                transcript_id, target_minutes=minutes
            )
        except Exception as exc:
            QMessageBox.critical(self, "Chapter generation failed", str(exc))
            return

        self.refresh_details()
        self.tabs.setCurrentWidget(self.chapters_table)
        if not chapters.empty:
            self.chapters_table.selectRow(0)
        count = len(chapters)
        self.action_status.setText(
            f"Built {count} chapters for transcript {transcript_id}."
        )
        QMessageBox.information(
            self, "Chapters built", f"{count} chapters were created."
        )

    def export_srt(self):
        transcript_id = self.selected_transcript_id()
        if not transcript_id:
            QMessageBox.information(
                self, "Export SRT", "Select a transcript first."
            )
            return
        transcript = self.service.transcript(transcript_id)
        default_name = f'{transcript.get("title") or "transcript"}.srt'
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SRT", default_name, "SRT (*.srt)"
        )
        if not path:
            return
        try:
            exported = self.service.export_srt(transcript_id, path)
            segment_count = len(self.service.segments(transcript_id))
        except Exception as exc:
            QMessageBox.critical(self, "SRT export failed", str(exc))
            return

        self.action_status.setText(
            f"Exported {segment_count} subtitle entries to {exported}."
        )
        QMessageBox.information(
            self,
            "SRT exported",
            f"Exported {segment_count} subtitle entries to:\n{exported}",
        )

    def search(self):
        query = self.search_text.text().strip()
        if not query:
            QMessageBox.information(
                self, "Transcript search", "Enter a word or phrase to search for."
            )
            self.search_text.setFocus()
            return
        try:
            results = self.service.search(query, transcript_id=None)
        except Exception as exc:
            QMessageBox.critical(self, "Transcript search failed", str(exc))
            return

        self.search_table.setModel(FrameModel(results))
        self._stretch_column(self.search_table, results, "text")
        self.tabs.setCurrentWidget(self.search_table)
        if not results.empty:
            self.search_table.selectRow(0)
        self.action_status.setText(
            f'Found {len(results)} result(s) for “{query}”.'
        )
