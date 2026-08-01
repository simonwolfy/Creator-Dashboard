import pandas as pd
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QTableView,QPushButton,QHBoxLayout
from creator_intelligence.ui.pages.twitch import FrameModel

class ModulesPage(QWidget):
    def __init__(self, registry):
        super().__init__()
        self.registry = registry
        layout = QVBoxLayout(self)
        title = QLabel("Module Architecture")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        description = QLabel(
            "Each feature area is loaded as an independent module. "
            "A failed optional module no longer prevents the rest of the application from starting."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        row = QHBoxLayout()
        refresh = QPushButton("Refresh module status")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        row.addStretch()
        layout.addLayout(row)
        self.table = QTableView()
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self):
        frame = pd.DataFrame(self.registry.module_status())
        self.table.setModel(FrameModel(frame))
