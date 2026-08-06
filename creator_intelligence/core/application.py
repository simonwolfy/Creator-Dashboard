from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging

from creator_intelligence.core.bootstrap import bootstrap_application
from creator_intelligence.core.config import ConfigService
from creator_intelligence.core.diagnostics import DiagnosticsService, DiagnosticsSnapshot
from creator_intelligence.core.health import HealthService
from creator_intelligence.core.lifecycle import ApplicationLifecycle, LifecycleReport
from creator_intelligence.core.logging import configure_logging
from creator_intelligence.core.workspace import WorkspaceManager
from creator_intelligence.data.database import Database
from creator_intelligence.services.backup import BackupService
from creator_intelligence.utils.paths import PROJECT_ROOT


@dataclass
class ApplicationRuntime:
    workspace: WorkspaceManager
    db: Database
    settings: object
    context: object
    registry: object
    health_checks: list
    startup_report: LifecycleReport
    diagnostics: DiagnosticsSnapshot


class CreatorIntelligenceApplication:
    """Owns Creator Intelligence startup, runtime services, and shutdown."""

    APPLICATION_NAME = "Creator Intelligence"
    VERSION = "5.0.0-alpha.2"

    def __init__(self, workspace_root: Path | None = None):
        self.workspace = WorkspaceManager(workspace_root or PROJECT_ROOT)
        self.logger = logging.getLogger("creator_intelligence.application")
        self.lifecycle = ApplicationLifecycle(self.logger)
        self.runtime: ApplicationRuntime | None = None
        self._db: Database | None = None
        self._settings = None
        self._context = None
        self._registry = None
        self._health_checks = []
        self._configure_pipeline()

    def _configure_pipeline(self) -> None:
        self.lifecycle.add_startup_step("Configure logging", self._configure_logging)
        self.lifecycle.add_startup_step("Initialize workspace", self._initialize_workspace)
        self.lifecycle.add_startup_step("Load configuration", self._load_configuration)
        self.lifecycle.add_startup_step("Open database", self._open_database)
        self.lifecycle.add_startup_step("Apply database migrations", self._migrate_database)
        self.lifecycle.add_startup_step("Create startup backup", self._create_backup, required=False)
        self.lifecycle.add_startup_step("Load application modules", self._load_modules)
        self.lifecycle.add_startup_step("Run startup diagnostics", self._run_diagnostics, required=False)
        self.lifecycle.add_shutdown_step("Emit application closing", self._emit_closing)
        self.lifecycle.add_shutdown_step("Clear transient services", self._clear_services)

    def start(self) -> ApplicationRuntime:
        report = self.lifecycle.start()
        if not all((self._db, self._settings, self._context, self._registry)):
            raise RuntimeError("Application startup completed without a complete runtime.")
        diagnostics = DiagnosticsService().build(
            version=self.VERSION,
            workspace=self.workspace.paths.root,
            db=self._db,
            registry=self._registry,
            health_checks=self._health_checks,
            startup_report=report,
        )
        self.runtime = ApplicationRuntime(
            workspace=self.workspace,
            db=self._db,
            settings=self._settings,
            context=self._context,
            registry=self._registry,
            health_checks=self._health_checks,
            startup_report=report,
            diagnostics=diagnostics,
        )
        self._context.set("diagnostics", diagnostics)
        self._registry.emit("application_started")
        self.logger.info(
            "%s %s ready with %s modules in %.2f ms",
            self.APPLICATION_NAME,
            self.VERSION,
            len(self._registry.modules),
            report.duration_ms,
        )
        return self.runtime

    def stop(self) -> LifecycleReport:
        return self.lifecycle.stop()

    def _configure_logging(self) -> str:
        configure_logging(self.workspace.paths.logs)
        return "structured logging ready"

    def _initialize_workspace(self) -> str:
        paths = self.workspace.initialize()
        return str(paths.root)

    def _load_configuration(self) -> str:
        config_path = self.workspace.paths.config / "settings.json"
        self._settings = ConfigService(config_path).load()
        return str(config_path)

    def _open_database(self) -> str:
        self._db = Database(self.workspace.paths.database)
        return str(self._db.path)

    def _migrate_database(self) -> str:
        assert self._db is not None
        applied = self._db.migrate()
        return f"{len(applied)} migration(s) applied"

    def _create_backup(self) -> str:
        assert self._db is not None
        if not getattr(self._settings, "auto_backup_on_start", False):
            return "startup backup disabled"
        backup = BackupService(
            self._db.path,
            self.workspace.paths.backups,
            getattr(self._settings, "backup_retention", 30),
        ).create("startup")
        return str(backup)

    def _load_modules(self) -> str:
        assert self._db is not None
        self._context, self._registry = bootstrap_application(self._db, settings=self._settings)
        self._context.set("application", self)
        self._context.set("workspace", self.workspace)
        return f"{len(self._registry.modules)} modules loaded"

    def _run_diagnostics(self) -> str:
        assert self._db is not None
        self._health_checks = HealthService(self._db.path).run()
        failures = [check for check in self._health_checks if not check.ok]
        if failures:
            self.logger.warning(
                "Startup diagnostics reported %s issue(s): %s",
                len(failures),
                "; ".join(f"{check.name}: {check.message}" for check in failures),
            )
        return f"{len(self._health_checks)} checks, {len(failures)} issues"

    def _emit_closing(self) -> None:
        if self._registry is not None:
            self._registry.emit("application_closing")

    def _clear_services(self) -> None:
        if self._context is not None:
            self._context.services.clear()
