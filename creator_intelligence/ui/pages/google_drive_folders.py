from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

FOLDER_ID_ROLE = Qt.ItemDataRole.UserRole
PATH_ROLE = Qt.ItemDataRole.UserRole + 1
LOADED_ROLE = Qt.ItemDataRole.UserRole + 2


class GoogleDriveFoldersPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Google Drive Folder Browser")
        title.setObjectName("pageTitle")
        browse = QPushButton("Load My Drive")
        browse.clicked.connect(self.load_root)
        refresh = QPushButton("Refresh mappings")
        refresh.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(browse)
        header.addWidget(refresh)
        layout.addLayout(header)

        self.summary = QLabel("Connect Google Drive, then load My Drive to browse and map folders.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        splitter = QSplitter(Qt.Orientation.Vertical)

        browser_panel = QWidget()
        browser_layout = QVBoxLayout(browser_panel)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Drive folder", "Folder ID"])
        self.tree.setAlternatingRowColors(True)
        self.tree.itemExpanded.connect(self._load_children)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeMode.Stretch)
        browser_layout.addWidget(self.tree)

        picker = QHBoxLayout()
        self.selected_label = QLabel("No folder selected")
        self.purpose_box = QComboBox()
        self.purpose_box.addItems(self.service.PURPOSES)
        self.map_button = QPushButton("Map selected folder")
        self.map_button.setEnabled(False)
        self.map_button.clicked.connect(self.add_mapping)
        picker.addWidget(self.selected_label, 2)
        picker.addWidget(QLabel("Purpose"))
        picker.addWidget(self.purpose_box)
        picker.addWidget(self.map_button)
        browser_layout.addLayout(picker)
        splitter.addWidget(browser_panel)

        mappings_panel = QWidget()
        mappings_layout = QVBoxLayout(mappings_panel)
        mappings_layout.addWidget(QLabel("Saved mappings"))
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Purpose", "Folder ID", "Recursive", "Metadata only", "Enabled", "Validated", "Last error", "ID"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        mappings_layout.addWidget(self.table)

        actions = QHBoxLayout()
        validate = QPushButton("Validate selected")
        validate.clicked.connect(self.validate_selected)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self.remove_selected)
        actions.addWidget(validate)
        actions.addWidget(remove)
        actions.addStretch()
        mappings_layout.addLayout(actions)
        splitter.addWidget(mappings_panel)
        splitter.setSizes([420, 260])
        layout.addWidget(splitter)
        self.refresh()

    def load_root(self) -> None:
        self.tree.clear()
        self.map_button.setEnabled(False)
        self.selected_label.setText("Loading My Drive...")
        try:
            folders = self.service.browse_folders()
            root = QTreeWidgetItem(["My Drive", "root"])
            root.setData(0, FOLDER_ID_ROLE, "root")
            root.setData(0, PATH_ROLE, "My Drive")
            root.setData(0, LOADED_ROLE, True)
            self.tree.addTopLevelItem(root)
            for folder in folders:
                root.addChild(self._folder_item(folder, "My Drive"))
            root.setExpanded(True)
            self.summary.setText(f"Loaded {len(folders)} top-level folders from your Google Drive.")
            self.selected_label.setText("Select a folder to map it.")
        except Exception as exc:
            self.selected_label.setText("Unable to load Drive folders.")
            QMessageBox.critical(self, "Unable to browse Drive", str(exc))

    def _folder_item(self, folder: dict, parent_path: str) -> QTreeWidgetItem:
        name = str(folder.get("name") or "Untitled folder")
        folder_id = str(folder.get("id") or "")
        item = QTreeWidgetItem([name, folder_id])
        item.setData(0, FOLDER_ID_ROLE, folder_id)
        item.setData(0, PATH_ROLE, f"{parent_path}/{name}")
        item.setData(0, LOADED_ROLE, False)
        # Placeholder supplies an expansion arrow. It is replaced on first expand.
        placeholder = QTreeWidgetItem(["Loading...", ""])
        placeholder.setDisabled(True)
        item.addChild(placeholder)
        return item

    def _load_children(self, item: QTreeWidgetItem) -> None:
        if item.data(0, LOADED_ROLE):
            return
        folder_id = item.data(0, FOLDER_ID_ROLE)
        if not folder_id:
            return
        item.takeChildren()
        try:
            children = self.service.browse_folders(str(folder_id))
            parent_path = str(item.data(0, PATH_ROLE) or item.text(0))
            for folder in children:
                item.addChild(self._folder_item(folder, parent_path))
            item.setData(0, LOADED_ROLE, True)
            self.summary.setText(f"Loaded {len(children)} folders inside {item.text(0)}.")
        except Exception as exc:
            item.setData(0, LOADED_ROLE, False)
            item.addChild(QTreeWidgetItem(["Unable to load", ""]))
            QMessageBox.critical(self, "Unable to load subfolders", str(exc))

    def _selection_changed(self) -> None:
        item = self.tree.currentItem()
        folder_id = item.data(0, FOLDER_ID_ROLE) if item else None
        selectable = bool(folder_id and folder_id != "root")
        self.map_button.setEnabled(selectable)
        if selectable:
            self.selected_label.setText(str(item.data(0, PATH_ROLE) or item.text(0)))
        else:
            self.selected_label.setText("Select a folder to map it.")

    def add_mapping(self) -> None:
        item = self.tree.currentItem()
        folder_id = item.data(0, FOLDER_ID_ROLE) if item else None
        if not folder_id or folder_id == "root":
            QMessageBox.information(self, "Google Drive", "Load Drive and select a folder first.")
            return
        try:
            self.service.add_mapping(
                str(folder_id),
                item.text(0),
                purpose=self.purpose_box.currentText(),
                folder_path=str(item.data(0, PATH_ROLE) or item.text(0)),
            )
            self.refresh()
            self.summary.setText(f"Mapped {item.text(0)} as {self.purpose_box.currentText()}.")
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
        if mappings and self.tree.topLevelItemCount() == 0:
            self.summary.setText(f"{len(mappings)} Drive folder mappings configured. Load My Drive to browse folders.")

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
