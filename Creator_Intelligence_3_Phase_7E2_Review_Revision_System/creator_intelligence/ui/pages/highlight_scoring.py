import json, pandas as pd
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QAbstractItemView,QMessageBox,QInputDialog,QPlainTextEdit
from creator_intelligence.ui.pages.twitch import FrameModel
class HighlightScoringPage(QWidget):
    def __init__(self,service):
        super().__init__();self.service=service;layout=QVBoxLayout(self);title=QLabel('Highlight Scoring Engine');title.setObjectName('pageTitle');layout.addWidget(title)
        row=QHBoxLayout()
        for label,fn in [('Generate highlights',self.generate),('Approve',lambda:self.review('Approved')),('Reject',lambda:self.review('Rejected')),('Needs changes',lambda:self.review('Needs changes')),('Override score',self.override),('Edit boundaries',self.boundaries),('Merge IDs',self.merge),('Send to production',self.send),('Refresh',self.refresh)]:
            b=QPushButton(label);b.clicked.connect(fn);row.addWidget(b)
        row.addStretch();layout.addLayout(row);self.summary=QPlainTextEdit();self.summary.setReadOnly(True);self.summary.setMaximumHeight(140);layout.addWidget(self.summary)
        self.transcripts=QTableView();self.transcripts.setSelectionBehavior(QAbstractItemView.SelectRows);layout.addWidget(self.transcripts)
        self.highlights=QTableView();self.highlights.setSelectionBehavior(QAbstractItemView.SelectRows);layout.addWidget(self.highlights);self.transcripts.clicked.connect(lambda _:self.refresh_highlights());self.refresh()
    def tid(self):
        i=self.transcripts.currentIndex();return None if not i.isValid() else int(self.transcripts.model().frame.iloc[i.row()]['id'])
    def hid(self):
        i=self.highlights.currentIndex();return None if not i.isValid() else int(self.highlights.model().frame.iloc[i.row()]['id'])
    def refresh(self):self.transcripts.setModel(FrameModel(self.service.transcript_service.transcripts()));self.refresh_highlights()
    def refresh_highlights(self):
        tid=self.tid()
        if not tid:self.highlights.setModel(FrameModel(pd.DataFrame()));self.summary.setPlainText('Select a transcript.');return
        self.highlights.setModel(FrameModel(self.service.highlights(tid)));self.summary.setPlainText(json.dumps(self.service.opportunity_summary(tid),indent=2,default=str))
    def generate(self):
        tid=self.tid()
        if not tid:return
        score,ok=QInputDialog.getDouble(self,'Minimum score','Minimum highlight score',35,0,100,1)
        if ok:
            try:f=self.service.generate(tid,minimum_score=score);QMessageBox.information(self,'Generated',f'{len(f)} ranked highlights were created.');self.refresh_highlights()
            except Exception as e:QMessageBox.critical(self,'Failed',str(e))
    def review(self,status):
        hid=self.hid()
        if not hid:return
        notes,ok=QInputDialog.getMultiLineText(self,'Review notes',f'{status} notes')
        if ok:self.service.set_review(hid,status,notes or None);self.refresh_highlights()
    def override(self):
        hid=self.hid()
        if not hid:return
        val,ok=QInputDialog.getDouble(self,'Override score','Score',80,0,100,1)
        if ok:
            h=self.service.highlight(hid);self.service.set_review(hid,h['review_status'],h.get('reviewer_notes'),val);self.refresh_highlights()
    def boundaries(self):
        hid=self.hid()
        if not hid:return
        h=self.service.highlight(hid);s,ok=QInputDialog.getDouble(self,'Start','Start seconds',float(h['start_seconds']),0,999999,1)
        if not ok:return
        p,ok=QInputDialog.getDouble(self,'Peak','Peak seconds',float(h['peak_seconds']),s,999999,1)
        if not ok:return
        e,ok=QInputDialog.getDouble(self,'End','End seconds',float(h['end_seconds']),p,999999,1)
        if ok:self.service.update_boundaries(hid,s,p,e);self.refresh_highlights()
    def merge(self):
        text,ok=QInputDialog.getText(self,'Merge highlights','Comma-separated highlight IDs')
        if ok and text:
            try:self.service.merge([int(x.strip()) for x in text.split(',') if x.strip()]);self.refresh_highlights()
            except Exception as e:QMessageBox.critical(self,'Merge failed',str(e))
    def send(self):
        hid=self.hid()
        if not hid:return
        try:pid=self.service.send_to_production(hid);QMessageBox.information(self,'Production project',f'Project {pid} was created.');self.refresh_highlights()
        except Exception as e:QMessageBox.warning(self,'Cannot send',str(e))
