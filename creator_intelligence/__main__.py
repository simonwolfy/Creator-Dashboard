import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from creator_intelligence.core.application import CreatorIntelligenceApplication
from creator_intelligence.core.onboarding import OnboardingService
from creator_intelligence.services.runtime_setup import RuntimeSetupService
from creator_intelligence.ui.dialogs.onboarding import OnboardingWizard
from creator_intelligence.ui.main_window import MainWindow


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--release-smoke-test" in arguments:
        from creator_intelligence.core.release_smoke import run_release_smoke

        return run_release_smoke()
    if "--release-upgrade-smoke-test" in arguments:
        from creator_intelligence.core.release_smoke import run_upgrade_smoke

        index = arguments.index("--release-upgrade-smoke-test")
        if index + 1 >= len(arguments):
            raise SystemExit("--release-upgrade-smoke-test requires a workspace path")
        return run_upgrade_smoke(Path(arguments[index + 1]))
    app = QApplication(sys.argv)
    app.setApplicationName("Creator Intelligence")
    app.setApplicationVersion(CreatorIntelligenceApplication.VERSION)
    app.setOrganizationName("Creator Intelligence")

    onboarding = OnboardingService(runtime_setup=RuntimeSetupService())
    if onboarding.needs_onboarding():
        wizard = OnboardingWizard(onboarding)
        if not wizard.exec():
            return 0
    profile = onboarding.profile()
    core = CreatorIntelligenceApplication(Path(profile.workspace_root))
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
        runtime.context.set("onboarding", onboarding)
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
