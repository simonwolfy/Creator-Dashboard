from __future__ import annotations

from threading import Thread

from PySide6.QtCore import QObject, Signal


class UpdateCheckWorker(QObject):
    result_ready = Signal(object)

    def __init__(self, checker, *, force: bool, parent=None):
        super().__init__(parent)
        self.checker = checker
        self.force = force
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        Thread(target=self._run, name="creator-update-check", daemon=True).start()

    def _run(self) -> None:
        try:
            self.result_ready.emit(self.checker.check(force=self.force))
        finally:
            self.running = False


class UpdateDownloadWorker(QObject):
    download_ready = Signal(object)
    download_failed = Signal(str)

    def __init__(self, checker, release, parent=None):
        super().__init__(parent)
        self.checker = checker
        self.release = release
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        Thread(target=self._run, name="creator-update-download", daemon=True).start()

    def _run(self) -> None:
        try:
            self.download_ready.emit(self.checker.download_and_verify(self.release))
        except Exception as exc:
            self.download_failed.emit(str(exc))
        finally:
            self.running = False
