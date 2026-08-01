from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class GoogleDriveFoldersPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.available: list[dict] = []
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Google Drive Folder Mapping")
        title.setObjectName("pageTitle")
        browse = QPushButton("Browse Drive folders")
        browse.clicked.connect(self.browse)
        refresh = QPushButton("Refresh mappings")
        refresh.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(browse)
        header.addWidget(refresh)
        layout.addLayout(header)

        picker = QHBoxLayout()
        self.folder_box = QComboBox()
        self.purpose_box = QComboBox()
        self.purpose_box.addItems(self.service.PURPOSES)
        add = QPushButton("Map selected folder")
        add.clicked.connect(self.add_mapping)
        picker.addWidget(QLabel("Drive folder"))
        picker.addWidget(self.folder_box, 2)
        picker.addWidget(QLabel("Purpose"))
        picker.addWidget(self.purpose_box)
        picker.addWidget(add)
        layout.addLayout(picker)

        self.summary = QLabel("Connect Google Drive, then browse folders to create mappings.")
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Purpose", "Folder ID", "Recursive", "Metadata only", "Enabled", "Validated", "Last error", "ID"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        validate = QPushButton("Validate selected")
        validate.clicked.connect(self.validate_selected)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self.remove_selected)
        actions.addWidget(validate)
        actions.addWidget(remove)
        actions.addStretch()
        layout.addLayout(actions)
        self.refresh()

    def browse(self) -> None:
        try:
            self.available = self.service.browse_folders()
            self.folder_box.clear()
            for folder in self.available:
                self.folder_box.addItem(folder.get("name") or "Untitled folder", folder.get("id"))
            self.summary.setText(f"Found {len(self.available)} Google Drive folders.")
        except Exception as exc:
            QMessageBox.critical(self, "Unable to browse Drive", str(exc))

    def add_mapping(self) -> None:
        folder_id = self.folder_box.currentData()
        if not folder_id:
            QMessageBox.information(self, "Google Drive", "Browse and select a folder first.")
            return
        try:
            self.service.add_mapping(
                str(folder_id),
                self.folder_box.currentText(),
                purpose=self.purpose_box.currentText(),
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Unable to map folder", str(exc))

    def refresh(self) -> None:
        mappings = self.service.list_mappings()
        self.table.setRowCount(len(mappings))
        keys = (
            "folder_name", "purpose", "drive_folder_id", "recursive", "metadata_only",
            "enabled", "last_validated_at", "last_error", "id",
        )
        for row_index, mapping in enumerate(mappings):
            for column_index, key in enumerate(keys):
                value = mapping.get(key)
                if key in {"recursive", "metadata_only", "enabled"}:
                    value = "Yes" if int(value or 0) else "No"
                self.table.setItem(row_index, column_index, QTableWidgetItem("" if value is None else str(value)))
        self.table.resizeColumnsToContents()
        if mappings:
            self.summary.setText(f"{len(mappings)} Drive folder mappings configured.")

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 8)
        return int(item.text()) if item and item.text() else None

    def validate_selected(self) -> None:
        mapping_id = self._selected_id()
        if mapping_id is None:
            return
        try:
            self.service.validate_mapping(mapping_id)
            self.refresh()
        except Exception as exc:
            self.refresh()
            QMessageBox.critical(self, "Folder validation failed", str(exc))

    def remove_selected(self) -> None:
        mapping_id = self._selected_id()
        if mapping_id is None:
            return
        self.service.remove_mapping(mapping_id)
        self.refresh()
