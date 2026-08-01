from __future__ import annotations
import json
import pandas as pd
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QTabWidget,
    QAbstractItemView,QMessageBox,QInputDialog,QPlainTextEdit
)
from creator_intelligence.ui.pages.twitch import FrameModel

class EditorWorkspacePage(QWidget):
    def __init__(self,service):
        super().__init__()
        self.service=service
        layout=QVBoxLayout(self)
        title=QLabel("Editor Workspace")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.summary=QLabel()
        layout.addWidget(self.summary)

        controls=QHBoxLayout()
        actions=[
            ("Sync production queue",self.sync),
            ("Generate AI brief",self.generate_brief),
            ("Acknowledge",self.acknowledge),
            ("Start editing",self.start_editing),
            ("Mark ready for review",self.ready_for_review),
            ("Add note",self.add_note),
            ("Refresh",self.refresh)
        ]
        for label,handler in actions:
            button=QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)

        self.tabs=QTabWidget()
        self.queue_table=QTableView()
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.queue_table,"Editor queue")
        self.brief_view=QPlainTextEdit()
        self.brief_view.setReadOnly(True)
        self.tabs.addTab(self.brief_view,"AI editor brief")
        self.moments_table=QTableView()
        self.tabs.addTab(self.moments_table,"Brief moments")
        self.notes_table=QTableView()
        self.tabs.addTab(self.notes_table,"Notes")
        self.checklist_table=QTableView()
        self.tabs.addTab(self.checklist_table,"Checklist")
        layout.addWidget(self.tabs)

        self.queue_table.clicked.connect(lambda _:self.refresh_details())
        self.refresh()

    def selected_workspace_id(self):
        index=self.queue_table.currentIndex()
        if not index.isValid():
            return None
        return int(self.queue_table.model().frame.iloc[index.row()]["id"])

    def refresh(self):
        dashboard=self.service.dashboard()
        self.summary.setText(
            f'Queued: {dashboard["queued"]}   |   '
            f'Assigned: {dashboard["assigned"]}   |   '
            f'Editing: {dashboard["editing"]}   |   '
            f'Ready for review: {dashboard["ready_for_review"]}   |   '
            f'Revisions: {dashboard["revision"]}   |   '
            f'Estimated editor hours: {dashboard["estimated_hours"]:.2f}   |   '
            f'Open notes: {dashboard["open_notes"]}'
        )
        self.queue_table.setModel(FrameModel(self.service.queue()))
        self.refresh_details()

    def refresh_details(self):
        workspace_id=self.selected_workspace_id()
        if not workspace_id:
            self.brief_view.setPlainText("Select a project.")
            self.moments_table.setModel(FrameModel(pd.DataFrame()))
            self.notes_table.setModel(FrameModel(pd.DataFrame()))
            self.checklist_table.setModel(FrameModel(pd.DataFrame()))
            return
        brief=self.service.latest_brief(workspace_id)
        if brief:
            display={
                "version":brief["version"],
                "objective":brief["objective"],
                "summary":brief["summary"],
                "editing_style":brief["editing_style"],
                "pacing":brief["pacing"],
                "target_duration_seconds":brief["target_duration_seconds"],
                "hook_notes":brief["hook_notes"],
                "ending_notes":brief["ending_notes"],
                "avoid_notes":brief["avoid_notes"],
                "required_elements":json.loads(
                    brief["required_elements_json"] or "[]"
                )
            }
            self.brief_view.setPlainText(
                json.dumps(display,indent=2,default=str)
            )
            self.moments_table.setModel(
                FrameModel(self.service.brief_moments(brief["id"]))
            )
        else:
            self.brief_view.setPlainText("No AI brief has been generated.")
            self.moments_table.setModel(FrameModel(pd.DataFrame()))
        self.notes_table.setModel(FrameModel(self.service.notes(workspace_id)))
        self.checklist_table.setModel(
            FrameModel(self.service.checklist(workspace_id))
        )

    def sync(self):
        count=self.service.sync_from_production()
        QMessageBox.information(
            self,"Queue synchronized",
            f"{count} production projects were added to the editor workspace."
        )
        self.refresh()

    def generate_brief(self):
        workspace_id=self.selected_workspace_id()
        if not workspace_id:
            return
        transcript_id,ok=QInputDialog.getInt(
            self,"Transcript","Transcript ID (0 for none)",
            0,0,999999
        )
        if ok:
            brief=self.service.generate_brief(
                workspace_id,
                transcript_id=transcript_id or None
            )
            QMessageBox.information(
                self,"Brief generated",
                f'Brief version {brief["version"]} was generated.'
            )
            self.refresh()

    def acknowledge(self):
        workspace_id=self.selected_workspace_id()
        if workspace_id:
            self.service.acknowledge(workspace_id)
            self.refresh()

    def start_editing(self):
        workspace_id=self.selected_workspace_id()
        if workspace_id:
            self.service.start_editing(workspace_id)
            self.refresh()

    def ready_for_review(self):
        workspace_id=self.selected_workspace_id()
        if not workspace_id:
            return
        hours,ok=QInputDialog.getDouble(
            self,"Completed work","Editor hours used",
            1.0,0,1000,2
        )
        if ok:
            self.service.mark_ready_for_review(workspace_id,hours)
            self.refresh()

    def add_note(self):
        workspace_id=self.selected_workspace_id()
        if not workspace_id:
            return
        timestamp,ok=QInputDialog.getDouble(
            self,"Timestamp","Timestamp seconds (-1 for general)",
            -1,-1,999999,1
        )
        if not ok:
            return
        body,ok=QInputDialog.getMultiLineText(
            self,"Editor note","Note"
        )
        if ok and body:
            self.service.add_note(
                workspace_id,body,
                timestamp_seconds=None if timestamp<0 else timestamp
            )
            self.refresh_details()
