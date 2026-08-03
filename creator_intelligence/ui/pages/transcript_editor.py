from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
)

from creator_intelligence.ui.pages.transcripts import TranscriptsPage


EXPORT_FORMATS = {
    "SRT subtitles": ("srt", "SRT (*.srt)", "export_srt"),
    "Markdown transcript": ("md", "Markdown (*.md)", "export_markdown"),
    "CSV transcript": ("csv", "CSV (*.csv)", "export_csv"),
    "YouTube chapters": ("txt", "Text (*.txt)", "export_youtube_chapters"),
    "Premiere markers": ("csv", "CSV (*.csv)", "export_marker_csv:premiere"),
    "Resolve markers": ("csv", "CSV (*.csv)", "export_marker_csv:resolve"),
    "Final Cut Pro XML": ("fcpxml", "FCPXML (*.fcpxml)", "export_fcpxml"),
    "Review package JSON": ("json", "JSON (*.json)", "export_review_json"),
}


def format_transcript_statistics(stats: dict) -> str:
    confidence = stats.get("average_confidence")
    confidence_text = "—" if confidence is None else f"{float(confidence) * 100:.1f}%"
    return (
        f"Words: {int(stats.get('word_count') or 0):,}   |   "
        f"Segments: {int(stats.get('segment_count') or 0):,}   |   "
        f"Chapters: {int(stats.get('chapter_count') or 0):,}   |   "
        f"Speakers: {int(stats.get('speaker_count') or 0):,}   |   "
        f"WPM: {float(stats.get('words_per_minute') or 0):.1f}   |   "
        f"Silence: {float(stats.get('silence_percent') or 0):.1f}%   |   "
        f"Longest pause: {float(stats.get('longest_pause_seconds') or 0):.1f}s   |   "
        f"Confidence: {confidence_text}"
    )


class TranscriptEditorPage(TranscriptsPage):
    """Transcript Engine page with editing, review, chapter, and export tools."""

    seek_requested = Signal(float)

    def __init__(self, service):
        super().__init__(service)

        self.segments_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.segments_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.chapters_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.chapters_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.segments_table.doubleClicked.connect(self._seek_segment)
        self.chapters_table.doubleClicked.connect(self._seek_chapter)
        self.search_table.doubleClicked.connect(self._seek_search_result)

        self.stats_label = QLabel("Select a transcript to view statistics.")
        self.stats_label.setWordWrap(True)

        segment_tools = QHBoxLayout()
        for label, handler in (
            ("Edit text", self.edit_segment),
            ("Assign speaker", self.assign_speaker),
            ("Split segment", self.split_segment),
            ("Merge segments", self.merge_segments),
            ("Delete segment", self.delete_segment),
            ("Mark reviewed", lambda: self.set_review_status("Reviewed")),
            ("Needs revision", lambda: self.set_review_status("Needs revision")),
            ("Mark unreviewed", lambda: self.set_review_status("Unreviewed")),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            segment_tools.addWidget(button)
        segment_tools.addStretch()

        quality_tools = QHBoxLayout()
        self.low_confidence_only = QCheckBox("Low confidence only")
        self.low_confidence_only.toggled.connect(self.apply_segment_filter)
        self.confidence_threshold = QDoubleSpinBox()
        self.confidence_threshold.setRange(0.05, 1.0)
        self.confidence_threshold.setSingleStep(0.05)
        self.confidence_threshold.setDecimals(2)
        self.confidence_threshold.setValue(0.65)
        self.confidence_threshold.valueChanged.connect(self.apply_segment_filter)
        quality_tools.addWidget(self.low_confidence_only)
        quality_tools.addWidget(QLabel("Below"))
        quality_tools.addWidget(self.confidence_threshold)
        quality_tools.addStretch()

        chapter_tools = QHBoxLayout()
        for label, handler in (
            ("Rename chapter", self.rename_chapter),
            ("Split chapter", self.split_chapter),
            ("Merge chapters", self.merge_chapters),
            ("Delete chapter", self.delete_chapter),
            ("Create chapter", self.create_chapter),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            chapter_tools.addWidget(button)
        chapter_tools.addStretch()

        export_tools = QHBoxLayout()
        export_tools.addWidget(QLabel("Export format"))
        self.export_format = QComboBox()
        self.export_format.addItems(EXPORT_FORMATS.keys())
        export_tools.addWidget(self.export_format)
        export_button = QPushButton("Export selected transcript")
        export_button.clicked.connect(self.export_selected_format)
        export_tools.addWidget(export_button)
        export_tools.addStretch()

        layout = self.layout()
        insert_at = layout.indexOf(self.tabs)
        layout.insertWidget(insert_at, self.stats_label)
        layout.insertLayout(insert_at + 1, segment_tools)
        layout.insertLayout(insert_at + 2, quality_tools)
        layout.insertLayout(insert_at + 3, chapter_tools)
        layout.insertLayout(insert_at + 4, export_tools)
        self._refresh_editor_summary()

    def refresh_details(self):
        super().refresh_details()
        if hasattr(self, "stats_label"):
            self._refresh_editor_summary()
            self.apply_segment_filter()

    def _refresh_editor_summary(self):
        transcript_id = self.selected_transcript_id()
        if not transcript_id:
            self.stats_label.setText("Select a transcript to view statistics.")
            return
        try:
            self.stats_label.setText(format_transcript_statistics(
                self.service.transcript_statistics(transcript_id)
            ))
        except Exception as exc:
            self.stats_label.setText(f"Statistics unavailable: {exc}")

    def _selected_rows(self, table) -> pd.DataFrame:
        model = table.model()
        if model is None or not hasattr(model, "frame") or model.frame.empty:
            return pd.DataFrame()
        rows = sorted({index.row() for index in table.selectionModel().selectedRows()})
        if not rows and table.currentIndex().isValid():
            rows = [table.currentIndex().row()]
        return model.frame.iloc[rows].copy() if rows else pd.DataFrame()

    def _selected_segments(self) -> pd.DataFrame:
        return self._selected_rows(self.segments_table)

    def _selected_chapters(self) -> pd.DataFrame:
        return self._selected_rows(self.chapters_table)

    def apply_segment_filter(self, *_):
        if not hasattr(self, "low_confidence_only") or self._all_segments.empty:
            return
        selected_id = None
        selected = self._selected_segments()
        if not selected.empty and "id" in selected:
            selected_id = int(selected.iloc[0]["id"])
        frame = self._all_segments
        if self.low_confidence_only.isChecked() and "confidence" in frame:
            values = pd.to_numeric(frame["confidence"], errors="coerce")
            frame = frame[values.isna() | (values < self.confidence_threshold.value())]
        self._show_segments(frame, selected_segment_id=selected_id)

    def edit_segment(self):
        rows = self._selected_segments()
        if len(rows) != 1:
            self._selection_warning("Select exactly one transcript segment.")
            return
        row = rows.iloc[0]
        text, ok = QInputDialog.getMultiLineText(
            self, "Edit transcript segment", "Text", str(row["text"])
        )
        if ok:
            self._run_editor_action(
                lambda: self.service.update_segment(int(row["id"]), text=text),
                "Segment text updated.",
                int(row["id"]),
            )

    def assign_speaker(self):
        rows = self._selected_segments()
        if rows.empty:
            self._selection_warning("Select one or more transcript segments.")
            return
        current = str(rows.iloc[0].get("speaker") or "")
        speaker, ok = QInputDialog.getText(self, "Assign speaker", "Speaker name", text=current)
        if not ok:
            return
        self._run_editor_action(
            lambda: [self.service.update_segment(int(row["id"]), speaker=speaker)
                     for _, row in rows.iterrows()],
            f"Assigned speaker to {len(rows)} segment(s).",
            int(rows.iloc[0]["id"]),
        )

    def split_segment(self):
        rows = self._selected_segments()
        if len(rows) != 1:
            self._selection_warning("Select exactly one transcript segment.")
            return
        row = rows.iloc[0]
        start = float(row["start_seconds"])
        end = float(row["end_seconds"])
        split, ok = QInputDialog.getDouble(
            self, "Split segment", "Split timestamp (seconds)",
            (start + end) / 2.0, start + 0.01, end - 0.01, 2,
        )
        if ok:
            self._run_editor_action(
                lambda: self.service.split_segment(int(row["id"]), split),
                f"Segment split at {self._clock(split)}.",
                int(row["id"]),
            )

    def merge_segments(self):
        rows = self._selected_segments()
        if len(rows) != 2:
            self._selection_warning("Select exactly two adjacent transcript segments.")
            return
        rows = rows.sort_values("segment_index")
        first_id = int(rows.iloc[0]["id"])
        second_id = int(rows.iloc[1]["id"])
        self._run_editor_action(
            lambda: self.service.merge_segments(first_id, second_id),
            "Segments merged.",
            first_id,
        )

    def delete_segment(self):
        rows = self._selected_segments()
        if rows.empty:
            self._selection_warning("Select one or more transcript segments.")
            return
        answer = QMessageBox.question(
            self, "Delete transcript segments",
            f"Delete {len(rows)} selected segment(s)? This cannot be undone.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_editor_action(
            lambda: [self.service.delete_segment(int(row["id"]))
                     for _, row in rows.sort_values("segment_index", ascending=False).iterrows()],
            f"Deleted {len(rows)} segment(s).",
        )

    def set_review_status(self, status: str):
        rows = self._selected_segments()
        if rows.empty:
            self._selection_warning("Select one or more transcript segments.")
            return
        self._run_editor_action(
            lambda: [self.service.set_segment_review(int(row["id"]), status)
                     for _, row in rows.iterrows()],
            f"Marked {len(rows)} segment(s) as {status.lower()}.",
            int(rows.iloc[0]["id"]),
        )

    def rename_chapter(self):
        rows = self._selected_chapters()
        if len(rows) != 1:
            self._selection_warning("Select exactly one chapter.")
            return
        row = rows.iloc[0]
        title, ok = QInputDialog.getText(
            self, "Rename chapter", "Chapter title", text=str(row["title"])
        )
        if ok:
            self._run_chapter_action(
                lambda: self.service.rename_chapter(int(row["id"]), title),
                "Chapter renamed.",
            )

    def split_chapter(self):
        rows = self._selected_chapters()
        if len(rows) != 1:
            self._selection_warning("Select exactly one chapter.")
            return
        row = rows.iloc[0]
        start = float(row["start_seconds"])
        end = float(row["end_seconds"])
        split, ok = QInputDialog.getDouble(
            self, "Split chapter", "Split timestamp (seconds)",
            (start + end) / 2.0, start + 0.01, end - 0.01, 2,
        )
        if not ok:
            return
        title, ok = QInputDialog.getText(
            self, "New chapter title", "Title for second chapter",
            text=f'{row["title"]} — Part 2',
        )
        if ok:
            self._run_chapter_action(
                lambda: self.service.split_chapter(int(row["id"]), split, title),
                f"Chapter split at {self._clock(split)}.",
            )

    def merge_chapters(self):
        rows = self._selected_chapters()
        if len(rows) != 2:
            self._selection_warning("Select exactly two adjacent chapters.")
            return
        rows = rows.sort_values("chapter_index")
        first = rows.iloc[0]
        second = rows.iloc[1]
        title, ok = QInputDialog.getText(
            self, "Merge chapters", "Merged chapter title", text=str(first["title"])
        )
        if ok:
            self._run_chapter_action(
                lambda: self.service.merge_chapters(
                    int(first["id"]), int(second["id"]), title
                ),
                "Chapters merged.",
            )

    def delete_chapter(self):
        rows = self._selected_chapters()
        if rows.empty:
            self._selection_warning("Select one or more chapters.")
            return
        answer = QMessageBox.question(
            self, "Delete chapters",
            f"Delete {len(rows)} selected chapter(s)? This cannot be undone.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_chapter_action(
            lambda: [self.service.delete_chapter(int(row["id"]))
                     for _, row in rows.sort_values("chapter_index", ascending=False).iterrows()],
            f"Deleted {len(rows)} chapter(s).",
        )

    def create_chapter(self):
        transcript_id = self.selected_transcript_id()
        if not transcript_id:
            self._selection_warning("Select a transcript first.")
            return
        title, ok = QInputDialog.getText(self, "Create chapter", "Chapter title")
        if not ok or not title.strip():
            return
        start, ok = QInputDialog.getDouble(
            self, "Create chapter", "Start timestamp (seconds)", 0.0, 0.0, 10_000_000.0, 2
        )
        if not ok:
            return
        end, ok = QInputDialog.getDouble(
            self, "Create chapter", "End timestamp (seconds)", start + 60.0,
            start + 0.01, 10_000_000.0, 2,
        )
        if ok:
            self._run_chapter_action(
                lambda: self.service.create_manual_chapter(transcript_id, start, end, title),
                "Manual chapter created.",
            )

    def export_selected_format(self):
        transcript_id = self.selected_transcript_id()
        if not transcript_id:
            self._selection_warning("Select a transcript first.")
            return
        label = self.export_format.currentText()
        extension, file_filter, operation = EXPORT_FORMATS[label]
        transcript = self.service.transcript(transcript_id)
        safe_title = str(transcript.get("title") or "transcript").replace("/", "_").replace("\\", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {label}", f"{safe_title}.{extension}", file_filter
        )
        if not path:
            return
        output = Path(path)
        try:
            if operation.startswith("export_marker_csv:"):
                marker_format = operation.split(":", 1)[1]
                exported = self.service.export_marker_csv(transcript_id, output, marker_format)
            else:
                exported = getattr(self.service, operation)(transcript_id, output)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.action_status.setText(f"Exported {label} to {exported}.")
        QMessageBox.information(self, "Export complete", f"Saved to:\n{exported}")

    def _run_editor_action(self, action, message: str, selected_segment_id: int | None = None):
        try:
            action()
        except Exception as exc:
            QMessageBox.critical(self, "Transcript edit failed", str(exc))
            return
        self.refresh_details()
        if selected_segment_id is not None:
            self._show_segments(self._all_segments, selected_segment_id)
        self.action_status.setText(message)

    def _run_chapter_action(self, action, message: str):
        try:
            action()
        except Exception as exc:
            QMessageBox.critical(self, "Chapter edit failed", str(exc))
            return
        self.refresh_details()
        self.tabs.setCurrentWidget(self.chapters_table)
        self.action_status.setText(message)

    def _seek_segment(self, index):
        model = self.segments_table.model()
        if not index.isValid() or model is None or not hasattr(model, "frame"):
            return
        seconds = float(model.frame.iloc[index.row()]["start_seconds"])
        self.seek_requested.emit(seconds)
        self.action_status.setText(f"Seek requested at {self._clock(seconds)}.")

    def _seek_chapter(self, index):
        model = self.chapters_table.model()
        if not index.isValid() or model is None or not hasattr(model, "frame"):
            return
        seconds = float(model.frame.iloc[index.row()]["start_seconds"])
        self.seek_requested.emit(seconds)
        self.action_status.setText(f"Seek requested at chapter start {self._clock(seconds)}.")

    def _seek_search_result(self, index):
        if not index.isValid() or self._search_results.empty:
            return
        seconds = float(self._search_results.iloc[index.row()]["start_seconds"])
        self.seek_requested.emit(seconds)
        self.action_status.setText(f"Seek requested at search result {self._clock(seconds)}.")

    def _selection_warning(self, message: str):
        QMessageBox.information(self, "Transcript Editor", message)
