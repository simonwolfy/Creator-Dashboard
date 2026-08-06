from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.ui.pages.twitch import FrameModel


class ThumbnailWorker(QObject):
    finished = Signal(int)
    failed = Signal(str)

    def __init__(self, processing, job_id: int):
        super().__init__()
        self.processing = processing
        self.job_id = job_id

    def run(self):
        try:
            self.processing.run_job(self.job_id)
            self.finished.emit(self.job_id)
        except Exception as exc:
            self.failed.emit(str(exc))


class ThumbnailEnginePage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self._threads = []

        layout = QVBoxLayout(self)
        title = QLabel('Thumbnail Engine')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(QLabel('Generate disposable preview frames from local videos. Source files are never modified.'))

        controls = QHBoxLayout()
        for text, callback in (
            ('Queue selected', self.queue_selected),
            ('Queue missing thumbnails', self.queue_missing),
            ('Run next thumbnail job', self.run_next),
            ('Refresh', self.refresh),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)

        self.table = QTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.refresh()

    def _selected_id(self):
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return int(self.table.model().frame.iloc[index.row()]['id'])

    def _settings(self):
        interval, ok = QInputDialog.getInt(self, 'Thumbnail interval', 'Seconds between thumbnails', 300, 30, 3600, 30)
        if not ok:
            return None
        width, ok = QInputDialog.getInt(self, 'Thumbnail width', 'Width in pixels', 640, 160, 1920, 80)
        return (interval, width) if ok else None

    def queue_selected(self):
        asset_id = self._selected_id()
        if asset_id is None:
            return
        settings = self._settings()
        if settings is None:
            return
        try:
            self.service.queue_thumbnails(asset_id, *settings)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, 'Unable to queue thumbnails', str(exc))

    def queue_missing(self):
        settings = self._settings()
        if settings is None:
            return
        result = self.service.queue_missing(*settings)
        QMessageBox.information(self, 'Thumbnail queue', f"Queued: {result['queued']}\nSkipped: {result['skipped']}")
        self.refresh()

    def run_next(self):
        jobs = self.service.processing.db.frame(
            "SELECT id FROM media_processing_jobs WHERE status='Queued' AND job_type='Generate thumbnails' ORDER BY priority,queued_at LIMIT 1"
        )
        if jobs.empty:
            QMessageBox.information(self, 'Thumbnail Engine', 'No queued thumbnail jobs.')
            return
        job_id = int(jobs.iloc[0]['id'])
        thread = QThread(self)
        worker = ThumbnailWorker(self.service.processing, job_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda *_: self._done(thread))
        worker.failed.connect(lambda message: self._failed(thread, message))
        self._threads.append((thread, worker))
        thread.start()

    def _done(self, thread):
        thread.quit()
        self._threads = [item for item in self._threads if item[0] is not thread]
        self.refresh()

    def _failed(self, thread, message):
        self._done(thread)
        QMessageBox.warning(self, 'Thumbnail generation failed', message)

    def refresh(self):
        rows = self.service.assets()
        import pandas as pd
        frame = pd.DataFrame(rows)
        keep = ['id', 'display_name', 'duration_seconds', 'width', 'height', 'thumbnail_count', 'latest_thumbnail_path', 'source_path']
        for column in keep:
            if column not in frame:
                frame[column] = None
        self.table.setModel(FrameModel(frame[keep]))
        with_thumbnails = sum(1 for row in rows if int(row.get('thumbnail_count') or 0) > 0)
        self.summary.setText(f'Videos: {len(rows)}  |  With thumbnails: {with_thumbnails}  |  Missing thumbnails: {len(rows)-with_thumbnails}')
