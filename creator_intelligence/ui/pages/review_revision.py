from __future__ import annotations
import pandas as pd
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QTabWidget,QAbstractItemView,QMessageBox,QInputDialog
from creator_intelligence.ui.pages.twitch import FrameModel

class ReviewRevisionPage(QWidget):
    def __init__(self,service):
        super().__init__(); self.service=service
        layout=QVBoxLayout(self); title=QLabel('Review & Revision System'); title.setObjectName('pageTitle'); layout.addWidget(title)
        row=QHBoxLayout()
        for label,fn in [('Sync editor queue',self.sync),('Create draft version',self.create_version),('Add timestamp comment',self.add_comment),('Request revision',self.request_revision),('Resolve selected comment',self.resolve_comment),('Complete all checks',self.complete_checks),('Approve version',self.approve),('Refresh',self.refresh)]:
            b=QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); layout.addLayout(row)
        self.tabs=QTabWidget(); self.queue=QTableView(); self.queue.setSelectionBehavior(QAbstractItemView.SelectRows); self.tabs.addTab(self.queue,'Needs review')
        self.versions=QTableView(); self.versions.setSelectionBehavior(QAbstractItemView.SelectRows); self.tabs.addTab(self.versions,'Versions')
        self.comments=QTableView(); self.comments.setSelectionBehavior(QAbstractItemView.SelectRows); self.tabs.addTab(self.comments,'Comments')
        self.requests=QTableView(); self.tabs.addTab(self.requests,'Revision requests')
        self.checks=QTableView(); self.tabs.addTab(self.checks,'Approval checks')
        self.analytics=QTableView(); self.tabs.addTab(self.analytics,'Review analytics')
        self.feedback=QTableView(); self.tabs.addTab(self.feedback,'Common feedback')
        layout.addWidget(self.tabs); self.queue.clicked.connect(lambda _:self.refresh_details()); self.refresh()
    def selected_workspace(self):
        i=self.queue.currentIndex(); return int(self.queue.model().frame.iloc[i.row()]['workspace_id']) if i.isValid() else None
    def selected_version(self):
        i=self.versions.currentIndex(); return int(self.versions.model().frame.iloc[i.row()]['id']) if i.isValid() else None
    def selected_comment(self):
        i=self.comments.currentIndex(); return int(self.comments.model().frame.iloc[i.row()]['id']) if i.isValid() else None
    def refresh(self):
        self.queue.setModel(FrameModel(self.service.review_queue())); self.analytics.setModel(FrameModel(self.service.analytics())); self.feedback.setModel(FrameModel(self.service.common_feedback())); self.refresh_details()
    def refresh_details(self):
        wid=self.selected_workspace()
        if not wid:
            for t in (self.versions,self.comments,self.requests,self.checks): t.setModel(FrameModel(pd.DataFrame()))
            return
        versions=self.service.versions(wid); self.versions.setModel(FrameModel(versions)); self.comments.setModel(FrameModel(self.service.comments(workspace_id=wid))); self.requests.setModel(FrameModel(self.service.revision_requests(wid)))
        latest=self.service.latest_version(wid); self.checks.setModel(FrameModel(self.service.approval_checks(latest['id']) if latest else pd.DataFrame()))
    def sync(self):
        if self.service.editor_workspace: self.service.editor_workspace.sync_from_production()
        self.refresh()
    def create_version(self):
        wid=self.selected_workspace()
        if not wid: return
        loc,ok=QInputDialog.getText(self,'Draft file','File path or URL')
        if ok: self.service.create_version(wid,loc or None); self.refresh()
    def add_comment(self):
        wid=self.selected_workspace(); vid=self.selected_version()
        if not wid or not vid: return
        ts,ok=QInputDialog.getDouble(self,'Timestamp','Seconds',0,0,999999,3)
        if not ok:return
        body,ok=QInputDialog.getMultiLineText(self,'Review comment','Comment')
        if ok and body:self.service.add_comment(wid,vid,body,timestamp_seconds=ts,priority='High');self.refresh_details()
    def request_revision(self):
        wid=self.selected_workspace(); vid=self.selected_version()
        if not wid or not vid:return
        title,ok=QInputDialog.getText(self,'Revision request','Title','Revision requested')
        if ok:self.service.create_revision_request(wid,vid,title or 'Revision requested');self.refresh()
    def resolve_comment(self):
        cid=self.selected_comment()
        if cid:self.service.resolve_comment(cid,'Completed by editor.');self.refresh_details()
    def complete_checks(self):
        vid=self.selected_version()
        if not vid:return
        for _,r in self.service.approval_checks(vid).iterrows(): self.service.set_check(int(r['id']),'Complete')
        self.refresh_details()
    def approve(self):
        vid=self.selected_version()
        if not vid:return
        try:self.service.approve_version(vid);self.refresh()
        except Exception as exc:QMessageBox.warning(self,'Cannot approve',str(exc))
