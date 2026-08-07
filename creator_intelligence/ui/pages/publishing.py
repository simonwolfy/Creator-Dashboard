from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QTabWidget,
    QAbstractItemView,QMessageBox,QInputDialog,QDialog,QFormLayout,QLineEdit,
    QComboBox,QDialogButtonBox
)
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.services.publishing_planner import PLATFORMS,PUBLISH_STATUSES

class PublishingItemDialog(QDialog):
    def __init__(self, production_projects, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Publishing item")
        form=QFormLayout(self)
        self.title=QLineEdit()
        self.platform=QComboBox(); self.platform.addItems(PLATFORMS)
        self.content_type=QComboBox(); self.content_type.addItems(
            ["Long-form","Short","Highlight","Stream VOD","Community post"]
        )
        self.status=QComboBox(); self.status.addItems(PUBLISH_STATUSES)
        self.project=QComboBox(); self.project.addItem("No linked project",None)
        for project in production_projects:
            self.project.addItem(project["title"],int(project["id"]))
        self.publish_at=QLineEdit()
        self.publish_at.setPlaceholderText("YYYY-MM-DDTHH:MM:SS")
        for label,widget in [
            ("Title",self.title),("Platform",self.platform),
            ("Content type",self.content_type),("Status",self.status),
            ("Production project",self.project),
            ("Planned publish time",self.publish_at)
        ]:
            form.addRow(label,widget)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return {
            "title":self.title.text().strip(),
            "platform":self.platform.currentText(),
            "content_type":self.content_type.currentText(),
            "status":self.status.currentText(),
            "production_project_id":self.project.currentData(),
            "planned_publish_at":self.publish_at.text().strip() or None,
            "score":50,
            "confidence":0.5,
            "description_status":"Missing",
            "thumbnail_status":"Missing",
            "metadata_status":"Missing",
            "upload_status":"Not uploaded"
        }

class PublishingPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service=service
        layout=QVBoxLayout(self)
        title=QLabel("Publishing Planner"); title.setObjectName("pageTitle")
        layout.addWidget(title)

        buttons=QHBoxLayout()
        actions=[
            ("New publishing item",self.new_item),
            ("Sync approved projects",self.sync_projects),
            ("Auto-schedule ready",self.auto_schedule),
            ("Generate deadlines",self.generate_deadlines),
            ("Change status",self.change_status),
            ("Mark thumbnail ready",lambda:self.update_readiness("thumbnail_status","Ready")),
            ("Mark metadata ready",lambda:self.update_readiness("metadata_status","Ready")),
            ("Mark uploaded",lambda:self.update_readiness("upload_status","Uploaded")),
            ("Generate recommendations",self.generate_recommendations),
            ("Match package outcomes",self.refresh_outcome_feedback),
            ("Approve package",lambda:self.package_decision("Approved")),
            ("Reject package",lambda:self.package_decision("Rejected")),
            ("Link published post",self.link_selected_package),
            ("Use experiment variant",self.select_variant),
            ("Reject experiment variant",self.reject_variant),
            ("Refresh",self.refresh)
        ]
        for label,handler in actions:
            button=QPushButton(label); button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.tabs=QTabWidget()
        self.items_table=QTableView()
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.items_table,"Publishing queue")
        self.calendar_table=QTableView()
        self.tabs.addTab(self.calendar_table,"30-day calendar")
        self.dependencies_table=QTableView()
        self.tabs.addTab(self.dependencies_table,"Selected item dependencies")
        self.recommendations_table=QTableView()
        self.tabs.addTab(self.recommendations_table,"Recommendations")
        self.slots_table=QTableView()
        self.tabs.addTab(self.slots_table,"Recurring slots")
        self.insights_table=QTableView()
        self.tabs.addTab(self.insights_table,"Timing insights")
        self.outcomes_table=QTableView()
        self.outcomes_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.outcomes_table,"Package outcomes")
        self.experiments_table=QTableView()
        self.experiments_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.experiments_table,"Packaging experiments")
        self.variants_table=QTableView()
        self.variants_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.variants_table,"Selected experiment variants")
        self.patterns_table=QTableView()
        self.tabs.addTab(self.patterns_table,"Winning patterns")
        layout.addWidget(self.tabs)
        self.items_table.clicked.connect(lambda _:self.refresh_dependencies())
        self.experiments_table.clicked.connect(lambda _:self.refresh_variants())
        self.refresh()

    def selected_item_id(self):
        index=self.items_table.currentIndex()
        if not index.isValid(): return None
        return int(self.items_table.model().frame.iloc[index.row()]["id"])

    def refresh(self):
        self.items_table.setModel(FrameModel(self.service.items()))
        self.calendar_table.setModel(FrameModel(self.service.calendar()))
        self.recommendations_table.setModel(FrameModel(self.service.recommendations()))
        self.slots_table.setModel(FrameModel(self.service.slots()))
        self.insights_table.setModel(FrameModel(self.service.timing_insights()))
        self.outcomes_table.setModel(FrameModel(self.service.outcome_dashboard()))
        self.experiments_table.setModel(FrameModel(self.service.experiment_dashboard()))
        self.patterns_table.setModel(FrameModel(self.service.experiment_patterns()))
        self.refresh_variants()
        self.refresh_dependencies()

    def selected_experiment_id(self):
        index=self.experiments_table.currentIndex()
        if not index.isValid(): return None
        return str(self.experiments_table.model().frame.iloc[index.row()]["id"])

    def selected_variant_id(self):
        index=self.variants_table.currentIndex()
        if not index.isValid(): return None
        return str(self.variants_table.model().frame.iloc[index.row()]["id"])

    def refresh_variants(self):
        experiment_id=self.selected_experiment_id()
        if not experiment_id:
            import pandas as pd
            self.variants_table.setModel(FrameModel(pd.DataFrame()))
            return
        self.variants_table.setModel(FrameModel(self.service.experiment_variants(experiment_id)))

    def select_variant(self):
        variant_id=self.selected_variant_id()
        if variant_id:
            self.service.select_experiment_variant(variant_id)
            self.refresh()

    def reject_variant(self):
        variant_id=self.selected_variant_id()
        if variant_id:
            self.service.reject_experiment_variant(variant_id)
            self.refresh()

    def selected_package_id(self):
        index=self.outcomes_table.currentIndex()
        if not index.isValid(): return None
        return str(self.outcomes_table.model().frame.iloc[index.row()]["id"])

    def refresh_outcome_feedback(self):
        result=self.service.refresh_outcomes()
        summary=self.service.outcome_summary()
        QMessageBox.information(
            self,"Publishing outcomes",
            f"Matched {result['matched']} package(s) and captured {result['snapshots']} checkpoint(s).\n"
            f"{summary['matched']} matched, {summary['pending']} pending, {summary['measured']} measured."
        )
        self.refresh()

    def package_decision(self,status):
        package_id=self.selected_package_id()
        if package_id:
            self.service.set_package_decision(package_id,status)
            self.refresh()

    def link_selected_package(self):
        package_id=self.selected_package_id()
        if not package_id: return
        source_id,ok=QInputDialog.getText(self,"Link published post","Synced platform post ID:")
        if not ok or not source_id.strip(): return
        try:
            self.service.link_package(package_id,source_id.strip())
        except Exception as exc:
            QMessageBox.warning(self,"Cannot link post",str(exc)); return
        self.refresh()

    def refresh_dependencies(self):
        item_id=self.selected_item_id()
        if not item_id:
            import pandas as pd
            self.dependencies_table.setModel(FrameModel(pd.DataFrame()))
            return
        self.dependencies_table.setModel(
            FrameModel(self.service.dependencies(item_id))
        )

    def new_item(self):
        projects=[]
        if self.service.production_service:
            projects=self.service.production_service.projects().to_dict("records")
        dialog=PublishingItemDialog(projects,self)
        if dialog.exec() and dialog.values()["title"]:
            self.service.create_item(dialog.values())
            self.refresh()

    def sync_projects(self):
        count=self.service.synchronize_production()
        QMessageBox.information(
            self,"Production sync",f"{count} publishing items were created."
        )
        self.refresh()

    def auto_schedule(self):
        ids=self.service.auto_schedule_ready_items()
        QMessageBox.information(
            self,"Auto-schedule",f"{len(ids)} ready items were scheduled."
        )
        self.refresh()

    def generate_deadlines(self):
        item_id=self.selected_item_id()
        if not item_id: return
        try:
            count=self.service.propagate_deadlines(item_id)
            QMessageBox.information(
                self,"Deadlines generated",f"{count} dependencies were added."
            )
            self.refresh_dependencies()
        except Exception as exc:
            QMessageBox.warning(self,"Cannot generate deadlines",str(exc))

    def change_status(self):
        item_id=self.selected_item_id()
        if not item_id: return
        status,ok=QInputDialog.getItem(
            self,"Publishing status","Status",PUBLISH_STATUSES,0,False
        )
        if ok:
            self.service.update_item(item_id,status=status)
            self.refresh()

    def update_readiness(self,field,value):
        item_id=self.selected_item_id()
        if not item_id: return
        self.service.update_item(item_id,**{field:value})
        self.refresh()

    def generate_recommendations(self):
        recommendations=self.service.generate_recommendations()
        QMessageBox.information(
            self,"Recommendations",
            f"{len(recommendations)} publishing recommendations were generated."
        )
        self.refresh()
