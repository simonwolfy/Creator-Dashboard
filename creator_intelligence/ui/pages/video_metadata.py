from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ProbeWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service, asset_id: str | None = None, batch: bool = False):
        super().__init__()
        self.service = service
        self.asset_id = asset_id
        self.batch = batch

    def run(self) -> None:
        try:
            result = self.service.probe_pending_local(limit=25) if self.batch else self.service.probe_asset(self.asset_id)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class VideoMetadataPage(QWidget):
    ALL = "All"

    def __init__(self, service):
        super().__init__()
        self.service = service
        self._rows: list[dict] = []
        self._threads: list[tuple[QThread, ProbeWorker]] = []

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Video Metadata Engine")
        title.setObjectName("pageTitle")
        self.tool_label = QLabel()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.tool_label)
        layout.addLayout(header)

        controls = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems([self.ALL, "Pending", "Complete", "Needs local file", "Failed", "Missing", "Unavailable"])
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        probe = QPushButton("Probe selected")
        probe.clicked.connect(self.probe_selected)
        batch = QPushButton("Probe next 25 local videos")
        batch.clicked.connect(self.probe_batch)
        controls.addWidget(QLabel("Probe status"))
        controls.addWidget(self.status_filter)
        controls.addWidget(refresh)
        controls.addStretch()
        controls.addWidget(probe)
        controls.addWidget(batch)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Storage", "Probe", "Duration", "Resolution", "FPS", "Video codec", "Audio", "HDR", "Container", "Probed"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._show_selection)
        splitter.addWidget(self.table)

        detail = QWidget()
        detail.setMinimumWidth(360)
        detail_layout = QVBoxLayout(detail)
        detail_title = QLabel("Technical Details")
        detail_title.setStyleSheet("font-size:18px;font-weight:700;")
        detail_layout.addWidget(detail_title)
        form = QFormLayout()
        self.details: dict[str, QLabel] = {}
        for key, label in (
            ("name", "Name"),
            ("location", "Location"),
            ("probe_status", "Probe status"),
            ("probe_error", "Last error"),
            ("duration_seconds", "Duration"),
            ("width", "Width"),
            ("height", "Height"),
            ("frame_rate", "Frame rate"),
            ("video_codec", "Video codec"),
            ("video_profile", "Profile"),
            ("pixel_format", "Pixel format"),
            ("hdr_format", "Dynamic range"),
            ("audio_codec", "Audio codec"),
            ("audio_tracks", "Audio tracks"),
            ("audio_channels", "Channels"),
            ("audio_sample_rate", "Sample rate"),
            ("container_format", "Container"),
            ("bit_rate", "Bit rate"),
            ("rotation", "Rotation"),
        ):
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.details[key] = value
            form.addRow(label, value)
        detail_layout.addLayout(form)
        detail_layout.addStretch()
        splitter.addWidget(detail)
        splitter.setSizes([1050, 350])
        layout.addWidget(splitter)

        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.refresh()

    def refresh(self) -> None:
        status = self.status_filter.currentText()
        self._rows = self.service.assets(status=None if status == self.ALL else status)
        tool = self.service.tool_status()
        self.tool_label.setText(tool["message"])
        self.table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            values = (
                row.get("name"),
                row.get("storage_provider"),
                row.get("probe_status"),
                _duration(row.get("duration_seconds")),
                _resolution(row),
                _number(row.get("frame_rate"), 2),
                row.get("video_codec"),
                _audio(row),
                row.get("hdr_format"),
                row.get("container_format"),
                row.get("probed_at"),
            )
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem("" if value is None else str(value)))
        self.table.resizeColumnsToContents()
        complete = sum(1 for row in self._rows if row.get("probe_status") == "Complete")
        local = sum(1 for row in self._rows if row.get("storage_provider") == "Local")
        self.summary.setText(f"Video assets: {len(self._rows)}  |  Local: {local}  |  Metadata complete: {complete}")
        self._show_selection()

    def _selected(self) -> dict | None:
        selected = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self._rows[selected[0].row()] if selected else None

    def _show_selection(self) -> None:
        row = self._selected()
        for key, label in self.details.items():
            value = None if row is None else row.get(key)
            if key == "duration_seconds":
                value = _duration(value)
            elif key == "bit_rate" and value not in (None, ""):
                value = f"{float(value) / 1_000_000:.2f} Mbps"
            elif key == "audio_sample_rate" and value not in (None, ""):
                value = f"{int(value)} Hz"
            label.setText("—" if value in (None, "") else str(value))

    def probe_selected(self) -> None:
        row = self._selected()
        if not row:
            QMessageBox.information(self, "Video Metadata", "Select a video asset first.")
            return
        self._start_worker(asset_id=str(row["id"]))

    def probe_batch(self) -> None:
        self._start_worker(batch=True)

    def _start_worker(self, asset_id: str | None = None, batch: bool = False) -> None:
        thread = QThread(self)
        worker = ProbeWorker(self.service, asset_id=asset_id, batch=batch)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda result: self._complete(thread, result))
        worker.failed.connect(lambda message: self._failed(thread, message))
        self._threads.append((thread, worker))
        thread.start()

    def _complete(self, thread: QThread, result) -> None:
        self._finish_thread(thread)
        self.refresh()
        if isinstance(result, dict) and "attempted" in result:
            QMessageBox.information(
                self,
                "Video Metadata",
                f"Attempted {result['attempted']} videos. Complete: {result['complete']}. Failed: {result['failed']}.",
            )
        elif isinstance(result, dict) and result.get("probe_status") != "Complete":
            QMessageBox.warning(self, "Video Metadata", str(result.get("probe_error") or result.get("probe_status")))

    def _failed(self, thread: QThread, message: str) -> None:
        self._finish_thread(thread)
        QMessageBox.critical(self, "Video metadata probe failed", message)

    def _finish_thread(self, thread: QThread) -> None:
        thread.quit()
        thread.wait()
        self._threads = [pair for pair in self._threads if pair[0] is not thread]


def _duration(value) -> str:
    if value in (None, ""):
        return "—"
    seconds = max(0, int(float(value)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _resolution(row: dict) -> str:
    width, height = row.get("width"), row.get("height")
    return "—" if not width or not height else f"{int(width)}×{int(height)}"


def _number(value, places: int) -> str:
    return "—" if value in (None, "") else f"{float(value):.{places}f}"


def _audio(row: dict) -> str:
    codec = row.get("audio_codec") or "—"
    tracks = row.get("audio_tracks")
    return codec if tracks in (None, "") else f"{codec} ({int(tracks)} track{'s' if int(tracks) != 1 else ''})"
