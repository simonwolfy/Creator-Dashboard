from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.ui.pages.twitch import FrameModel


class ProcessingSchedulerPage(QWidget):
    def __init__(self, scheduler):
        super().__init__()
        self.scheduler = scheduler

        layout = QVBoxLayout(self)
        title = QLabel("Processing Scheduler")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.hardware = QLabel()
        self.status = QLabel()
        layout.addWidget(self.hardware)
        layout.addWidget(self.status)

        settings_row = QHBoxLayout()
        form = QFormLayout()
        self.workers = QSpinBox()
        self.workers.setRange(1, 16)
        self.workers.setValue(scheduler.max_workers)
        self.gpu_workers = QSpinBox()
        self.gpu_workers.setRange(0, 4)
        self.gpu_workers.setValue(scheduler.max_gpu_workers)
        form.addRow("Concurrent workers", self.workers)
        form.addRow("GPU proxy workers", self.gpu_workers)
        settings_row.addLayout(form)

        self.apply_button = QPushButton("Apply limits")
        self.start_button = QPushButton("Start scheduler")
        self.stop_button = QPushButton("Stop after current jobs")
        self.cancel_button = QPushButton("Stop and cancel running")
        self.run_button = QPushButton("Dispatch now")
        self.refresh_button = QPushButton("Refresh")

        for button in (
            self.apply_button,
            self.start_button,
            self.stop_button,
            self.cancel_button,
            self.run_button,
            self.refresh_button,
        ):
            settings_row.addWidget(button)
        layout.addLayout(settings_row)

        self.queue = QTableView()
        self.queue.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue.setAlternatingRowColors(True)
        layout.addWidget(self.queue)

        self.apply_button.clicked.connect(self.apply_limits)
        self.start_button.clicked.connect(self.start_scheduler)
        self.stop_button.clicked.connect(lambda: self.stop_scheduler(False))
        self.cancel_button.clicked.connect(lambda: self.stop_scheduler(True))
        self.run_button.clicked.connect(self.dispatch_now)
        self.refresh_button.clicked.connect(self.refresh)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def apply_limits(self):
        try:
            self.scheduler.configure(self.workers.value(), self.gpu_workers.value())
        except Exception as exc:
            QMessageBox.warning(self, "Scheduler", str(exc))
        self.refresh()

    def start_scheduler(self):
        self.scheduler.start()
        self.refresh()

    def stop_scheduler(self, cancel_running: bool):
        self.scheduler.stop(cancel_running=cancel_running)
        self.refresh()

    def dispatch_now(self):
        jobs = self.scheduler.run_once()
        if not jobs:
            QMessageBox.information(
                self,
                "Processing Scheduler",
                "No eligible queued jobs were available for the current worker limits.",
            )
        self.refresh()

    def refresh(self):
        snapshot = self.scheduler.snapshot()
        hardware = snapshot["hardware"]
        gpu = hardware.gpu_name or "No NVIDIA GPU detected"
        nvenc = "available" if hardware.nvenc_available else "not available"
        self.hardware.setText(
            f"Hardware: {hardware.logical_cpus} logical CPU threads | {gpu} | NVENC {nvenc}"
        )
        counts = snapshot["counts"]
        state = "Running" if snapshot["scheduler_running"] else "Stopped"
        self.status.setText(
            f"Scheduler: {state} | Active workers: {snapshot['active_workers']}/{snapshot['workers']} "
            f"| GPU workers: {snapshot['gpu_workers']} | Queued: {counts['Queued']} "
            f"| Running: {counts['Running']} | Failed: {counts['Failed']}"
        )
        self.start_button.setEnabled(not snapshot["scheduler_running"])
        self.apply_button.setEnabled(not snapshot["scheduler_running"])
        self.queue.setModel(FrameModel(self.scheduler.processing.jobs()))
