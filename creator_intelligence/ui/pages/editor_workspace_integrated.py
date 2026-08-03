from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import (
    QAbstractItemView,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableView,
)

from creator_intelligence.ui.pages.editor_workspace import EditorWorkspacePage
from creator_intelligence.ui.pages.twitch import FrameModel


class IntegratedEditorWorkspacePage(EditorWorkspacePage):
    """Editor workspace that consumes creator-selected transcript clips."""

    def __init__(self, service):
        super().__init__(service)
        self.transcript_clips_table = QTableView()
        self.transcript_clips_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.tabs.addTab(self.transcript_clips_table, "Transcript clips")

        self.include_clips_button = QPushButton("Add transcript clips to brief")
        self.include_clips_button.clicked.connect(self.add_clips_to_latest_brief)
        self.layout().insertWidget(3, self.include_clips_button)
        self.refresh_details()

    def refresh_details(self):
        super().refresh_details()
        if hasattr(self, "transcript_clips_table"):
            self._refresh_transcript_clips()

    def generate_brief(self):
        workspace_id = self.selected_workspace_id()
        if not workspace_id:
            QMessageBox.warning(self, "No project selected", "Select an editor project.")
            return
        transcript_id, ok = QInputDialog.getInt(
            self, "Transcript", "Transcript ID (0 for none)", 0, 0, 999999
        )
        if not ok:
            return
        brief = self.service.generate_brief(
            workspace_id, transcript_id=transcript_id or None
        )
        added = self._attach_transcript_clips(
            int(brief["id"]), transcript_id or None
        )
        QMessageBox.information(
            self,
            "Brief generated",
            f'Brief version {brief["version"]} was generated with '
            f"{added} creator-selected transcript clip(s).",
        )
        self.refresh()

    def add_clips_to_latest_brief(self):
        workspace_id = self.selected_workspace_id()
        if not workspace_id:
            QMessageBox.warning(self, "No project selected", "Select an editor project.")
            return
        workspace = self.service.workspace_project(workspace_id)
        transcript_id = workspace.get("transcript_id")
        brief = self.service.latest_brief(workspace_id)
        if not brief:
            QMessageBox.warning(
                self, "No brief", "Generate an editor brief before adding clips."
            )
            return
        if not transcript_id:
            QMessageBox.warning(
                self, "No transcript linked", "Generate the brief with a transcript ID first."
            )
            return
        added = self._attach_transcript_clips(int(brief["id"]), int(transcript_id))
        QMessageBox.information(
            self, "Transcript clips added", f"Added {added} new clip(s) to the brief."
        )
        self.refresh_details()

    def _refresh_transcript_clips(self):
        workspace_id = self.selected_workspace_id()
        frame = pd.DataFrame()
        enabled = False
        if workspace_id:
            workspace = self.service.workspace_project(workspace_id)
            transcript_id = workspace.get("transcript_id")
            if transcript_id:
                frame = self.service.db.frame(
                    """SELECT id,start_seconds,end_seconds,title,reason,score,
                              source,review_status,created_at
                       FROM transcript_clip_candidates
                       WHERE transcript_id=?
                       ORDER BY start_seconds,id""",
                    (int(transcript_id),),
                )
                enabled = self.service.latest_brief(workspace_id) is not None
        self.transcript_clips_table.setModel(FrameModel(frame))
        self.include_clips_button.setEnabled(enabled and not frame.empty)

    def _attach_transcript_clips(self, brief_id: int, transcript_id: int | None) -> int:
        if not transcript_id:
            return 0
        clips = self.service.db.frame(
            """SELECT * FROM transcript_clip_candidates
               WHERE transcript_id=? AND review_status!='Rejected'
               ORDER BY start_seconds,id""",
            (int(transcript_id),),
        )
        if clips.empty:
            return 0

        existing = self.service.db.frame(
            """SELECT start_seconds,end_seconds,title FROM editor_brief_moments
               WHERE brief_id=?""",
            (int(brief_id),),
        )
        signatures = {
            (round(float(row["start_seconds"]), 2),
             round(float(row["end_seconds"]), 2),
             str(row["title"]))
            for _, row in existing.iterrows()
        }
        next_index_frame = self.service.db.frame(
            """SELECT COALESCE(MAX(moment_index),-1)+1 AS next_index
               FROM editor_brief_moments WHERE brief_id=?""",
            (int(brief_id),),
        )
        next_index = int(next_index_frame.iloc[0]["next_index"])
        now = self.service.db.frame("SELECT datetime('now') AS now").iloc[0]["now"]
        added = 0
        for _, row in clips.iterrows():
            signature = (
                round(float(row["start_seconds"]), 2),
                round(float(row["end_seconds"]), 2),
                str(row["title"]),
            )
            if signature in signatures:
                continue
            start = float(row["start_seconds"])
            end = float(row["end_seconds"])
            self.service.db.execute(
                """INSERT INTO editor_brief_moments(
                    brief_id,moment_index,start_seconds,peak_seconds,end_seconds,
                    title,category,score,confidence,role,instruction,
                    source_highlight_id,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(brief_id), next_index, start, (start + end) / 2.0, end,
                    str(row["title"]), "Transcript clip", float(row["score"] or 0),
                    min(1.0, max(0.0, float(row["score"] or 0) / 100.0)),
                    "Creator-selected clip",
                    str(row["reason"] or "Use this creator-selected transcript moment."),
                    None, str(now),
                ),
            )
            signatures.add(signature)
            next_index += 1
            added += 1
        return added
