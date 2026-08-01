import sys
import traceback
import logging
from PySide6.QtWidgets import QApplication, QMessageBox
from creator_intelligence.core.logging import configure_logging
from creator_intelligence.core.config import ConfigService
from creator_intelligence.data.database import Database
from creator_intelligence.services.backup import BackupService
from creator_intelligence.ui.main_window import MainWindow
from creator_intelligence.utils.paths import DB_PATH, BACKUP_DIR

def main():
    configure_logging()
    log = logging.getLogger(__name__)
    app = QApplication(sys.argv)
    app.setApplicationName("Creator Intelligence 3.0")
    app.setOrganizationName("SimonWolfy")

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
        db = Database(DB_PATH)
        db.migrate()
        config = ConfigService().load()
        if config.auto_backup_on_start:
            BackupService(DB_PATH, BACKUP_DIR, config.backup_retention).create("startup")
        window = MainWindow(db)
        window.show()
        log.info("Application started")
        return app.exec()
    except Exception as exc:
        details = traceback.format_exc()
        log.critical("Startup failure\n%s", details)
        QMessageBox.critical(None, "Startup failed", f"{exc}\n\nSee the logs folder for details.")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
