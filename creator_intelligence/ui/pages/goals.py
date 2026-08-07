from datetime import datetime
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,QDoubleSpinBox,QPushButton,QTableView
from creator_intelligence.ui.pages.twitch import FrameModel

class GoalsPage(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db=db
        layout=QVBoxLayout(self)
        title=QLabel("Goals and Progress"); title.setObjectName("pageTitle"); layout.addWidget(title)
        row=QHBoxLayout()
        self.period=QLineEdit(datetime.now().strftime("%Y-%m"))
        self.platform=QComboBox(); self.platform.addItems(["Twitch","YouTube","Combined"])
        self.metric_selector=QComboBox(); self.metric_selector.addItems(["average_viewers","followers","stream_hours","views","subscribers","revenue","shorts_published","videos_published"])
        self.target=QDoubleSpinBox(); self.target.setRange(0,100000000); self.target.setDecimals(2)
        button=QPushButton("Save goal"); button.clicked.connect(self.save)
        for label,w in [("Period",self.period),("Platform",self.platform),("Metric",self.metric_selector),("Target",self.target)]:
            row.addWidget(QLabel(label)); row.addWidget(w)
        row.addWidget(button); layout.addLayout(row)
        self.view=QTableView(); layout.addWidget(self.view); self.refresh()

    def save(self):
        self.db.execute("""INSERT INTO creator_goals(period,metric,target,platform,created_at)
            VALUES(?,?,?,?,datetime('now'))
            ON CONFLICT(period,metric,platform) DO UPDATE SET target=excluded.target""",
            (self.period.text(),self.metric_selector.currentText(),self.target.value(),self.platform.currentText()))
        self.refresh()

    def refresh(self):
        self.view.setModel(FrameModel(self.db.frame("SELECT * FROM creator_goals ORDER BY period DESC, platform, metric")))
