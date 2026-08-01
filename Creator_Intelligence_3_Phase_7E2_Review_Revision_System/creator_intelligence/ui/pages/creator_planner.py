from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QTabWidget,
    QAbstractItemView,QMessageBox,QInputDialog,QDialog,QFormLayout,QLineEdit,
    QComboBox,QDialogButtonBox,QSpinBox
)
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.services.creator_planner import (
    SOURCE_TYPES,DELIVERABLE_TYPES
)

class SourceDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle("Content source")
        form=QFormLayout(self)
        self.source_type=QComboBox(); self.source_type.addItems(SOURCE_TYPES)
        self.title=QLineEdit()
        self.platform=QLineEdit("Twitch")
        self.game=QLineEdit()
        self.location=QLineEdit()
        self.duration=QSpinBox(); self.duration.setRange(0,24*3600)
        self.duration.setSuffix(" seconds")
        for label,widget in [
            ("Source type",self.source_type),("Title",self.title),
            ("Platform",self.platform),("Game/topic",self.game),
            ("URL or file path",self.location),("Duration",self.duration)
        ]:
            form.addRow(label,widget)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        source_type=self.source_type.currentText()
        location=self.location.text().strip() or None
        return {
            "source_type":source_type,
            "title":self.title.text().strip(),
            "platform":self.platform.text().strip() or None,
            "game_topic":self.game.text().strip() or None,
            "source_url":location if location and "://" in location else None,
            "local_path":location if location and "://" not in location else None,
            "recorded_at":None,
            "duration_seconds":self.duration.value() or None,
            "status":"Available"
        }

class CreatorPlannerPage(QWidget):
    def __init__(self,service):
        super().__init__()
        self.service=service
        layout=QVBoxLayout(self)
        title=QLabel("Creator Planner — VOD First"); title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.summary=QLabel()
        layout.addWidget(self.summary)
        self.advice=QLabel()
        self.advice.setWordWrap(True)
        layout.addWidget(self.advice)

        buttons=QHBoxLayout()
        actions=[
            ("Add content source",self.add_source),
            ("Suggest VOD deliverables",self.suggest_deliverables),
            ("Add deliverable",self.add_deliverable),
            ("Send deliverable to production",self.to_production),
            ("Generate daily plan",self.generate_plan),
            ("Refresh",self.refresh)
        ]
        for label,handler in actions:
            button=QPushButton(label); button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.tabs=QTabWidget()
        self.sources_table=QTableView()
        self.sources_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.sources_table,"Content sources")
        self.deliverables_table=QTableView()
        self.deliverables_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabs.addTab(self.deliverables_table,"Deliverables")
        self.actions_table=QTableView()
        self.tabs.addTab(self.actions_table,"Today's plan")
        self.yield_table=QTableView()
        self.tabs.addTab(self.yield_table,"Source yield")
        self.goals_table=QTableView()
        self.tabs.addTab(self.goals_table,"Goals")
        layout.addWidget(self.tabs)
        self.sources_table.clicked.connect(lambda _:self.refresh_deliverables())
        self.refresh()

    def selected_source_id(self):
        index=self.sources_table.currentIndex()
        if not index.isValid(): return None
        return int(self.sources_table.model().frame.iloc[index.row()]["id"])

    def selected_deliverable_id(self):
        index=self.deliverables_table.currentIndex()
        if not index.isValid(): return None
        return int(self.deliverables_table.model().frame.iloc[index.row()]["id"])

    def refresh(self):
        summary=self.service.command_center()
        self.summary.setText(
            f'VODs: {summary["stream_vods"]}   |   '
            f'Dedicated recordings: {summary["dedicated_recordings"]}   |   '
            f'Suggested deliverables: {summary["suggested_deliverables"]}   |   '
            f'Waiting on editor: {summary["waiting_on_editor"]}   |   '
            f'Needs review: {summary["waiting_on_creator_review"]}   |   '
            f'Ready to schedule: {summary["ready_to_schedule"]}'
        )
        self.advice.setText("\n".join(self.service.if_i_were_you()))
        self.sources_table.setModel(FrameModel(self.service.sources()))
        self.actions_table.setModel(FrameModel(self.service.actions()))
        self.yield_table.setModel(FrameModel(self.service.source_yield()))
        self.goals_table.setModel(FrameModel(self.service.goals()))
        self.refresh_deliverables()

    def refresh_deliverables(self):
        source_id=self.selected_source_id()
        self.deliverables_table.setModel(
            FrameModel(self.service.deliverables(source_id))
        )

    def add_source(self):
        dialog=SourceDialog(self)
        if dialog.exec() and dialog.values()["title"]:
            self.service.create_source(dialog.values())
            self.refresh()

    def suggest_deliverables(self):
        source_id=self.selected_source_id()
        if not source_id: return
        try:
            ids=self.service.suggest_vod_deliverables(source_id)
            QMessageBox.information(
                self,"VOD deliverables",
                f"{len(ids)} deliverables were suggested."
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self,"Cannot suggest deliverables",str(exc))

    def add_deliverable(self):
        source_id=self.selected_source_id()
        if not source_id: return
        deliverable_type,ok=QInputDialog.getItem(
            self,"Deliverable type","Type",DELIVERABLE_TYPES,0,False
        )
        if not ok: return
        title,ok=QInputDialog.getText(
            self,"Deliverable title","Title"
        )
        if ok and title:
            platform,ok2=QInputDialog.getText(
                self,"Platform","Platform","YouTube"
            )
            if ok2:
                self.service.add_deliverable(
                    source_id,deliverable_type,title,platform or None,
                    confidence=1,score=70
                )
                self.refresh()

    def to_production(self):
        deliverable_id=self.selected_deliverable_id()
        if not deliverable_id: return
        try:
            project_id=self.service.convert_deliverable_to_production(
                deliverable_id
            )
            QMessageBox.information(
                self,"Production project",
                f"Production project {project_id} was created."
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self,"Cannot create project",str(exc))

    def generate_plan(self):
        actions=self.service.generate_daily_plan()
        QMessageBox.information(
            self,"Daily creator plan",
            f"{len(actions)} prioritized actions were generated."
        )
        self.refresh()
