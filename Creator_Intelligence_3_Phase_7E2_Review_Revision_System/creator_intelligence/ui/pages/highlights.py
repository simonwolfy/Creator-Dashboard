from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,
    QAbstractItemView,QMessageBox,QInputDialog,QComboBox,QSpinBox,
    QDoubleSpinBox,QFormLayout,QGroupBox,QTextEdit
)
from creator_intelligence.ui.pages.twitch import FrameModel

class HighlightsPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service

        layout = QVBoxLayout(self)
        title = QLabel("Highlight Detection and Review")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        controls = QHBoxLayout()
        self.session_id = QSpinBox()
        self.session_id.setRange(1,999999999)
        self.session_id.setPrefix("Session ")
        generate = QPushButton("Generate candidates")
        generate.clicked.connect(self.generate)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        approve = QPushButton("Approve")
        approve.clicked.connect(lambda:self.review("Approved"))
        reject = QPushButton("Reject")
        reject.clicked.connect(lambda:self.review("Rejected"))
        changes = QPushButton("Needs changes")
        changes.clicked.connect(lambda:self.review("Needs changes"))
        merge = QPushButton("Merge selected IDs")
        merge.clicked.connect(self.merge)
        split = QPushButton("Split candidate")
        split.clicked.connect(self.split)
        boundaries = QPushButton("Edit boundaries")
        boundaries.clicked.connect(self.edit_boundaries)
        export = QPushButton("Export to pipeline")
        export.clicked.connect(self.export)
        for widget in (
            self.session_id,generate,refresh,approve,reject,changes,
            boundaries,merge,split,export
        ):
            controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)

        self.table = QTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        settings_box = QGroupBox("Detection settings")
        form = QFormLayout(settings_box)
        self.grouping = QSpinBox(); self.grouping.setRange(15,900)
        self.pre_roll = QSpinBox(); self.pre_roll.setRange(0,300)
        self.post_roll = QSpinBox(); self.post_roll.setRange(0,600)
        self.short_max = QSpinBox(); self.short_max.setRange(15,180)
        self.highlight_max = QSpinBox(); self.highlight_max.setRange(30,900)
        self.minimum_score = QDoubleSpinBox()
        self.minimum_score.setRange(0,100)
        self.minimum_score.setSingleStep(1)
        save = QPushButton("Save settings")
        save.clicked.connect(self.save_settings)
        form.addRow("Grouping window (seconds)",self.grouping)
        form.addRow("Default pre-roll",self.pre_roll)
        form.addRow("Default post-roll",self.post_roll)
        form.addRow("Short maximum length",self.short_max)
        form.addRow("Highlight maximum length",self.highlight_max)
        form.addRow("Minimum candidate score",self.minimum_score)
        form.addRow(save)
        layout.addWidget(settings_box)
        self.load_settings()
        self.refresh()

    def selected_id(self):
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return int(self.table.model().frame.iloc[index.row()]["id"])

    def refresh(self):
        frame = self.service.candidates(self.session_id.value())
        self.table.setModel(FrameModel(frame))

    def generate(self):
        try:
            frame = self.service.generate_candidates(self.session_id.value())
            self.table.setModel(FrameModel(frame))
            QMessageBox.information(
                self,"Candidates generated",
                f"{len(frame)} candidates are available for review."
            )
        except Exception as exc:
            QMessageBox.critical(self,"Generation failed",str(exc))

    def review(self,status):
        candidate_id = self.selected_id()
        if not candidate_id:
            return
        notes,ok = QInputDialog.getMultiLineText(
            self,"Review notes",f"{status} notes"
        )
        if ok:
            self.service.set_review_status(candidate_id,status,notes or None)
            self.refresh()

    def edit_boundaries(self):
        candidate_id = self.selected_id()
        if not candidate_id:
            return
        candidate = self.service.candidate(candidate_id)
        start,ok = QInputDialog.getInt(
            self,"Start boundary","Start seconds",
            int(candidate["start_seconds"]),0,999999
        )
        if not ok:
            return
        end,ok = QInputDialog.getInt(
            self,"End boundary","End seconds",
            int(candidate["end_seconds"]),start+1,999999
        )
        if ok:
            self.service.update_boundaries(candidate_id,start,end)
            self.refresh()

    def merge(self):
        text,ok = QInputDialog.getText(
            self,"Merge candidates",
            "Comma-separated candidate IDs"
        )
        if ok and text:
            try:
                ids = [int(part.strip()) for part in text.split(",") if part.strip()]
                self.service.merge_candidates(ids)
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self,"Merge failed",str(exc))

    def split(self):
        candidate_id = self.selected_id()
        if not candidate_id:
            return
        candidate = self.service.candidate(candidate_id)
        midpoint = (
            int(candidate["start_seconds"]) +
            int(candidate["end_seconds"])
        ) // 2
        split,ok = QInputDialog.getInt(
            self,"Split candidate","Split at seconds",
            midpoint,
            int(candidate["start_seconds"])+1,
            int(candidate["end_seconds"])-1
        )
        if ok:
            try:
                self.service.split_candidate(candidate_id,split)
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self,"Split failed",str(exc))

    def export(self):
        candidate_id = self.selected_id()
        if not candidate_id:
            return
        formats = [
            "YouTube Short","YouTube Highlight",
            "TikTok Clip","Multi-platform Clip"
        ]
        content_type,ok = QInputDialog.getItem(
            self,"Export highlight","Content type",
            formats,0,False
        )
        if ok:
            try:
                self.service.export_to_pipeline(candidate_id,content_type)
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self,"Export failed",str(exc))

    def load_settings(self):
        rules = self.service.settings()
        self.grouping.setValue(rules.grouping_window_seconds)
        self.pre_roll.setValue(rules.default_pre_roll_seconds)
        self.post_roll.setValue(rules.default_post_roll_seconds)
        self.short_max.setValue(rules.short_max_seconds)
        self.highlight_max.setValue(rules.highlight_max_seconds)
        self.minimum_score.setValue(rules.minimum_score)

    def save_settings(self):
        self.service.update_settings(
            grouping_window_seconds=self.grouping.value(),
            default_pre_roll_seconds=self.pre_roll.value(),
            default_post_roll_seconds=self.post_roll.value(),
            short_max_seconds=self.short_max.value(),
            highlight_max_seconds=self.highlight_max.value(),
            minimum_score=self.minimum_score.value()
        )
        QMessageBox.information(self,"Settings saved","Highlight settings were saved.")
