import json, pandas as pd
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QAbstractItemView,QMessageBox,QPlainTextEdit
from creator_intelligence.ui.pages.twitch import FrameModel
class OpportunityWorkloadPage(QWidget):
    def __init__(self,service):
        super().__init__(); self.service=service
        layout=QVBoxLayout(self); title=QLabel('VOD Opportunity and Editor Workload'); title.setObjectName('pageTitle'); layout.addWidget(title)
        row=QHBoxLayout()
        for label,fn in [('Score selected VOD',self.score),('Recalculate editor capacity',self.capacity),('Generate assignments',self.assign),('Refresh',self.refresh)]:
            b=QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); layout.addLayout(row)
        self.summary=QPlainTextEdit(); self.summary.setReadOnly(True); self.summary.setMaximumHeight(130); layout.addWidget(self.summary)
        self.transcripts=QTableView(); self.transcripts.setSelectionBehavior(QAbstractItemView.SelectRows); layout.addWidget(self.transcripts)
        self.opportunities=QTableView(); layout.addWidget(self.opportunities)
        self.editors=QTableView(); layout.addWidget(self.editors)
        self.assignments=QTableView(); layout.addWidget(self.assignments)
        self.refresh()
    def transcript_id(self):
        i=self.transcripts.currentIndex(); return int(self.transcripts.model().frame.iloc[i.row()]['id']) if i.isValid() else None
    def refresh(self):
        self.transcripts.setModel(FrameModel(self.service.content_recommendations.highlight_scoring.transcript_service.transcripts()))
        self.opportunities.setModel(FrameModel(self.service.opportunities())); self.editors.setModel(FrameModel(self.service.forecast_editors()))
        self.assignments.setModel(FrameModel(self.service.assignments())); self.summary.setPlainText(json.dumps(self.service.dashboard(),indent=2))
    def score(self):
        tid=self.transcript_id()
        if not tid:return
        try:self.service.calculate_vod(tid); self.refresh()
        except Exception as e:QMessageBox.critical(self,'Scoring failed',str(e))
    def capacity(self):self.service.forecast_editors(); self.refresh()
    def assign(self):
        ids=self.service.generate_assignments(); QMessageBox.information(self,'Assignments',f'{len(ids)} recommendations created.'); self.refresh()
