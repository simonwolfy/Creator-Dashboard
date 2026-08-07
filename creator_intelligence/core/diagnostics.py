from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import platform
import sys


@dataclass(frozen=True)
class DiagnosticsSnapshot:
    application_version: str
    python_version: str
    platform: str
    workspace: str
    database: str
    database_integrity: str
    migrations_applied: int
    migrations_pending: int
    modules_loaded: int
    module_failures: int
    health_issues: int
    startup_duration_ms: float

    def as_dict(self) -> dict:
        return asdict(self)


class DiagnosticsService:
    def build(self, *, version: str, workspace: Path, db, registry, health_checks, startup_report) -> DiagnosticsSnapshot:
        return DiagnosticsSnapshot(
            application_version=version,
            python_version=sys.version.split()[0],
            platform=platform.platform(),
            workspace=str(workspace),
            database=str(db.path),
            database_integrity=str(db.integrity_check()),
            migrations_applied=len(db.migration_history()),
            migrations_pending=len(db.pending_migrations()),
            modules_loaded=len(registry.modules),
            module_failures=len(registry.failures),
            health_issues=sum(1 for check in health_checks if not check.ok),
            startup_duration_ms=startup_report.duration_ms,
        )
