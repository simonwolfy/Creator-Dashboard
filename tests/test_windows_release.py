from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from creator_intelligence.core.application import CreatorIntelligenceApplication
from creator_intelligence.core.workspace import WorkspaceManager

ROOT = Path(__file__).resolve().parents[1]


def test_release_pipeline_has_privacy_history_gate_and_artifacts():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "python -m pytest" in workflow
    assert "privacy_audit --history" in workflow
    assert "PyInstaller" in workflow
    assert "ISCC.exe" in workflow
    assert "Get-FileHash" in workflow
    assert "upload-artifact" in workflow


def test_installer_preserves_external_workspaces_and_creates_shortcuts():
    installer = (ROOT / "installer" / "CreatorIntelligence.iss").read_text(encoding="utf-8")
    assert "{group}" in installer
    assert "{autodesktop}" in installer
    assert "Creator Intelligence Workspace" not in installer
    assert 'Name: "{app}"' in installer


def test_existing_workspace_is_backed_up_before_pending_migrations(tmp_path):
    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.initialize()
    with sqlite3.connect(workspace.paths.database) as connection:
        connection.execute("CREATE TABLE legacy_marker(value TEXT)")
        connection.execute("INSERT INTO legacy_marker VALUES ('preserve me')")

    app = CreatorIntelligenceApplication(workspace.paths.root)
    app._settings = type("Settings", (), {"backup_retention": 30})()
    app._open_database()
    detail = app._protect_upgrade()

    backups = list(workspace.paths.backups.glob("*pre_upgrade*.db"))
    assert "protected by" in detail
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT value FROM legacy_marker").fetchone()[0] == "preserve me"


def test_successful_start_records_application_version(tmp_path):
    app = CreatorIntelligenceApplication(tmp_path / "workspace")
    runtime = app.start()
    metadata = json.loads(runtime.workspace.paths.metadata.read_text(encoding="utf-8"))
    assert metadata["application_version"] == app.VERSION
    app.stop()
