from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class RuntimeSetupWorker(QThread):
    progress_changed = Signal(int, str)
    setup_finished = Signal(object)
    setup_failed = Signal(str)

    def __init__(self, service, *, install_ffmpeg, download_model, parent=None):
        super().__init__(parent)
        self.service = service
        self.install_ffmpeg = bool(install_ffmpeg)
        self.download_model = bool(download_model)

    def run(self):
        try:
            result = self.service.install(
                install_ffmpeg=self.install_ffmpeg,
                download_model=self.download_model,
                progress=lambda percent, message: self.progress_changed.emit(percent, message),
            )
        except Exception as exc:
            self.setup_failed.emit(str(exc))
            return
        self.setup_finished.emit(result)
