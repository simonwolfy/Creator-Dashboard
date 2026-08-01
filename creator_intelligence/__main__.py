import sys
import traceback
import logging
from PySide6.QtWidgets import QApplication, QMessageBox

from creator_intelligence.core.application import CreatorIntelligenceApplication
from creator_intelligence.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Creator Intelligence")
    app.setApplicationVersion(CreatorIntelligenceApplication.VERSION)
    app.setOrganizationName("SimonWolfy")

    core = CreatorIntelligenceApplication()
    log = logging.getLogger(__name__)

    def handle_exception(exc_type, exc_value, exc_tb):
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical("Unhandled exception\n%s", details)
        QMessageBox.critical(
            None,
            "Creator Intelligence error",
            "The application encountered an unexpected error.\n\n"
            "Details were written to logs/creator_intelligence.log"
        )

    sys.excepthook = handle_exception

    try:
        runtime = core.start()
        window = MainWindow(runtime, application_core=core)
        window.show()
        return app.exec()
    except Exception as exc:
        details = traceback.format_exc()
        log.critical("Startup failure\n%s", details)
        QMessageBox.critical(
            None,
            "Startup failed",
            f"{exc}\n\nSee the logs folder for details."
        )
        try:
            core.stop()
        except Exception:
            log.exception("Cleanup after startup failure also failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
