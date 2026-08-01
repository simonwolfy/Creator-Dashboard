from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class InstallWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, service):
        super().__init__()
        self.service = service

    def run(self):
        try:
            self.completed.emit(self.service.install_with_winget())
        except Exception as exc:
            self.failed.emit(str(exc))


class FFmpegManagerPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self._thread = None
        self._worker = None

        layout = QVBoxLayout(self)
        title = QLabel("FFmpeg Manager")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.banner = QLabel()
        self.banner.setWordWrap(True)
        layout.addWidget(self.banner)

        form = QFormLayout()
        self.ready = QLabel()
        self.source = QLabel()
        self.ffmpeg_path = QLabel()
        self.ffprobe_path = QLabel()
        self.ffmpeg_version = QLabel()
        self.ffprobe_version = QLabel()
        for value in (self.ffmpeg_path, self.ffprobe_path, self.ffmpeg_version, self.ffprobe_version):
            value.setWordWrap(True)
            value.setTextInteractionFlags(value.textInteractionFlags())
        form.addRow("Status", self.ready)
        form.addRow("Detected from", self.source)
        form.addRow("FFmpeg", self.ffmpeg_path)
        form.addRow("FFmpeg version", self.ffmpeg_version)
        form.addRow("FFprobe", self.ffprobe_path)
        form.addRow("FFprobe version", self.ffprobe_version)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.install_button = QPushButton("Install with WinGet")
        self.install_button.clicked.connect(self.install)
        choose_button = QPushButton("Select FFmpeg bin folder")
        choose_button.clicked.connect(self.choose_folder)
        clear_button = QPushButton("Clear saved configuration")
        clear_button.clicked.connect(self.clear_configuration)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        actions.addWidget(self.install_button)
        actions.addWidget(choose_button)
        actions.addWidget(clear_button)
        actions.addWidget(refresh_button)
        actions.addStretch()
        layout.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        note = QLabel(
            "Creator Intelligence stores the selected executable paths in its own configuration. "
            "It does not edit the Windows PATH and does not require administrator access when WinGet can install the package for the current user."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.refresh()

    def refresh(self):
        status = self.service.status()
        self.banner.setText(status.message)
        self.ready.setText("Ready" if status.ready else "Not ready")
        self.ready.setStyleSheet("font-weight:700;color:#70d68c;" if status.ready else "font-weight:700;color:#ff9b73;")
        self.source.setText(status.source)
        self.ffmpeg_path.setText(status.ffmpeg_path or "—")
        self.ffprobe_path.setText(status.ffprobe_path or "—")
        self.ffmpeg_version.setText(status.ffmpeg_version or "—")
        self.ffprobe_version.setText(status.ffprobe_version or "—")

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select the folder containing ffmpeg.exe and ffprobe.exe")
        if not folder:
            return
        try:
            self.service.configure_bin_folder(folder)
            self.refresh()
            QMessageBox.information(self, "FFmpeg Manager", "FFmpeg was configured successfully.")
        except Exception as exc:
            QMessageBox.warning(self, "Invalid FFmpeg folder", str(exc))

    def clear_configuration(self):
        self.service.clear_configuration()
        self.refresh()

    def install(self):
        self.install_button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.banner.setText("Installing FFmpeg with Windows Package Manager. This can take several minutes...")
        self._thread = QThread(self)
        self._worker = InstallWorker(self.service)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.completed.connect(self._installed)
        self._worker.failed.connect(self._install_failed)
        self._thread.start()

    def _installed(self, _result):
        self._finish_install()
        self.refresh()
        status = self.service.status()
        if status.ready:
            QMessageBox.information(self, "FFmpeg Manager", "FFmpeg and FFprobe are installed and ready.")
        else:
            QMessageBox.information(
                self,
                "FFmpeg installed",
                "WinGet completed, but the executables were not detected yet. Restart Creator Intelligence or select the FFmpeg bin folder manually.",
            )

    def _install_failed(self, message):
        self._finish_install()
        self.refresh()
        QMessageBox.warning(self, "FFmpeg installation failed", message)

    def _finish_install(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._worker = None
        self._thread = None
        self.install_button.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setVisible(False)
