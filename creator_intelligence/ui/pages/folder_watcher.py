from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class FolderWatcherPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Automatic Folder Watcher")
        title.setObjectName("pageTitle")
        add_button = QPushButton("Add folder")
        add_button.clicked.connect(self.add_folder)
        scan_button = QPushButton("Scan enabled folders")
        scan_button.clicked.connect(self.scan_all)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(add_button)
        header.addWidget(scan_button)
        header.addWidget(refresh_button)
        layout.addLayout(header)

        self.summary = QLabel("No scans run yet.")
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Path", "Enabled", "Recursive", "Checksums", "Last scan", "Last error", "ID"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        note = QLabel(
            "The watcher uses safe on-demand scans in this phase. Continuous background polling will be added after local validation."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.refresh()

    def add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose folder to watch")
        if not path:
            return
        try:
            self.service.add_folder(path)
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Unable to add folder", str(exc))

    def scan_all(self) -> None:
        summaries = self.service.scan_all()
        created = sum(item.created for item in summaries)
        updated = sum(item.updated for item in summaries)
        missing = sum(item.missing for item in summaries)
        errors = sum(item.errors for item in summaries)
        self.summary.setText(
            f"Scanned {len(summaries)} folders | New: {created} | Updated: {updated} | Missing: {missing} | Errors: {errors}"
        )
        self.refresh(keep_summary=True)

    def refresh(self, keep_summary: bool = False) -> None:
        folders = self.service.list_folders()
        self.table.setRowCount(len(folders))
        keys = (
            "name",
            "path",
            "enabled",
            "recursive",
            "calculate_checksums",
            "last_scan_at",
            "last_error",
            "id",
        )
        for row_index, folder in enumerate(folders):
            for column_index, key in enumerate(keys):
                value = folder.get(key)
                if key in {"enabled", "recursive", "calculate_checksums"}:
                    value = "Yes" if int(value or 0) else "No"
                self.table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem("" if value is None else str(value)),
                )
        self.table.resizeColumnsToContents()
        if not keep_summary and not folders:
            self.summary.setText("No folders configured. Add an OBS, export, thumbnail, or project folder to begin.")
