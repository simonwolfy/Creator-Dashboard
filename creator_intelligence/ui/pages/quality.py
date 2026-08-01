from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QPushButton,QTableView
from creator_intelligence.ui.pages.twitch import FrameModel

class QualityPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service=service
        layout=QVBoxLayout(self)
        title=QLabel("Data Quality Center"); title.setObjectName("pageTitle"); layout.addWidget(title)
        button=QPushButton("Run full scan"); button.clicked.connect(self.scan); layout.addWidget(button)
        self.view=QTableView(); layout.addWidget(self.view); self.scan()

    def scan(self):
        self.view.setModel(FrameModel(self.service.scan()))
