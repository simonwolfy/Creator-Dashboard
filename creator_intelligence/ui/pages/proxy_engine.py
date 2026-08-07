from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
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


class ProxyWorker(QObject):
    finished = Signal(int)
    failed = Signal(str)

    def __init__(self, processing, job_id: int):
        super().__init__()
        self.processing = processing
        self.job_id = job_id

    def run(self) -> None:
        try:
            self.processing.run_job(self.job_id)
            self.finished.emit(self.job_id)
        except Exception as exc:
            self.failed.emit(str(exc))


class ProxyEnginePage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self._rows: list[dict] = []
        self._threads: list[tuple[QThread, ProxyWorker]] = []

        layout = QVBoxLayout(self)
        title = QLabel("Proxy Engine")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(
            QLabel(
                "Create disposable editing proxies from local videos. Source files are never modified."
            )
        )

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Preset"))
        self.preset = QComboBox()
        for preset in self.service.presets():
            self.preset.addItem(preset.label, preset.key)
        controls.addWidget(self.preset)
        queue_selected = QPushButton("Queue selected")
        queue_selected.clicked.connect(self.queue_selected)
        queue_missing = QPushButton("Queue missing proxies")
        queue_missing.clicked.connect(self.queue_missing)
        run_next = QPushButton("Run next proxy job")
        run_next.clicked.connect(self.run_next)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(queue_selected)
        controls.addWidget(queue_missing)
        controls.addWidget(run_next)
        controls.addStretch()
        controls.addWidget(refresh)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Name",
                "Duration",
                "Resolution",
                "Source size",
                "Proxies",
                "Latest proxy",
                "Estimated size",
                "Source path",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.refresh()

    def refresh(self) -> None:
        self._rows = self.service.assets()
        self.table.setRowCount(len(self._rows))
        preset_key = str(self.preset.currentData() or "balanced")
        ready = 0
        for row_index, row in enumerate(self._rows):
            proxy_count = int(row.get("proxy_count") or 0)
            if proxy_count:
                ready += 1
            values = (
                row.get("display_name"),
                self._duration(row.get("duration_seconds")),
                self._resolution(row.get("width"), row.get("height")),
                self._size(row.get("file_size_bytes")),
                proxy_count,
                row.get("latest_proxy_path") or "—",
                self._size(
                    self.service.estimated_size_bytes(
                        row.get("duration_seconds"), preset_key
                    )
                ),
                row.get("source_path"),
            )
            for column, value in enumerate(values):
                self.table.setItem(
                    row_index,
                    column,
                    QTableWidgetItem("—" if value in (None, "") else str(value)),
                )
        self.table.resizeColumnsToContents()
        self.summary.setText(
            f"Videos: {len(self._rows)}  |  With proxy: {ready}  |  Missing proxy: {len(self._rows) - ready}"
        )

    def queue_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Proxy Engine", "Select a video first.")
            return
        asset = self._rows[row]
        try:
            job_id = self.service.queue_proxy(
                int(asset["id"]), str(self.preset.currentData())
            )
        except Exception as exc:
            QMessageBox.warning(self, "Could not queue proxy", str(exc))
            return
        QMessageBox.information(self, "Proxy queued", f"Job {job_id} was queued.")

    def queue_missing(self) -> None:
        result = self.service.queue_missing(str(self.preset.currentData()), limit=25)
        QMessageBox.information(
            self,
            "Proxy jobs queued",
            f"Queued: {result['queued']}\nSkipped: {result['skipped']}",
        )

    def run_next(self) -> None:
        frame = self.service.processing.db.frame(
            """
            SELECT id FROM media_processing_jobs
            WHERE status='Queued' AND job_type='Generate proxy'
            ORDER BY priority, queued_at LIMIT 1
            """
        )
        if frame.empty:
            QMessageBox.information(self, "Proxy Engine", "No proxy jobs are queued.")
            return
        job_id = int(frame.iloc[0]["id"])
        thread = QThread(self)
        worker = ProxyWorker(self.service.processing, job_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda _job_id: self._finish_worker(thread))
        worker.failed.connect(lambda message: self._worker_failed(thread, message))
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._threads.append((thread, worker))
        thread.start()

    def _finish_worker(self, thread: QThread) -> None:
        self._threads = [item for item in self._threads if item[0] is not thread]
        self.refresh()

    def _worker_failed(self, thread: QThread, message: str) -> None:
        self._finish_worker(thread)
        QMessageBox.warning(self, "Proxy generation failed", message)

    @staticmethod
    def _duration(value) -> str:
        if not value:
            return "—"
        seconds = int(float(value))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _resolution(width, height) -> str:
        return "—" if not width or not height else f"{int(width)}×{int(height)}"

    @staticmethod
    def _size(value) -> str:
        if not value:
            return "—"
        size = float(value)
        units = ("B", "KB", "MB", "GB", "TB")
        index = 0
        while size >= 1024 and index < len(units) - 1:
            size /= 1024
            index += 1
        return f"{size:.1f} {units[index]}"
