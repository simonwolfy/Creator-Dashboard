import json, pandas as pd
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QAbstractItemView,QMessageBox,QInputDialog,QPlainTextEdit
from creator_intelligence.ui.pages.twitch import FrameModel
class ContentRecommendationsPage(QWidget):
    def __init__(self,service):
        super().__init__(); self.service=service
        layout=QVBoxLayout(self); title=QLabel('Short and Long-Form Recommendations'); title.setObjectName('pageTitle'); layout.addWidget(title)
        row=QHBoxLayout()
        for label,fn in [('Generate',self.generate),('Approve',lambda:self.review('Approved')),('Reject',lambda:self.review('Rejected')),('Send to production',self.send),('Refresh',self.refresh)]:
            b=QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); layout.addLayout(row)
        self.summary=QPlainTextEdit(); self.summary.setReadOnly(True); self.summary.setMaximumHeight(130); layout.addWidget(self.summary)
        self.transcripts=QTableView(); self.transcripts.setSelectionBehavior(QAbstractItemView.SelectRows); layout.addWidget(self.transcripts)
        self.recs=QTableView(); self.recs.setSelectionBehavior(QAbstractItemView.SelectRows); layout.addWidget(self.recs)
        self.outline=QTableView(); layout.addWidget(self.outline)
        self.transcripts.clicked.connect(lambda _:self.refresh_recs()); self.recs.clicked.connect(lambda _:self.refresh_outline()); self.refresh()
    def transcript_id(self):
        i=self.transcripts.currentIndex(); return int(self.transcripts.model().frame.iloc[i.row()]['id']) if i.isValid() else None
    def rec_id(self):
        i=self.recs.currentIndex(); return int(self.recs.model().frame.iloc[i.row()]['id']) if i.isValid() else None
    def refresh(self):
        self.transcripts.setModel(FrameModel(self.service.highlight_scoring.transcript_service.transcripts())); self.refresh_recs()
    def refresh_recs(self):
        tid=self.transcript_id()
        if not tid: self.recs.setModel(FrameModel(pd.DataFrame())); self.summary.setPlainText('Select a transcript.'); return
        self.recs.setModel(FrameModel(self.service.recommendations(tid))); self.summary.setPlainText(json.dumps(self.service.summary(tid),indent=2)); self.refresh_outline()
    def refresh_outline(self):
        rid=self.rec_id(); self.outline.setModel(FrameModel(self.service.outline(rid) if rid else pd.DataFrame()))
    def generate(self):
        tid=self.transcript_id()
        if not tid:return
        try:
            frame=self.service.generate(tid); QMessageBox.information(self,'Generated',f'{len(frame)} recommendations created.'); self.refresh_recs()
        except Exception as e: QMessageBox.critical(self,'Failed',str(e))
    def review(self,status):
        rid=self.rec_id()
        if rid:self.service.set_review(rid,status); self.refresh_recs()
    def send(self):
        rid=self.rec_id()
        if not rid:return
        try: QMessageBox.information(self,'Production',f'Project {self.service.send_to_production(rid)} created.'); self.refresh_recs()
        except Exception as e: QMessageBox.warning(self,'Cannot send',str(e))
