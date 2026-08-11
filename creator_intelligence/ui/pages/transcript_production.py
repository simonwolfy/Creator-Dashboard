from __future__ import annotations

import json
import pandas as pd
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.ui.pages.transcript_editor_polished import (
    PolishedTranscriptEditorPage,
)
from creator_intelligence.ui.pages.twitch import FrameModel


class TranscriptProductionPage(PolishedTranscriptEditorPage):
    """Transcript editor with clip intelligence, review, and production handoff."""

    def __init__(self, service):
        super().__init__(service)

        self.clip_controls = QWidget()
        clip_layout = QHBoxLayout(self.clip_controls)
        clip_layout.setContentsMargins(0, 0, 0, 0)
        self.clip_filter = QComboBox()
        self.clip_filter.addItems([
            "All", "Unreviewed", "Approved", "Rejected", "Needs work"
        ])
        self.clip_filter.currentTextChanged.connect(self._refresh_clip_candidates)
        clip_layout.addWidget(self.clip_filter)
        for label, handler in (
            ("Discover clips", self.discover_clips),
            ("Analyze selected", self.analyze_selected_clips),
            ("View intelligence", self.view_clip_intelligence),
            ("Edit range", self.edit_selected_clip_range),
            ("Approve", lambda: self._review_selected_clips("Approved")),
            ("Reject", lambda: self._review_selected_clips("Rejected")),
            ("Needs work", lambda: self._review_selected_clips("Needs work")),
            ("Reset", lambda: self._review_selected_clips("Unreviewed")),
            ("Send to production", self.send_selected_clips_to_production),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            clip_layout.addWidget(button)
        clip_layout.addStretch()

        self.clip_candidates_table = QTableView()
        self.clip_candidates_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.clip_candidates_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.clip_candidates_table.doubleClicked.connect(self._seek_clip_candidate)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(self.clip_controls)
        page_layout.addWidget(self.clip_candidates_table)
        self.clip_candidates_tab_index = self.tabs.addTab(page, "Clip candidates")
        self._refresh_clip_candidates()

    def _segment_group(self):
        group = super()._segment_group()
        group.layout().addWidget(self._make_button(
            "Create clip", self.create_clip_candidate, "create_clip"
        ))
        return group

    def refresh_details(self):
        super().refresh_details()
        if hasattr(self, "clip_candidates_table"):
            self._refresh_clip_candidates()

    def _update_action_states(self) -> None:
        super()._update_action_states()
        button = getattr(self, "_editor_buttons", {}).get("create_clip")
        if button is not None:
            button.setEnabled(
                self.selected_transcript_id() is not None
                and len(self._selected_segments()) >= 1
            )

    def create_clip_candidate(self) -> None:
        rows = self._selected_segments()
        transcript_id = self.selected_transcript_id()
        if rows.empty or transcript_id is None:
            QMessageBox.warning(
                self, "No transcript selected", "Select one or more transcript rows."
            )
            return
        try:
            ordered = rows.sort_values(["start_seconds", "end_seconds"])
            start = float(ordered.iloc[0]["start_seconds"])
            end = float(ordered.iloc[-1]["end_seconds"])
            combined_text = " ".join(str(value).strip() for value in ordered["text"])
            default_title = combined_text[:72].strip() or f"Clip at {self._clock(start)}"
            title, ok = QInputDialog.getText(
                self, "Create editor clip", "Clip title", text=default_title
            )
            if not ok or not title.strip():
                return
            reason, ok = QInputDialog.getMultiLineText(
                self,
                "Editor instruction",
                "Why should the editor use this moment?",
                "Creator-selected transcript moment.",
            )
            if not ok:
                return
            confidence = pd.to_numeric(
                ordered.get("confidence", pd.Series(dtype=float)), errors="coerce"
            ).dropna()
            score = float(confidence.mean() * 100.0) if len(confidence) else 50.0
            clip_id = self.service.add_clip_candidate(
                int(transcript_id), start, end, title.strip(), reason.strip(),
                score, "creator-selection",
            )
            self.service.analyze_clip_candidate(clip_id)
        except Exception as exc:
            QMessageBox.critical(self, "Clip creation failed", str(exc))
            return
        self.action_status.setText(
            f"Created and analyzed clip {clip_id}: {self._clock(start)}–{self._clock(end)}."
        )
        self._refresh_clip_candidates(selected_id=clip_id)
        self.tabs.setCurrentIndex(self.clip_candidates_tab_index)

    def discover_clips(self) -> None:
        transcript_id = self.selected_transcript_id()
        if transcript_id is None:
            QMessageBox.information(
                self, "Discover clips", "Select a transcript to scan."
            )
            return
        min_score, ok = QInputDialog.getDouble(
            self,
            "Discover clips",
            "Minimum candidate score (higher is stricter)",
            55.0,
            0.0,
            100.0,
            1,
        )
        if not ok:
            return
        max_candidates, ok = QInputDialog.getInt(
            self,
            "Discover clips",
            "Maximum moments to place in review",
            20,
            1,
            100,
            1,
        )
        if not ok:
            return
        try:
            result = self.service.discover_clip_candidates(
                int(transcript_id),
                min_score=min_score,
                max_candidates=max_candidates,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Clip discovery failed", str(exc))
            return
        self.clip_filter.setCurrentText("Unreviewed")
        self._refresh_clip_candidates()
        self.tabs.setCurrentIndex(self.clip_candidates_tab_index)
        self.action_status.setText(
            f"Scanned {result['segments_scanned']} segment(s), staged "
            f"{result['candidates_created']} clip(s), and removed "
            f"{result['duplicates_removed']} overlap(s). Review clips before Production."
        )

    def _selected_clip_ids(self) -> list[int]:
        model = self.clip_candidates_table.model()
        selection = self.clip_candidates_table.selectionModel()
        if model is None or selection is None or not hasattr(model, "frame"):
            return []
        return [
            int(model.frame.iloc[index.row()]["id"])
            for index in selection.selectedRows()
        ]

    def analyze_selected_clips(self) -> None:
        clip_ids = self._selected_clip_ids()
        if not clip_ids:
            QMessageBox.information(
                self, "Clip intelligence", "Select one or more clips to analyze."
            )
            return
        try:
            self.service.analyze_clip_candidates(clip_ids)
        except Exception as exc:
            QMessageBox.critical(self, "Clip analysis failed", str(exc))
            return
        self.action_status.setText(
            f"Analyzed {len(clip_ids)} clip(s) with local clip intelligence."
        )
        self._refresh_clip_candidates()

    def view_clip_intelligence(self) -> None:
        clip_ids = self._selected_clip_ids()
        if len(clip_ids) != 1:
            QMessageBox.information(
                self, "Clip intelligence", "Select exactly one clip."
            )
            return
        transcript_id = self.selected_transcript_id()
        full = self.service.clip_candidates(int(transcript_id))
        match = full[full["id"] == int(clip_ids[0])]
        if match.empty:
            return
        row = match.iloc[0]
        if not row.get("analyzed_at"):
            self.service.analyze_clip_candidate(int(clip_ids[0]))
            full = self.service.clip_candidates(int(transcript_id))
            row = full[full["id"] == int(clip_ids[0])].iloc[0]
        try:
            hashtags = " ".join(json.loads(row.get("suggested_hashtags_json") or "[]"))
        except Exception:
            hashtags = str(row.get("suggested_hashtags_json") or "")
        message = (
            f"Hook: {float(row.get('hook_score') or 0):.1f}\n"
            f"Humor: {float(row.get('humor_score') or 0):.1f}\n"
            f"Surprise: {float(row.get('surprise_score') or 0):.1f}\n"
            f"Emotion: {float(row.get('emotion_score') or 0):.1f}\n"
            f"Quote: {float(row.get('quote_score') or 0):.1f}\n"
            f"Viral potential: {float(row.get('viral_score') or 0):.1f}\n\n"
            f"Suggested trim: {self._clock(row.get('suggested_start_seconds') or row['start_seconds'])}–"
            f"{self._clock(row.get('suggested_end_seconds') or row['end_seconds'])}\n\n"
            f"Suggested title:\n{row.get('suggested_title') or row.get('title') or ''}\n\n"
            f"Suggested caption:\n{row.get('suggested_caption') or ''}\n\n"
            f"Hashtags:\n{hashtags}"
        )
        QMessageBox.information(self, "Clip intelligence", message)

    def edit_selected_clip_range(self) -> None:
        clip_ids = self._selected_clip_ids()
        if len(clip_ids) != 1:
            QMessageBox.information(
                self, "Edit clip range", "Select exactly one clip to edit."
            )
            return
        transcript_id = self.selected_transcript_id()
        if transcript_id is None:
            return
        full = self.service.clip_candidates(int(transcript_id))
        match = full[full["id"] == int(clip_ids[0])]
        if match.empty:
            return
        row = match.iloc[0]
        duration = float(
            self.service.transcript(int(transcript_id)).get("duration_seconds")
            or row["end_seconds"]
        )
        start, ok = QInputDialog.getDouble(
            self,
            "Edit clip range",
            "Start time in seconds",
            float(row["start_seconds"]),
            0.0,
            max(duration, float(row["end_seconds"])),
            2,
        )
        if not ok:
            return
        end, ok = QInputDialog.getDouble(
            self,
            "Edit clip range",
            "End time in seconds",
            float(row["end_seconds"]),
            start + 0.01,
            max(duration, start + 0.01),
            2,
        )
        if not ok:
            return
        try:
            self.service.edit_clip_candidate_range(int(clip_ids[0]), start, end)
        except Exception as exc:
            QMessageBox.critical(self, "Clip range update failed", str(exc))
            return
        self.action_status.setText(
            f"Updated clip {clip_ids[0]} to {self._clock(start)}–{self._clock(end)}. "
            "Reapprove it before sending it to Production."
        )
        self._refresh_clip_candidates(selected_id=int(clip_ids[0]))

    def _review_selected_clips(self, status: str) -> None:
        clip_ids = self._selected_clip_ids()
        if not clip_ids:
            QMessageBox.information(self, "Clip review", "Select one or more clips.")
            return
        try:
            self.service.set_clip_review_status(clip_ids, status)
        except Exception as exc:
            QMessageBox.critical(self, "Clip review failed", str(exc))
            return
        self.action_status.setText(f"Updated {len(clip_ids)} clip(s) to {status}.")
        self._refresh_clip_candidates()

    def send_selected_clips_to_production(self) -> None:
        clip_ids = self._selected_clip_ids()
        if not clip_ids:
            QMessageBox.information(
                self, "Send to production", "Select one or more clips first."
            )
            return
        preset, ok = QInputDialog.getItem(
            self, "Export preset", "Preset",
            ["YouTube Shorts", "TikTok", "Instagram Reels",
             "YouTube Longform", "Podcast", "Custom"], 0, False,
        )
        if not ok:
            return
        priority, ok = QInputDialog.getItem(
            self, "Priority", "Priority",
            ["Critical", "High", "Normal", "Low"], 2, False,
        )
        if not ok:
            return
        destination, ok = QInputDialog.getText(
            self, "Destination", "Destination folder or URL (optional)"
        )
        if not ok:
            return
        try:
            jobs = self.service.send_clips_to_production(
                clip_ids,
                export_preset=preset,
                priority=priority,
                destination=destination.strip() or None,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Production handoff failed", str(exc))
            return
        self.action_status.setText(
            f"Sent {len(jobs)} clip(s) to the Production queue."
        )
        self._refresh_clip_candidates()

    def _refresh_clip_candidates(self, *_args, selected_id: int | None = None) -> None:
        transcript_id = self.selected_transcript_id()
        if not transcript_id:
            frame = pd.DataFrame()
        else:
            status = self.clip_filter.currentText() if hasattr(self, "clip_filter") else "All"
            frame = self.service.clip_candidates(int(transcript_id), status)
            if not frame.empty:
                frame = frame.copy()
                frame.insert(
                    0,
                    "time",
                    frame.apply(
                        lambda row: f"{self._clock(row['start_seconds'])}–{self._clock(row['end_seconds'])}",
                        axis=1,
                    ),
                )
                visible = [
                    "id", "time", "title", "discovery_rank", "creator_dna_score",
                    "discovery_chapter_title",
                    "viral_score", "hook_score",
                    "humor_score", "surprise_score", "emotion_score", "quote_score",
                    "suggested_title", "review_status", "sent_to_production",
                    "production_status", "reason",
                ]
                frame = frame[[column for column in visible if column in frame.columns]]
        self.clip_candidates_table.setModel(FrameModel(frame))
        if selected_id is not None and not frame.empty and "id" in frame.columns:
            matches = frame.index[frame["id"] == int(selected_id)].tolist()
            if matches:
                self.clip_candidates_table.selectRow(int(matches[0]))

    def _seek_clip_candidate(self, index) -> None:
        transcript_id = self.selected_transcript_id()
        model = self.clip_candidates_table.model()
        if transcript_id is None or model is None or not hasattr(model, "frame"):
            return
        clip_id = int(model.frame.iloc[index.row()]["id"])
        full = self.service.clip_candidates(int(transcript_id))
        match = full[full["id"] == clip_id]
        if match.empty:
            return
        row = match.iloc[0]
        self.seek_requested.emit(float(row["start_seconds"]))
        segments = self.service.segments(
            int(transcript_id),
            start=float(row["start_seconds"]),
            end=float(row["end_seconds"]),
        )
        self._show_segments(segments)
        self.tabs.setCurrentWidget(self.segments_table)
        self.action_status.setText(
            f'Clip: {row["title"]} ({self._clock(row["start_seconds"])}–'
            f'{self._clock(row["end_seconds"])})'
        )
