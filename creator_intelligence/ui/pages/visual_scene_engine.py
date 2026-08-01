from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableView,
    QAbstractItemView, QDoubleSpinBox, QMessageBox,
)

from creator_intelligence.ui.pages.twitch import FrameModel


class SceneWorker(QObject):
    progress = Signal(float, str)
    finished = Signal(int)
    failed = Signal(str)

    def __init__(self, service, media_asset_id: int, threshold: float, min_gap: float):
        super().__init__()
        self.service = service
        self.media_asset_id = media_asset_id
        self.threshold = threshold
        self.min_gap = min_gap

    def run(self):
        try:
            result = self.service.detect(
                self.media_asset_id,
                threshold=self.threshold,
                min_gap_seconds=self.min_gap,
                progress_callback=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.finished.emit(len(result))
        except Exception as exc:
            self.failed.emit(str(exc))


class VisualSceneEnginePage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self._thread = None
        self._worker = None

        layout = QVBoxLayout(self)
        title = QLabel("Visual Scene Detection")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "Detect hard cuts and major visual changes with FFmpeg. "
            "The original video is never modified."
        ))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Sensitivity threshold"))
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.05, 0.95)
        self.threshold.setSingleStep(0.05)
        self.threshold.setDecimals(2)
        self.threshold.setValue(0.35)
        controls.addWidget(self.threshold)

        controls.addWidget(QLabel("Minimum gap (seconds)"))
        self.min_gap = QDoubleSpinBox()
        self.min_gap.setRange(0.0, 60.0)
        self.min_gap.setSingleStep(0.5)
        self.min_gap.setValue(1.0)
        controls.addWidget(self.min_gap)

        self.run_button = QPushButton("Analyze selected")
        self.run_button.clicked.connect(self.analyze)
        controls.addWidget(self.run_button)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        controls.addStretch()
        layout.addLayout(controls)

        self.status = QLabel("Ready")
        layout.addWidget(self.status)

        self.assets = QTableView()
        self.assets.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.assets.clicked.connect(lambda _: self.refresh_changes())
        layout.addWidget(self.assets, 2)

        layout.addWidget(QLabel("Detected scene changes"))
        self.changes = QTableView()
        self.changes.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.changes, 3)
        self.refresh()

    def selected_asset_id(self):
        index = self.assets.currentIndex()
        if not index.isValid():
            return None
        return int(self.assets.model().frame.iloc[index.row()]["id"])

    def refresh(self):
        selected = self.selected_asset_id()
        self.assets.setModel(FrameModel(self.service.assets()))
        if selected is not None:
            frame = self.assets.model().frame
            matches = frame.index[frame["id"] == selected].tolist()
            if matches:
                self.assets.selectRow(int(matches[0]))
        self.refresh_changes()

    def refresh_changes(self):
        asset_id = self.selected_asset_id()
        self.changes.setModel(FrameModel(
            self.service.changes(asset_id) if asset_id else self.service.changes(-1)
        ))

    def analyze(self):
        asset_id = self.selected_asset_id()
        if asset_id is None:
            QMessageBox.warning(self, "No video selected", "Select a local video first.")
            return
        if self._thread is not None:
            return

        self.run_button.setEnabled(False)
        self.status.setText("Starting visual scene analysis…")
        thread = QThread(self)
        worker = SceneWorker(
            self.service,
            asset_id,
            self.threshold.value(),
            self.min_gap.value(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(
            lambda pct, msg: self.status.setText(f"{pct:.1f}% — {msg}")
        )
        worker.finished.connect(self._finished)
        worker.failed.connect(self._failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _finished(self, count: int):
        self.status.setText(f"Complete — {count} visual scene changes detected")
        self.refresh()

    def _failed(self, message: str):
        self.status.setText("Analysis failed")
        QMessageBox.critical(self, "Visual scene detection failed", message)

    def _cleanup(self):
        self._thread = None
        self._worker = None
        self.run_button.setEnabled(True)
