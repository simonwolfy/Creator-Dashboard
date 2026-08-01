from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,
    QAbstractItemView,QMessageBox,QCheckBox
)
from creator_intelligence.ui.pages.twitch import FrameModel

class NotificationsPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service=service
        layout=QVBoxLayout(self)
        title=QLabel("Notification Center")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        row=QHBoxLayout()
        self.unread_only=QCheckBox("Unread only")
        self.unread_only.toggled.connect(self.refresh)
        refresh=QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        mark=QPushButton("Mark selected read")
        mark.clicked.connect(self.mark_selected)
        mark_all=QPushButton("Mark all read")
        mark_all.clicked.connect(self.mark_all)
        dismiss=QPushButton("Dismiss selected")
        dismiss.clicked.connect(self.dismiss_selected)
        row.addWidget(self.unread_only); row.addWidget(refresh)
        row.addWidget(mark); row.addWidget(mark_all); row.addWidget(dismiss)
        row.addStretch()
        layout.addLayout(row)

        self.count_label=QLabel()
        layout.addWidget(self.count_label)
        self.table=QTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)
        self.refresh()

    def selected_id(self):
        idx=self.table.currentIndex()
        if not idx.isValid(): return None
        return int(self.table.model().frame.iloc[idx.row()]["id"])

    def refresh(self):
        frame=self.service.list(unread_only=self.unread_only.isChecked())
        self.table.setModel(FrameModel(frame))
        self.count_label.setText(f"Unread notifications: {self.service.unread_count()}")

    def mark_selected(self):
        item_id=self.selected_id()
        if item_id:
            self.service.mark_read(item_id)
            self.refresh()

    def mark_all(self):
        self.service.mark_all_read()
        self.refresh()

    def dismiss_selected(self):
        item_id=self.selected_id()
        if item_id:
            self.service.dismiss(item_id)
            self.refresh()
