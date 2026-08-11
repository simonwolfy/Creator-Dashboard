from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,QDialog,QDialogButtonBox,QLabel,QMessageBox,QProgressBar,
    QPushButton,QTableWidget,QTableWidgetItem,QVBoxLayout,
)

from creator_intelligence.services.runtime_setup import RuntimeSetupService
from creator_intelligence.ui.runtime_setup_worker import RuntimeSetupWorker


class RuntimeSetupDialog(QDialog):
    def __init__(self, service=None, parent=None):
        super().__init__(parent)
        self.service = service or RuntimeSetupService()
        self.worker = None
        self.setWindowTitle("Setup Once — local processing components")
        self.resize(760, 500)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Creator Intelligence includes its Python runtime and application libraries in the "
            "installed EXE. Setup Once prepares FFmpeg/FFprobe and downloads the local Whisper "
            "base model. Internet access is required only while those components download."
        )
        explanation.setWordWrap(True); layout.addWidget(explanation)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Component", "Status", "Used for", "Details"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.install_ffmpeg = QCheckBox("Install FFmpeg and FFprobe when missing")
        self.install_ffmpeg.setChecked(True)
        self.download_model = QCheckBox("Download the Whisper base model when missing")
        self.download_model.setChecked(True)
        layout.addWidget(self.install_ffmpeg); layout.addWidget(self.download_model)
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.progress.setFormat("Ready to run Setup Once")
        layout.addWidget(self.progress)
        self.run_button = QPushButton("Run Setup Once")
        self.run_button.clicked.connect(self.run_setup); layout.addWidget(self.run_button)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.refresh()

    def refresh(self, result=None):
        result = result or self.service.status()
        self.table.setRowCount(len(result.components))
        for row, component in enumerate(result.components):
            values = (
                component.name, "Ready" if component.ready else "Not ready",
                component.required_for, component.detail,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        if result.completed:
            self.progress.setValue(100); self.progress.setFormat("All local processing components are ready")

    def run_setup(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.run_button.setEnabled(False)
        self.progress.setValue(1); self.progress.setFormat("Starting Setup Once…")
        self.worker = RuntimeSetupWorker(
            self.service,
            install_ffmpeg=self.install_ffmpeg.isChecked(),
            download_model=self.download_model.isChecked(),
            parent=self,
        )
        self.worker.progress_changed.connect(self._progress)
        self.worker.setup_finished.connect(self._finished)
        self.worker.setup_failed.connect(self._failed)
        self.worker.start()

    def _progress(self, percent, message):
        self.progress.setValue(int(percent)); self.progress.setFormat(str(message))

    def _finished(self, result):
        self.run_button.setEnabled(True); self.refresh(result)
        if result.completed:
            QMessageBox.information(self, "Setup Once complete", "Local video and transcription components are ready.")
        else:
            QMessageBox.warning(self, "Setup needs attention", "Setup finished, but one or more selected components are still unavailable.")

    def _failed(self, message):
        self.run_button.setEnabled(True); self.progress.setFormat("Setup failed — you can retry")
        QMessageBox.critical(self, "Setup Once failed", message)

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Setup is running", "Wait for the current download or installation to finish.")
            return
        super().reject()
