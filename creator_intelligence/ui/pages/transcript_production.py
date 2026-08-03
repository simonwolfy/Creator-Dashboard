from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import (
    QAbstractItemView,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableView,
)

from creator_intelligence.ui.pages.transcript_editor_polished import (
    PolishedTranscriptEditorPage,
)
from creator_intelligence.ui.pages.twitch import FrameModel


class TranscriptProductionPage(PolishedTranscriptEditorPage):
    """Transcript editor with creator-selected clip handoff support."""

    def __init__(self, service):
        super().__init__(service)
        self.clip_candidates_table = QTableView()
        self.clip_candidates_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.clip_candidates_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.clip_candidates_table.doubleClicked.connect(self._seek_clip_candidate)
        self.tabs.addTab(self.clip_candidates_table, "Clip candidates")
        self._refresh_clip_candidates()

    def _segment_group(self):
        group = super()._segment_group()
        layout = group.layout()
        layout.addWidget(self._make_button(
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
            combined_text = " ".join(
                str(value).strip() for value in ordered["text"]
            )
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
                int(transcript_id),
                start,
                end,
                title.strip(),
                reason.strip(),
                score,
                "creator-selection",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Clip creation failed",
                str(exc),
            )
            return

        self.action_status.setText(
            f"Created clip candidate {clip_id}: {self._clock(start)}–{self._clock(end)}."
        )
        self._refresh_clip_candidates(selected_id=clip_id)
        self.tabs.setCurrentWidget(self.clip_candidates_table)

    def _refresh_clip_candidates(self, selected_id: int | None = None) -> None:
        transcript_id = self.selected_transcript_id()
        if not transcript_id:
            frame = pd.DataFrame()
        else:
            frame = self.service.db.frame(
                """SELECT id,transcript_id,start_seconds,end_seconds,title,reason,
                          score,source,review_status,created_at
                   FROM transcript_clip_candidates
                   WHERE transcript_id=?
                   ORDER BY start_seconds,id""",
                (int(transcript_id),),
            )
        self.clip_candidates_table.setModel(FrameModel(frame))
        if selected_id is not None and not frame.empty:
            matches = frame.index[frame["id"] == int(selected_id)].tolist()
            if matches:
                self.clip_candidates_table.selectRow(int(matches[0]))

    def _seek_clip_candidate(self, index) -> None:
        model = self.clip_candidates_table.model()
        if model is None or not hasattr(model, "frame") or model.frame.empty:
            return
        row = model.frame.iloc[index.row()]
        self.seek_requested.emit(float(row["start_seconds"]))
        self.action_status.setText(
            f'Clip: {row["title"]} ({self._clock(row["start_seconds"])}–'
            f'{self._clock(row["end_seconds"])})'
        )
