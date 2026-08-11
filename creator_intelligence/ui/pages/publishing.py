from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.services.publishing_planner import PLATFORMS, PUBLISH_STATUSES
from creator_intelligence.ui.pages.twitch import FrameModel

class PublishingItemDialog(QDialog):
    def __init__(self, production_projects, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Publishing item")
        form=QFormLayout(self)
        self.title=QLineEdit()
        self.platform=QComboBox()
        self.platform.addItems(PLATFORMS)
        self.content_type=QComboBox()
        self.content_type.addItems(
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


class EditedContentDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edited content details")
        self.resize(620, 420)
        form=QFormLayout(self)
        self.title=QLineEdit(str(item.get("title") or ""))
        self.description=QPlainTextEdit(str(item.get("description") or ""))
        self.platform=QComboBox()
        self.platform.addItems(PLATFORMS)
        platform_index=self.platform.findText(str(item.get("platform") or "Multi-platform"))
        self.platform.setCurrentIndex(max(0,platform_index))
        self.content_type=QComboBox()
        self.content_type.addItems(
            ["Long-form","Short","Highlight","Stream VOD","Community post"]
        )
        type_index=self.content_type.findText(str(item.get("content_type") or "Short"))
        self.content_type.setCurrentIndex(max(0,type_index))
        self.publish_at=QLineEdit(str(item.get("planned_publish_at") or ""))
        self.publish_at.setPlaceholderText("Optional: YYYY-MM-DDTHH:MM:SS")
        for label,widget in (
            ("Title",self.title),
            ("Description or caption",self.description),
            ("Platform",self.platform),
            ("Content type",self.content_type),
            ("Preferred publish time",self.publish_at),
        ):
            form.addRow(label,widget)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return {
            "title":self.title.text().strip(),
            "description":self.description.toPlainText().strip() or None,
            "platform":self.platform.currentText(),
            "content_type":self.content_type.currentText(),
            "planned_publish_at":self.publish_at.text().strip() or None,
        }

class PublishingPage(QWidget):
    def __init__(self, service, intake_service=None):
        super().__init__()
        self.service=service
        self.intake=intake_service
        layout=QVBoxLayout(self)
        title=QLabel("Publishing Planner"); title.setObjectName("pageTitle")
        layout.addWidget(title)

        buttons=QHBoxLayout()
        buttons.setSpacing(8)
        for label,handler in (
            ("New item",self.new_item),
            ("Sync approved",self.sync_projects),
        ):
            button=QPushButton(label); button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addWidget(self._menu_button("Schedule", (
            ("Auto-schedule ready items",self.auto_schedule),
            ("Generate selected item deadlines",self.generate_deadlines),
        )))
        buttons.addWidget(self._menu_button("Readiness", (
            ("Change selected item status",self.change_status),
            ("Mark thumbnail ready",lambda:self.update_readiness("thumbnail_status","Ready")),
            ("Mark metadata ready",lambda:self.update_readiness("metadata_status","Ready")),
            ("Mark uploaded",lambda:self.update_readiness("upload_status","Uploaded")),
        )))
        recommendations=QPushButton("Recommendations")
        recommendations.clicked.connect(self.generate_recommendations)
        buttons.addWidget(recommendations)
        buttons.addWidget(self._menu_button("Packages", (
            ("Match package outcomes",self.refresh_outcome_feedback),
            ("Approve selected package",lambda:self.package_decision("Approved")),
            ("Reject selected package",lambda:self.package_decision("Rejected")),
            ("Link selected published post",self.link_selected_package),
        )))
        buttons.addWidget(self._menu_button("Experiments", (
            ("Use selected variant",self.select_variant),
            ("Reject selected variant",self.reject_variant),
        )))
        refresh=QPushButton("Refresh"); refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.tabs=QTabWidget()
        self.items_table=QTableView()
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.items_table,"Publishing queue")
        self.intake_table=None
        if self.intake is not None:
            self.intake_tab=QWidget()
            intake_layout=QVBoxLayout(self.intake_tab)
            intake_actions=QHBoxLayout()
            for label,handler in (
                ("Add ready-to-publish folder",self.add_intake_folder),
                ("Scan folders",self.scan_intake_folders),
                ("Edit selected",self.edit_intake_item),
                ("Approve",self.approve_intake_items),
                ("Schedule selected",self.schedule_intake_items),
                ("Reject",self.reject_intake_items),
                ("Connect published content",self.connect_intake_content),
            ):
                button=QPushButton(label)
                button.clicked.connect(handler)
                intake_actions.addWidget(button)
            intake_actions.addStretch()
            intake_layout.addLayout(intake_actions)
            intake_note=QLabel(
                "Files are indexed without being moved or deleted. New videos are neutral "
                "learning evidence until you approve, reject, publish, or connect their statistics."
            )
            intake_note.setWordWrap(True)
            intake_layout.addWidget(intake_note)
            self.intake_table=QTableView()
            self.intake_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.intake_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.intake_table.doubleClicked.connect(lambda _:self.edit_intake_item())
            intake_layout.addWidget(self.intake_table)
            self.tabs.addTab(self.intake_tab,"Edited Content Inbox")
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

    def _menu_button(self, label, actions):
        button=QToolButton(self)
        button.setText(label)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu=QMenu(button)
        for action_label,handler in actions:
            action=menu.addAction(action_label)
            action.triggered.connect(handler)
        button.setMenu(menu)
        return button

    def selected_item_id(self):
        index=self.items_table.currentIndex()
        if not index.isValid(): return None
        return int(self.items_table.model().frame.iloc[index.row()]["id"])

    def open_item(self, item_id):
        """Select a publishing item when another workflow links into this page."""
        self.refresh()
        model=self.items_table.model()
        if model is None or model.frame.empty:return
        matches=model.frame.index[model.frame["id"]==int(item_id)].tolist()
        if not matches:return
        row=int(matches[0])
        self.items_table.selectRow(row)
        self.items_table.setCurrentIndex(model.index(row,0))
        self.refresh_dependencies()
        self.tabs.setCurrentWidget(self.items_table)

    def open_outcomes(self, package_id=None, *, prompt_link=False):
        """Open package outcomes and optionally begin linking a synced post."""
        self.refresh()
        self.tabs.setCurrentWidget(self.outcomes_table)
        if package_id is None:
            return
        model = self.outcomes_table.model()
        if model is None or model.frame.empty:
            return
        matches = model.frame.index[
            model.frame["id"].astype(str) == str(package_id)
        ].tolist()
        if not matches:
            return
        row = int(matches[0])
        self.outcomes_table.selectRow(row)
        self.outcomes_table.setCurrentIndex(model.index(row, 0))
        if prompt_link:
            self.link_selected_package()

    def refresh(self):
        self.items_table.setModel(FrameModel(self.service.items()))
        if self.intake is not None and self.intake_table is not None:
            frame=self.intake.items().rename(columns={
                "content_type":"Content type",
                "learning_status":"Learning",
                "planned_publish_at":"Publish time",
                "publishing_status":"Publishing status",
                "file_name":"File",
                "file_status":"File status",
                "duration_seconds":"Duration seconds",
                "source_content_id":"Published content ID",
            })
            self.intake_table.setModel(FrameModel(frame))
        self.calendar_table.setModel(FrameModel(self.service.calendar()))
        self.recommendations_table.setModel(FrameModel(self.service.recommendations()))
        self.slots_table.setModel(FrameModel(self.service.slots()))
        self.insights_table.setModel(FrameModel(self.service.timing_insights()))
        self.outcomes_table.setModel(FrameModel(self.service.outcome_dashboard()))
        self.experiments_table.setModel(FrameModel(self.service.experiment_dashboard()))
        self.patterns_table.setModel(FrameModel(self.service.experiment_patterns()))
        self.refresh_variants()
        self.refresh_dependencies()

    def selected_intake_ids(self):
        if self.intake_table is None or self.intake_table.model() is None:
            return []
        selection=self.intake_table.selectionModel()
        rows=selection.selectedRows() if selection is not None else []
        if not rows and self.intake_table.currentIndex().isValid():
            rows=[self.intake_table.currentIndex()]
        frame=self.intake_table.model().frame
        return [int(frame.iloc[index.row()]["id"]) for index in rows]

    def add_intake_folder(self):
        path=QFileDialog.getExistingDirectory(self,"Choose a folder of edited videos")
        if not path:
            return
        try:
            folder_id=self.intake.add_folder(path)
            result=self.intake.scan_folder(folder_id)
            QMessageBox.information(
                self,"Edited content imported",
                f"Added {result['intake_created']} new video(s); ignored "
                f"{result['duplicates']} duplicate(s)."
            )
        except Exception as exc:
            QMessageBox.warning(self,"Unable to add folder",str(exc))
        self.refresh()

    def scan_intake_folders(self):
        try:
            result=self.intake.scan_all()
            QMessageBox.information(
                self,"Edited content scan",
                f"Scanned {result['folders']} folder(s). Added {result['intake_created']} "
                f"video(s), updated {result['updated']}, and ignored "
                f"{result['duplicates']} duplicate(s)."
            )
        except Exception as exc:
            QMessageBox.warning(self,"Unable to scan folders",str(exc))
        self.refresh()

    def edit_intake_item(self):
        ids=self.selected_intake_ids()
        if len(ids)!=1:
            QMessageBox.information(self,"Edit video","Select one edited video to edit.")
            return
        item=self.intake.item(ids[0])
        dialog=EditedContentDialog(item,self)
        if dialog.exec() and dialog.values()["title"]:
            try:
                self.intake.update_item(ids[0],**dialog.values())
            except Exception as exc:
                QMessageBox.warning(self,"Unable to update video",str(exc))
        self.refresh()

    def approve_intake_items(self):
        ids=self.selected_intake_ids()
        for intake_id in ids:
            self.intake.approve(intake_id)
        if ids:
            QMessageBox.information(self,"Edited content",f"Approved {len(ids)} video(s).")
        self.refresh()

    def schedule_intake_items(self):
        ids=self.selected_intake_ids()
        try:
            for intake_id in ids:
                self.intake.schedule(intake_id)
        except Exception as exc:
            QMessageBox.warning(self,"Unable to schedule video",str(exc))
        else:
            if ids:
                QMessageBox.information(self,"Edited content",f"Scheduled {len(ids)} video(s).")
        self.refresh()

    def reject_intake_items(self):
        ids=self.selected_intake_ids()
        for intake_id in ids:
            self.intake.reject(intake_id)
        if ids:
            QMessageBox.information(self,"Edited content",f"Rejected {len(ids)} video(s).")
        self.refresh()

    def connect_intake_content(self):
        ids=self.selected_intake_ids()
        if len(ids)!=1:
            QMessageBox.information(self,"Connect published content","Select one edited video.")
            return
        source_id,ok=QInputDialog.getText(
            self,"Connect published content","Synced platform content ID:"
        )
        if not ok or not source_id.strip():
            return
        try:
            self.intake.connect_published_content(ids[0],source_id.strip())
        except Exception as exc:
            QMessageBox.warning(self,"Unable to connect content",str(exc))
        self.refresh()

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
