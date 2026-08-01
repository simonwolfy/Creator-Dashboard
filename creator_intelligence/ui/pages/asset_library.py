from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class AssetLibraryPage(QWidget):
    """Searchable asset browser with status visibility and metadata details."""

    ALL = "All"

    def __init__(self, service):
        super().__init__()
        self.service = service
        self._rows: list[dict] = []

        outer = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Asset Library")
        title.setObjectName("pageTitle")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        outer.addLayout(header)

        filters = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search name, path, URL, or notes")
        self.search_box.returnPressed.connect(self.refresh)
        self.type_filter = self._combo(
            [self.ALL, "Video", "Audio", "Image", "Thumbnail", "Project", "Subtitle", "Overlay", "Other"]
        )
        self.provider_filter = self._combo([self.ALL, "Local", "Google Drive", "Backup", "Other"])
        self.status_filter = self._combo([self.ALL, "Available", "Missing", "Processing", "Archived"])
        for label, widget in (
            ("Search", self.search_box),
            ("Type", self.type_filter),
            ("Storage", self.provider_filter),
            ("Status", self.status_filter),
        ):
            filters.addWidget(QLabel(label))
            filters.addWidget(widget)
        apply_button = QPushButton("Apply")
        apply_button.clicked.connect(self.refresh)
        filters.addWidget(apply_button)
        outer.addLayout(filters)

        splitter = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Type", "Role", "Storage", "Status", "Size", "Updated", "Location"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._show_selection)
        self.table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.table)

        detail = QWidget()
        detail.setMinimumWidth(320)
        detail_layout = QVBoxLayout(detail)
        detail_title = QLabel("Asset Details")
        detail_title.setStyleSheet("font-size:18px;font-weight:700;")
        detail_layout.addWidget(detail_title)
        form = QFormLayout()
        self.detail_labels = {}
        for key, label in (
            ("name", "Name"),
            ("asset_type", "Type"),
            ("role", "Role"),
            ("storage_provider", "Storage"),
            ("status", "Status"),
            ("location", "Location"),
            ("mime_type", "MIME type"),
            ("size_bytes", "Size"),
            ("checksum_sha256", "SHA-256"),
            ("last_verified_at", "Last verified"),
            ("notes", "Notes"),
        ):
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.detail_labels[key] = value
            form.addRow(label, value)
        detail_layout.addLayout(form)
        detail_layout.addStretch()
        splitter.addWidget(detail)
        splitter.setSizes([1050, 350])
        outer.addWidget(splitter)

        self.summary = QLabel()
        outer.addWidget(self.summary)
        self.refresh()

    @staticmethod
    def _combo(values: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        return combo

    @staticmethod
    def _selected(combo: QComboBox) -> str | None:
        value = combo.currentText()
        return None if value == AssetLibraryPage.ALL else value

    def refresh(self) -> None:
        self._rows = self.service.search(
            self.search_box.text().strip() or None,
            asset_type=self._selected(self.type_filter),
            storage_provider=self._selected(self.provider_filter),
            status=self._selected(self.status_filter),
            limit=1000,
        )
        self.table.setRowCount(len(self._rows))
        missing = 0
        checksum_counts: dict[str, int] = {}
        for row in self._rows:
            checksum = row.get("checksum_sha256")
            if checksum:
                checksum_counts[checksum] = checksum_counts.get(checksum, 0) + 1
        duplicate_checksums = {value for value, count in checksum_counts.items() if count > 1}

        for row_index, row in enumerate(self._rows):
            if str(row.get("status") or "").casefold() == "missing":
                missing += 1
            values = (
                row.get("name"),
                row.get("asset_type"),
                row.get("role"),
                row.get("storage_provider"),
                row.get("status"),
                self._format_size(row.get("size_bytes")),
                row.get("updated_at"),
                row.get("location"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem("" if value is None else str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if row.get("checksum_sha256") in duplicate_checksums:
                    item.setToolTip("Possible duplicate: another asset has the same checksum")
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()
        duplicate_count = sum(checksum_counts[value] for value in duplicate_checksums)
        self.summary.setText(
            f"Assets: {len(self._rows)}  |  Missing: {missing}  |  Possible duplicates: {duplicate_count}"
        )
        self._show_selection()

    def _show_selection(self) -> None:
        selected = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        row = self._rows[selected[0].row()] if selected else None
        for key, label in self.detail_labels.items():
            if row is None:
                label.setText("—")
                continue
            value = row.get(key)
            if key == "size_bytes":
                value = self._format_size(value)
            label.setText("—" if value in (None, "") else str(value))

    @staticmethod
    def _format_size(value) -> str:
        if value in (None, ""):
            return "—"
        size = float(value)
        units = ("B", "KB", "MB", "GB", "TB")
        index = 0
        while size >= 1024 and index < len(units) - 1:
            size /= 1024
            index += 1
        return f"{size:.1f} {units[index]}"
