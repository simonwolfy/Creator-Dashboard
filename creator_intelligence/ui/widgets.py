from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

class MetricCard(QFrame):
    def __init__(self, title="", value="—", subtitle=""):
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        self.title = QLabel(title)
        self.title.setObjectName("metricTitle")
        self.value = QLabel(value)
        self.value.setObjectName("metricValue")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("metricSubtitle")
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.subtitle)

    def update_value(self, value, subtitle=""):
        self.value.setText(str(value))
        self.subtitle.setText(subtitle)
