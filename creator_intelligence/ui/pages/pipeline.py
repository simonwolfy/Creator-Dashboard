import pandas as pd
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QComboBox,
    QDialog,QDialogButtonBox,QFormLayout,QLineEdit,QSpinBox,QDoubleSpinBox,
    QPlainTextEdit,QMessageBox,QAbstractItemView
)
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.charts import Chart
from creator_intelligence.services.pipeline_intelligence import STATUSES

class PipelinePage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service=service
        layout=QVBoxLayout(self)
        title=QLabel("Content Production Pipeline"); title.setObjectName("pageTitle")
        layout.addWidget(title)

        row=QHBoxLayout()
        self.filter=QComboBox(); self.filter.addItems(["All"]+STATUSES)
        self.filter.currentTextChanged.connect(self.refresh)
        add=QPushButton("Add content item"); add.clicked.connect(self.add_item)
        edit=QPushButton("Edit selected"); edit.clicked.connect(self.edit_item)
        delete=QPushButton("Delete selected"); delete.clicked.connect(self.delete_item)
        row.addWidget(QLabel("Status")); row.addWidget(self.filter)
        row.addWidget(add); row.addWidget(edit); row.addWidget(delete); row.addStretch()
        layout.addLayout(row)

        self.chart=Chart("Items by workflow stage")
        layout.addWidget(self.chart)
        self.table=QTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self):
        df=self.service.list(self.filter.currentText())
        self.table.setModel(FrameModel(df))
        summary=self.service.status_summary()
        if not summary.empty:
            self.chart.bar(summary["status"],summary["items"],"Items")

    def selected_row(self):
        idx=self.table.currentIndex()
        if not idx.isValid(): return None
        return self.table.model().frame.iloc[idx.row()].to_dict()

    def item_dialog(self,existing=None):
        existing=existing or {}
        dialog=QDialog(self); dialog.setWindowTitle("Content item")
        form=QFormLayout(dialog)
        title=QLineEdit(str(existing.get("title") or ""))
        platform=QComboBox(); platform.addItems(["Twitch","YouTube","Cross-platform"])
        platform.setCurrentText(str(existing.get("platform") or "YouTube"))
        content_type=QComboBox(); content_type.addItems(["Stream","Video","Short","Highlight","Clip","Playlist","Other"])
        content_type.setCurrentText(str(existing.get("content_type") or "Video"))
        topic=QLineEdit(str(existing.get("game_topic") or ""))
        status=QComboBox(); status.addItems(STATUSES); status.setCurrentText(str(existing.get("status") or "Ideas"))
        priority=QComboBox(); priority.addItems(["Low","Normal","High","Critical"])
        priority.setCurrentText(str(existing.get("priority") or "Normal"))
        assignee=QLineEdit(str(existing.get("assignee") or ""))
        due=QLineEdit("" if pd.isna(existing.get("due_date")) else str(existing.get("due_date") or ""))
        progress=QSpinBox(); progress.setRange(0,100); progress.setValue(int(existing.get("progress_percent") or 0))
        stream=QLineEdit(str(existing.get("linked_stream_id") or ""))
        content=QLineEdit(str(existing.get("linked_content_id") or ""))
        planned=QLineEdit("" if pd.isna(existing.get("planned_publish_date")) else str(existing.get("planned_publish_date") or ""))
        actual=QLineEdit("" if pd.isna(existing.get("actual_publish_date")) else str(existing.get("actual_publish_date") or ""))
        editing=QDoubleSpinBox(); editing.setRange(0,10000); editing.setValue(float(existing.get("editing_hours") or 0))
        notes=QPlainTextEdit(str(existing.get("notes") or ""))
        for label,w in [
            ("Title",title),("Platform",platform),("Content type",content_type),
            ("Game/topic",topic),("Status",status),("Priority",priority),
            ("Assignee",assignee),("Due date (YYYY-MM-DD)",due),
            ("Progress %",progress),("Linked stream ID",stream),
            ("Linked content ID",content),("Planned publish date",planned),
            ("Actual publish date",actual),("Editing hours",editing),("Notes",notes)
        ]:
            form.addRow(label,w)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            return {
                "title":title.text(),"platform":platform.currentText(),
                "content_type":content_type.currentText(),"game_topic":topic.text(),
                "status":status.currentText(),"priority":priority.currentText(),
                "assignee":assignee.text(),"due_date":due.text() or None,
                "progress_percent":progress.value(),"linked_stream_id":stream.text() or None,
                "linked_content_id":content.text() or None,
                "planned_publish_date":planned.text() or None,
                "actual_publish_date":actual.text() or None,
                "editing_hours":editing.value(),"notes":notes.toPlainText()
            }
        return None

    def add_item(self):
        values=self.item_dialog()
        if values:
            self.service.save(values)
            self.refresh()

    def edit_item(self):
        row=self.selected_row()
        if not row: return
        values=self.item_dialog(row)
        if values:
            self.service.save(values,int(row["id"]))
            self.refresh()

    def delete_item(self):
        row=self.selected_row()
        if row:
            self.service.delete(int(row["id"]))
            self.refresh()
