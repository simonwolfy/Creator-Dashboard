from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,QAbstractItemView,QComboBox,QFileDialog,QFormLayout,QHBoxLayout,
    QLabel,QLineEdit,QMessageBox,QPlainTextEdit,QPushButton,QSplitter,QTableView,
    QVBoxLayout,QWidget
)

from creator_intelligence.ui.pages.twitch import FrameModel


class PackagingReviewPage(QWidget):
    def __init__(self,service):
        super().__init__(); self.service=service; self.current_package_id=None; self.source_path=None
        root=QVBoxLayout(self)
        title=QLabel("Packaging Review"); title.setObjectName("pageTitle"); root.addWidget(title)
        subtitle=QLabel("Review, edit, approve, and send platform-ready clip packages to Publishing.")
        subtitle.setWordWrap(True); root.addWidget(subtitle)
        filters=QHBoxLayout(); self.status=QComboBox(); self.status.addItems(["All","Generated","Approved","Rejected","Published"])
        self.platform=QComboBox(); self.platform.addItems(["All","youtube","tiktok","instagram","twitch"])
        for label,widget in (("Status",self.status),("Platform",self.platform)):
            filters.addWidget(QLabel(label)); filters.addWidget(widget)
        for label,handler in (("Refresh",self.refresh),("Approve selected",self.approve),
                              ("Reject selected",self.reject),("Regenerate",self.regenerate),
                              ("Send to Publishing",self.send_to_publishing),
                              ("Bulk approve",self.bulk_approve),("Export selected",self.export_selected)):
            button=QPushButton(label); button.clicked.connect(handler); filters.addWidget(button)
        filters.addStretch(); root.addLayout(filters)
        split=QSplitter(); root.addWidget(split,1)
        left=QWidget(); left_layout=QVBoxLayout(left); self.queue=QTableView()
        self.queue.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.queue.clicked.connect(lambda _:self.load_selected()); left_layout.addWidget(self.queue)
        split.addWidget(left)
        right=QWidget(); right_layout=QVBoxLayout(right)
        self.context=QLabel("Select a package to review."); self.context.setWordWrap(True); right_layout.addWidget(self.context)
        preview_row=QHBoxLayout(); self.preview=QLabel("No source video linked"); preview_row.addWidget(self.preview,1)
        open_button=QPushButton("Open source video"); open_button.clicked.connect(self.open_source); preview_row.addWidget(open_button)
        right_layout.addLayout(preview_row)
        self.transcript=QPlainTextEdit(); self.transcript.setReadOnly(True); self.transcript.setPlaceholderText("Clip transcript")
        self.transcript.setMaximumHeight(120); right_layout.addWidget(self.transcript)
        form=QFormLayout(); self.title_edit=QLineEdit(); self.description_edit=QPlainTextEdit(); self.caption_edit=QPlainTextEdit()
        self.hook_edit=QLineEdit(); self.hashtags_edit=QLineEdit(); self.description_edit.setMaximumHeight(90); self.caption_edit.setMaximumHeight(90)
        for label,widget in (("Title",self.title_edit),("Description",self.description_edit),
                             ("Caption",self.caption_edit),("Hook",self.hook_edit),("Hashtags",self.hashtags_edit)):
            form.addRow(label,widget)
        right_layout.addLayout(form)
        action_row=QHBoxLayout()
        for label,handler in (("Save edits",self.save_edits),("Copy package",self.copy_package)):
            button=QPushButton(label); button.clicked.connect(handler); action_row.addWidget(button)
        action_row.addStretch(); right_layout.addLayout(action_row)
        self.validation=QLabel(); self.validation.setWordWrap(True); right_layout.addWidget(self.validation)
        right_layout.addWidget(QLabel("Experiment variants — recommended option is marked Yes"))
        self.variants=QTableView(); self.variants.setSelectionBehavior(QAbstractItemView.SelectRows); right_layout.addWidget(self.variants,1)
        variant_actions=QHBoxLayout()
        use_variant=QPushButton("Use selected variant"); use_variant.clicked.connect(self.use_variant); variant_actions.addWidget(use_variant)
        variant_actions.addStretch(); right_layout.addLayout(variant_actions)
        split.addWidget(right); split.setSizes([520,700])
        self.status.currentTextChanged.connect(self.refresh); self.platform.currentTextChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.queue.setModel(FrameModel(self.service.queue(self.status.currentText(),self.platform.currentText())))

    def selected_ids(self):
        model=self.queue.model(); rows=sorted({index.row() for index in self.queue.selectionModel().selectedRows()}) if model else []
        return [str(model.frame.iloc[row]["id"]) for row in rows]

    def load_selected(self):
        ids=self.selected_ids()
        if not ids:return
        self.current_package_id=ids[0]; detail=self.service.detail(ids[0]); package=detail["package"]; clip=detail["clip"]
        self.source_path=detail["source_path"]
        self.context.setText(f"{package['platform'].title()} • Clip {package['clip_candidate_id']} • {package['decision_status']} • {package.get('clip_type') or 'Clip'}\nAI prediction: {package.get('predicted_performance') or 'Unknown'}")
        if clip:self.preview.setText(f"Preview range: {float(clip.get('start_seconds') or 0):.1f}s–{float(clip.get('end_seconds') or 0):.1f}s")
        else:self.preview.setText("No clip preview metadata")
        self.transcript.setPlainText(detail["transcript"])
        self.title_edit.setText(package.get("used_title") or package.get("generated_title") or "")
        self.description_edit.setPlainText(package.get("used_description") or package.get("generated_description") or "")
        self.caption_edit.setPlainText(package.get("used_caption") or package.get("generated_caption") or "")
        self.hook_edit.setText(package.get("used_hook") or package.get("generated_hook") or "")
        tags=self.service.outcomes._json(package.get("used_hashtags_json") or package.get("generated_hashtags_json"),[])
        self.hashtags_edit.setText(" ".join(tags)); self.variants.setModel(FrameModel(detail["variants"])); self.show_validation(detail["validation"])

    def edits(self):
        return {"title":self.title_edit.text().strip(),"description":self.description_edit.toPlainText().strip(),
                "caption":self.caption_edit.toPlainText().strip(),"hook":self.hook_edit.text().strip(),
                "hashtags":[value for value in self.hashtags_edit.text().split() if value]}

    def show_validation(self,result):
        counts=" • ".join(f"{key.title()}: {value}" for key,value in result["characters"].items() if value)
        self.validation.setText(("Ready to approve. " if result["valid"] else "Needs attention: "+" ".join(result["issues"])+" ")+counts)

    def save_edits(self):
        if not self.current_package_id:return
        self.service.save_edits(self.current_package_id,self.edits()); self.show_validation(self.service.validate(self.current_package_id,self.edits())); self.refresh()

    def approve(self):
        if not self.current_package_id:return
        try:self.service.approve(self.current_package_id,self.edits())
        except Exception as exc:QMessageBox.warning(self,"Cannot approve",str(exc));return
        self.refresh(); self.load_selected()

    def reject(self):
        if self.current_package_id:self.service.reject(self.current_package_id);self.refresh()

    def regenerate(self):
        if not self.current_package_id:return
        self.service.regenerate(self.current_package_id); QMessageBox.information(self,"Regenerated","A fresh package and experiment set was created."); self.refresh()

    def send_to_publishing(self):
        if not self.current_package_id:return
        try:item_id=self.service.send_to_publishing(self.current_package_id)
        except Exception as exc:QMessageBox.warning(self,"Cannot send",str(exc));return
        QMessageBox.information(self,"Sent to Publishing",f"Publishing item {item_id} is ready.")

    def bulk_approve(self):
        result=self.service.bulk_approve(self.selected_ids()); QMessageBox.information(self,"Bulk review",f"Approved {len(result['approved'])}; skipped {len(result['failed'])}."); self.refresh()

    def export_selected(self):
        ids=self.selected_ids()
        if not ids:return
        path,_=QFileDialog.getSaveFileName(self,"Export packages","packaging-review.json","JSON files (*.json)")
        if path:Path(path).write_text(json.dumps(self.service.export_payload(ids),indent=2),encoding="utf-8")

    def copy_package(self):
        if self.current_package_id:QApplication.clipboard().setText(json.dumps(self.service.export_payload([self.current_package_id])[0],indent=2))

    def use_variant(self):
        index=self.variants.currentIndex()
        if not index.isValid():return
        variant_id=str(self.variants.model().frame.iloc[index.row()]["id"]);self.service.experiments.select(variant_id);self.load_selected();self.refresh()

    def open_source(self):
        if self.source_path and Path(str(self.source_path)).exists():QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.source_path)))
        else:QMessageBox.information(self,"Source video","No accessible source video is linked to this transcript.")
