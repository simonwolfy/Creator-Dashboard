from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.services.production_pipeline import (
    CLIP_EXPORT_PRESETS,
    CLIP_JOB_STATUSES,
)
from creator_intelligence.ui.pages.production import ProductionPage
from creator_intelligence.ui.pages.twitch import FrameModel


class ProductionPipelinePage(ProductionPage):
    """Production management page with an operational clip queue."""

    seek_requested = Signal(float)

    def __init__(self, service):
        super().__init__(service)

        self.clip_page = QWidget()
        layout = QVBoxLayout(self.clip_page)
        self.clip_summary = QLabel()
        layout.addWidget(self.clip_summary)

        controls = QHBoxLayout()
        for label, handler in (
            ("Change clip status", self.change_clip_status),
            ("Set priority", self.set_clip_priority),
            ("Assign clip editor", self.assign_clip_editor),
            ("Set export preset", self.set_export_preset),
            ("Set destination", self.set_destination),
            ("Add editor note", self.add_clip_note),
            ("Export queue", self.export_clip_queue),
            ("Refresh clips", self.refresh_clips),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)

        self.clip_jobs_table = QTableView()
        self.clip_jobs_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.clip_jobs_table.doubleClicked.connect(self.seek_clip_job)
        layout.addWidget(self.clip_jobs_table, 3)

        layout.addWidget(QLabel("Selected clip notes"))
        self.clip_notes_table = QTableView()
        self.clip_notes_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        layout.addWidget(self.clip_notes_table, 1)
        self.clip_jobs_table.clicked.connect(lambda _: self.refresh_clip_notes())

        self.tabs.addTab(self.clip_page, "Clip production queue")
        self.refresh_clips()

    def selected_clip_job_id(self):
        index = self.clip_jobs_table.currentIndex()
        model = self.clip_jobs_table.model()
        if not index.isValid() or model is None or not hasattr(model, "frame"):
            return None
        return int(model.frame.iloc[index.row()]["id"])

    def refresh(self):
        super().refresh()
        if hasattr(self, "clip_jobs_table"):
            self.refresh_clips()

    def refresh_clips(self):
        selected = self.selected_clip_job_id()
        frame = self.service.clip_jobs()
        self.clip_jobs_table.setModel(FrameModel(frame))
        dashboard = self.service.clip_dashboard()
        self.clip_summary.setText(
            f'New: {dashboard["new"]}   |   Ready: {dashboard["ready"]}   |   '
            f'Editing: {dashboard["editing"]}   |   Review: {dashboard["review"]}   |   '
            f'Rendering: {dashboard["rendering"]}   |   Finished: {dashboard["finished"]}   |   '
            f'Queued duration: {dashboard["queued_duration_seconds"] / 60:.1f} minutes'
        )
        if selected is not None and not frame.empty:
            matches = frame.index[frame["id"] == selected].tolist()
            if matches:
                self.clip_jobs_table.selectRow(int(matches[0]))
        self.refresh_clip_notes()

    def refresh_clip_notes(self):
        job_id = self.selected_clip_job_id()
        frame = self.service.clip_notes(job_id) if job_id else pd.DataFrame()
        self.clip_notes_table.setModel(FrameModel(frame))

    def _update_selected_clip(self, **changes):
        job_id = self.selected_clip_job_id()
        if job_id is None:
            QMessageBox.information(self, "Clip queue", "Select a clip job first.")
            return
        try:
            self.service.update_clip_job(job_id, **changes)
        except Exception as exc:
            QMessageBox.critical(self, "Clip update failed", str(exc))
            return
        self.refresh_clips()

    def change_clip_status(self):
        status, ok = QInputDialog.getItem(
            self, "Clip status", "Status", list(CLIP_JOB_STATUSES), 0, False
        )
        if ok:
            self._update_selected_clip(status=status)

    def set_clip_priority(self):
        priority, ok = QInputDialog.getItem(
            self, "Clip priority", "Priority",
            ["Critical", "High", "Normal", "Low"], 2, False,
        )
        if ok:
            self._update_selected_clip(priority=priority)

    def assign_clip_editor(self):
        editors = self.service.editors(active_only=True)
        if editors.empty:
            QMessageBox.warning(self, "No editors", "Add an editor first.")
            return
        labels = ["Unassigned"] + editors["name"].tolist()
        label, ok = QInputDialog.getItem(
            self, "Assign clip editor", "Editor", labels, 0, False
        )
        if not ok:
            return
        editor_id = None
        if label != "Unassigned":
            editor_id = int(editors[editors["name"] == label].iloc[0]["id"])
        self._update_selected_clip(editor_id=editor_id)

    def set_export_preset(self):
        preset, ok = QInputDialog.getItem(
            self, "Export preset", "Preset", list(CLIP_EXPORT_PRESETS), 0, False
        )
        if ok:
            self._update_selected_clip(export_preset=preset)

    def set_destination(self):
        destination, ok = QInputDialog.getText(
            self, "Clip destination", "Folder or URL"
        )
        if ok:
            self._update_selected_clip(destination=destination.strip() or None)

    def add_clip_note(self):
        job_id = self.selected_clip_job_id()
        if job_id is None:
            return
        timestamp, ok = QInputDialog.getDouble(
            self, "Note timestamp", "Seconds (-1 for general)", -1, -1, 999999, 2
        )
        if not ok:
            return
        body, ok = QInputDialog.getMultiLineText(
            self, "Editor note", "Instruction"
        )
        if ok and body.strip():
            self.service.add_clip_note(
                job_id,
                body.strip(),
                None if timestamp < 0 else timestamp,
            )
            self.refresh_clip_notes()

    def export_clip_queue(self):
        formats = [
            "Production Queue (.csv)",
            "Production Queue (.json)",
            "Edit Decision List (.edl)",
            "Adobe Premiere Pro Markers (.csv)",
            "DaVinci Resolve Markers (.csv)",
        ]

        format_name, ok = QInputDialog.getItem(
            self,
            "Export queue",
            "Export format",
            formats,
            0,
            False,
        )
        if not ok:
            return

        export_map = {
            "Production Queue (.csv)": ("CSV", ".csv"),
            "Production Queue (.json)": ("JSON", ".json"),
            "Edit Decision List (.edl)": ("EDL", ".edl"),
            "Adobe Premiere Pro Markers (.csv)": ("Premiere markers", ".csv"),
            "DaVinci Resolve Markers (.csv)": ("Resolve markers", ".csv"),
        }
    
        export_type, suffix = export_map[format_name]

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export production queue",
            str(Path.cwd() / f"clip_production_queue{suffix}"),
        )
        if not path:
            return

        try:
            saved = self.service.export_clip_jobs(path, export_type)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return

        QMessageBox.information(self, "Queue exported", saved)

    def seek_clip_job(self, index):
        model = self.clip_jobs_table.model()
        if model is None or not hasattr(model, "frame") or model.frame.empty:
            return
        row = model.frame.iloc[index.row()]
        self.seek_requested.emit(float(row["start_seconds"]))
        QMessageBox.information(
            self,
            "Transcript location",
            f'{row["title"]}\nTranscript {int(row["transcript_id"])}\n'
            f'{row["time_range"]}',
        )
