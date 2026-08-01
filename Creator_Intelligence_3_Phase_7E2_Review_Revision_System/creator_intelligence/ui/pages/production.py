from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QTabWidget,
    QAbstractItemView,QMessageBox,QInputDialog,QComboBox,QSpinBox,QFormLayout,
    QDialog,QDialogButtonBox,QLineEdit,QDoubleSpinBox,QTextEdit
)
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.services.production_management import PROJECT_STATUSES

class ProjectDialog(QDialog):
    def __init__(self, editors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Production project")
        form = QFormLayout(self)
        self.title = QLineEdit()
        self.series = QLineEdit()
        self.episode = QLineEdit()
        self.platform = QComboBox(); self.platform.addItems(["YouTube","TikTok","Multi-platform"])
        self.content_type = QComboBox(); self.content_type.addItems(["Long-form","Short","Highlight","Stream VOD"])
        self.game = QLineEdit()
        self.status = QComboBox(); self.status.addItems(PROJECT_STATUSES)
        self.priority = QComboBox(); self.priority.addItems(["Critical","High","Normal","Low"])
        self.editor = QComboBox(); self.editor.addItem("Unassigned",None)
        for editor in editors:
            self.editor.addItem(editor["name"],int(editor["id"]))
        self.folder = QLineEdit()
        self.notes = QTextEdit()
        for label,widget in [
            ("Title",self.title),("Series",self.series),("Episode",self.episode),
            ("Platform",self.platform),("Content type",self.content_type),
            ("Game/topic",self.game),("Status",self.status),("Priority",self.priority),
            ("Editor",self.editor),("Project folder URL",self.folder),("Notes",self.notes)
        ]:
            form.addRow(label,widget)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return {
            "title":self.title.text().strip(),
            "series_name":self.series.text().strip() or None,
            "episode_number":self.episode.text().strip() or None,
            "platform":self.platform.currentText(),
            "content_type":self.content_type.currentText(),
            "game_topic":self.game.text().strip() or None,
            "status":self.status.currentText(),
            "priority":self.priority.currentText(),
            "editor_id":self.editor.currentData(),
            "folder_url":self.folder.text().strip() or None,
            "notes":self.notes.toPlainText().strip() or None
        }

class ProductionPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service=service
        layout=QVBoxLayout(self)
        title=QLabel("Production Management"); title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.summary=QLabel()
        layout.addWidget(self.summary)

        buttons=QHBoxLayout()
        for label,handler in [
            ("New project",self.new_project),("Add editor",self.add_editor),
            ("Change status",self.change_status),("Assign editor",self.assign_editor),
            ("Add asset",self.add_asset),("Add delivery",self.add_delivery),
            ("Add review note",self.add_review_note),
            ("Request revision",self.request_revision),
            ("Approve final",self.approve_final),("Refresh",self.refresh)
        ]:
            button=QPushButton(label); button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.tabs=QTabWidget()
        self.projects_table=QTableView()
        self.projects_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.projects_table,"Projects")
        self.workload_table=QTableView()
        self.tabs.addTab(self.workload_table,"Editor workload")
        self.recommendations_table=QTableView()
        self.tabs.addTab(self.recommendations_table,"Recommended actions")
        self.assets_table=QTableView()
        self.tabs.addTab(self.assets_table,"Selected project assets")
        self.deliveries_table=QTableView()
        self.tabs.addTab(self.deliveries_table,"Selected project deliveries")
        self.notes_table=QTableView()
        self.tabs.addTab(self.notes_table,"Selected project review notes")
        layout.addWidget(self.tabs)
        self.projects_table.selectionModelChanged = None
        self.projects_table.clicked.connect(lambda _:self.refresh_project_details())
        self.refresh()

    def selected_project_id(self):
        index=self.projects_table.currentIndex()
        if not index.isValid(): return None
        return int(self.projects_table.model().frame.iloc[index.row()]["id"])

    def refresh(self):
        dashboard=self.service.dashboard()
        self.summary.setText(
            f'Active: {dashboard["active_projects"]}   |   '
            f'Waiting on editor: {dashboard["waiting_for_editor"]}   |   '
            f'Needs your review: {dashboard["needs_creator_review"]}   |   '
            f'Revisions: {dashboard["revision_requested"]}   |   '
            f'Ready to publish: {dashboard["ready_to_publish"]}'
        )
        self.projects_table.setModel(FrameModel(self.service.projects()))
        self.workload_table.setModel(FrameModel(self.service.workload()))
        import pandas as pd
        self.recommendations_table.setModel(
            FrameModel(pd.DataFrame(self.service.recommendations()))
        )
        self.refresh_project_details()

    def refresh_project_details(self):
        project_id=self.selected_project_id()
        if not project_id:
            import pandas as pd
            blank=FrameModel(pd.DataFrame())
            self.assets_table.setModel(blank)
            self.deliveries_table.setModel(FrameModel(pd.DataFrame()))
            self.notes_table.setModel(FrameModel(pd.DataFrame()))
            return
        self.assets_table.setModel(FrameModel(self.service.assets(project_id)))
        self.deliveries_table.setModel(FrameModel(self.service.deliveries(project_id)))
        self.notes_table.setModel(FrameModel(self.service.review_notes(project_id)))

    def new_project(self):
        editors=self.service.editors(active_only=True).to_dict("records")
        dialog=ProjectDialog(editors,self)
        if dialog.exec() and dialog.values()["title"]:
            self.service.create_project(dialog.values())
            self.refresh()

    def add_editor(self):
        name,ok=QInputDialog.getText(self,"Add editor","Editor name")
        if not ok or not name.strip(): return
        specialty,ok=QInputDialog.getText(self,"Editor specialty","Specialty")
        if ok:
            capacity,ok2=QInputDialog.getDouble(
                self,"Weekly capacity","Target projects per week",2,0.1,50,1
            )
            if ok2:
                self.service.create_editor(name.strip(),specialty=specialty or None,
                                           target_weekly_capacity=capacity)
                self.refresh()

    def change_status(self):
        project_id=self.selected_project_id()
        if not project_id: return
        status,ok=QInputDialog.getItem(
            self,"Change status","Status",PROJECT_STATUSES,0,False
        )
        if ok:
            self.service.update_project(project_id,status=status)
            self.refresh()

    def assign_editor(self):
        project_id=self.selected_project_id()
        if not project_id: return
        editors=self.service.editors(active_only=True)
        if editors.empty:
            QMessageBox.warning(self,"No editors","Add an editor first.")
            return
        labels=editors["name"].tolist()
        label,ok=QInputDialog.getItem(self,"Assign editor","Editor",labels,0,False)
        if ok:
            editor_id=int(editors[editors["name"]==label].iloc[0]["id"])
            self.service.assign_editor(project_id,editor_id)
            self.refresh()

    def add_asset(self):
        project_id=self.selected_project_id()
        if not project_id: return
        label,ok=QInputDialog.getText(self,"Add asset","Asset label")
        if ok and label:
            asset_type,ok2=QInputDialog.getItem(
                self,"Asset type","Type",
                ["Raw footage","Facecam","Audio","Thumbnail","Music","Script","Other"],0,False
            )
            if ok2:
                self.service.add_asset(project_id,asset_type,label)
                self.refresh_project_details()

    def add_delivery(self):
        project_id=self.selected_project_id()
        if not project_id: return
        version,ok=QInputDialog.getText(self,"Add editor delivery","Version label","v1")
        if ok and version:
            location,ok2=QInputDialog.getText(self,"File location","URL or file path")
            if ok2:
                self.service.add_delivery(project_id,version,location or None)
                self.refresh()

    def add_review_note(self):
        project_id=self.selected_project_id()
        if not project_id: return
        timestamp,ok=QInputDialog.getInt(
            self,"Review timestamp","Seconds into video",0,0,999999
        )
        if not ok: return
        comment,ok=QInputDialog.getMultiLineText(
            self,"Review note","Requested change"
        )
        if ok and comment:
            self.service.add_review_note(project_id,comment,timestamp)
            self.refresh_project_details()

    def request_revision(self):
        project_id=self.selected_project_id()
        if not project_id: return
        notes,ok=QInputDialog.getMultiLineText(
            self,"Request revision","Revision summary"
        )
        if ok:
            self.service.request_revision(project_id,notes or None)
            self.refresh()

    def approve_final(self):
        project_id=self.selected_project_id()
        if not project_id: return
        try:
            self.service.approve_final(project_id)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self,"Cannot approve",str(exc))
