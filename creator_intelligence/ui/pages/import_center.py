from __future__ import annotations
import json
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QTabWidget,
    QFileDialog,QMessageBox,QAbstractItemView,QCheckBox,QGroupBox,QFormLayout,
    QLineEdit,QPlainTextEdit
)
from creator_intelligence.ui.pages.twitch import FrameModel

class DropZone(QLabel):
    def __init__(self, callback):
        super().__init__("Drop Twitch or YouTube CSV/TSV exports here")
        self.callback = callback
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(120)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            "border:2px dashed #6f36c9;border-radius:12px;"
            "font-size:16px;padding:24px;"
        )

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self,event):
        paths=[url.toLocalFile() for url in event.mimeData().urls()]
        self.callback(paths)
        event.acceptProposedAction()

class ImportCenterPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service=service
        self.current_batch_id=None
        layout=QVBoxLayout(self)
        title=QLabel("Automated Import Center")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        tabs=QTabWidget()
        tabs.addTab(self._new_import_tab(),"New import")
        tabs.addTab(self._watch_tab(),"Watched folders")
        tabs.addTab(self._history_tab(),"Import history")
        layout.addWidget(tabs)
        self.refresh_all()

    def _new_import_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.drop_zone=DropZone(self.handle_paths)
        layout.addWidget(self.drop_zone)
        row=QHBoxLayout()
        choose=QPushButton("Choose files")
        choose.clicked.connect(self.choose_files)
        self.commit_button=QPushButton("Commit staged import")
        self.commit_button.clicked.connect(self.commit_current)
        cancel=QPushButton("Cancel staged import")
        cancel.clicked.connect(self.cancel_current)
        row.addWidget(choose); row.addWidget(self.commit_button)
        row.addWidget(cancel); row.addStretch()
        layout.addLayout(row)

        self.summary=QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(170)
        layout.addWidget(self.summary)

        self.preview=QTableView()
        self.preview.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.preview)
        return page

    def _watch_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        add=QPushButton("Add watched folder"); add.clicked.connect(self.add_watch)
        scan=QPushButton("Scan selected folder"); scan.clicked.connect(self.scan_watch)
        auto=QPushButton("Scan and import selected folder"); auto.clicked.connect(lambda:self.scan_watch(True))
        remove=QPushButton("Remove selected folder"); remove.clicked.connect(self.remove_watch)
        row.addWidget(add); row.addWidget(scan); row.addWidget(auto); row.addWidget(remove); row.addStretch()
        layout.addLayout(row)
        self.watch_table=QTableView()
        self.watch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.watch_table)
        return page

    def _history_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        refresh=QPushButton("Refresh"); refresh.clicked.connect(self.refresh_all)
        rollback=QPushButton("Rollback selected import"); rollback.clicked.connect(self.rollback_selected)
        row.addWidget(refresh); row.addWidget(rollback); row.addStretch()
        layout.addLayout(row)
        self.history_table=QTableView()
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.history_table)
        return page

    def choose_files(self):
        paths,_=QFileDialog.getOpenFileNames(
            self,"Choose analytics exports","","CSV/TSV (*.csv *.tsv)"
        )
        self.handle_paths(paths)

    def handle_paths(self,paths):
        if not paths: return
        messages=[]
        for path in paths:
            try:
                batch=self.service.stage(path)
                self.current_batch_id=batch["batch_id"]
                messages.append(
                    f'{batch["file_name"]}: {batch["detected_type"]} '
                    f'({batch["rows_staged"]} changes, '
                    f'{batch["rows_skipped"]} duplicates, '
                    f'{batch["rows_rejected"]} rejected)'
                )
            except Exception as exc:
                messages.append(f"{path}: ERROR — {exc}")
        self.summary.setPlainText("\n".join(messages))
        self.refresh_current_preview()
        self.refresh_all()

    def refresh_current_preview(self):
        if not self.current_batch_id:
            self.preview.setModel(FrameModel(pd.DataFrame()))
            return
        frame=self.service.staging_rows(self.current_batch_id)
        if not frame.empty:
            frame["normalized"] = frame["normalized_json"].apply(
                lambda value: json.dumps(json.loads(value),ensure_ascii=False)
            )
            frame=frame[["row_number","row_key","disposition","normalized","warning_json","error_json"]]
        self.preview.setModel(FrameModel(frame))

    def commit_current(self):
        if not self.current_batch_id:
            QMessageBox.information(self,"No staged import","Stage a file first.")
            return
        try:
            result=self.service.commit(self.current_batch_id)
            QMessageBox.information(
                self,"Import complete",
                f'{result["rows_inserted"]} inserted, '
                f'{result["rows_updated"]} updated, '
                f'{result["rows_skipped"]} skipped.'
            )
            self.current_batch_id=None
            self.refresh_current_preview()
            self.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self,"Import failed",str(exc))

    def cancel_current(self):
        if self.current_batch_id:
            self.service.cancel_staging(self.current_batch_id)
            self.current_batch_id=None
            self.refresh_current_preview()
            self.refresh_all()

    def add_watch(self):
        path=QFileDialog.getExistingDirectory(self,"Choose watched folder")
        if path:
            self.service.add_watch_folder(path,recursive=True,archive_after_import=True)
            self.refresh_all()

    def selected_folder_id(self):
        idx=self.watch_table.currentIndex()
        if not idx.isValid(): return None
        return int(self.watch_table.model().frame.iloc[idx.row()]["id"])

    def scan_watch(self,auto_commit=False):
        folder_id=self.selected_folder_id()
        if not folder_id:
            QMessageBox.information(self,"Select folder","Select a watched folder.")
            return
        try:
            results=self.service.scan_watch_folder(folder_id,auto_commit=auto_commit)
            QMessageBox.information(
                self,"Scan complete",
                "\n".join(f'{r["status"]}: {r["file"]}' for r in results) or "No files found."
            )
            self.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self,"Scan failed",str(exc))

    def remove_watch(self):
        folder_id=self.selected_folder_id()
        if folder_id:
            self.service.remove_watch_folder(folder_id)
            self.refresh_all()

    def rollback_selected(self):
        idx=self.history_table.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self,"Select import","Select an import history row.")
            return
        row=self.history_table.model().frame.iloc[idx.row()]
        try:
            self.service.rollback(str(row["batch_id"]))
            QMessageBox.information(self,"Rollback complete","The database was restored to its pre-import state.")
            self.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self,"Rollback failed",str(exc))

    def refresh_all(self):
        self.watch_table.setModel(FrameModel(self.service.watch_folders()))
        self.history_table.setModel(FrameModel(self.service.history()))
