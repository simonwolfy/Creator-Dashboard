from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from creator_intelligence.core.application import CreatorIntelligenceApplication
from creator_intelligence.core.release_smoke import (
    prepare_n_minus_one_workspace,
    run_release_smoke,
    run_upgrade_smoke,
    verify_upgraded_workspace,
)
from creator_intelligence.core.release_verification import (
    release_rank,
    verify_artifacts,
    verify_bundle,
    verify_source,
    write_manifest,
)
from creator_intelligence.core.versioning import APPLICATION_VERSION
from creator_intelligence.core.workspace import WorkspaceManager

ROOT = Path(__file__).resolve().parents[1]


def test_source_launcher_starts_windowless_python_and_explains_missing_setup():
    launcher = (ROOT / "START_CREATOR_INTELLIGENCE.vbs").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert ".venv\\Scripts\\pythonw.exe" in launcher
    assert "shell.Run command, 0, False" in launcher
    assert "Run SETUP_ONCE.bat" in launcher
    assert "START_CREATOR_INTELLIGENCE.vbs" in readme


def test_release_pipeline_has_privacy_history_gate_and_artifacts():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "python -m pytest" in workflow
    assert "privacy_audit --history" in workflow
    assert "PyInstaller" in workflow
    assert "ISCC.exe" in workflow
    assert "Get-FileHash" in workflow
    assert "upload-artifact" in workflow
    assert "--release-smoke-test" in workflow
    assert "release_verification --artifacts release" in workflow
    assert "release_verification --bundle" in workflow
    assert "--draft" in workflow
    assert 'Contains("-")' in workflow
    assert '"--prerelease"' in workflow
    assert "actions/attest@v4" in workflow
    assert "--write-manifest release" in workflow
    assert "WINDOWS_SIGNING_CERTIFICATE_BASE64" in workflow
    assert "WINDOWS_SIGNING_CERTIFICATE_PASSWORD" in workflow
    assert "Get-AuthenticodeSignature" in workflow
    assert "--prepare-n-minus-one" in workflow
    assert "--release-upgrade-smoke-test" in workflow
    assert "--verify-upgraded-workspace" in workflow
    assert "simulated downgrade" in workflow


def test_installer_preserves_external_workspaces_and_creates_shortcuts():
    installer = (ROOT / "installer" / "CreatorIntelligence.iss").read_text(encoding="utf-8")
    assert "{group}" in installer
    assert "{autodesktop}" in installer
    assert "Creator Intelligence Workspace" not in installer
    assert '[UninstallDelete]' not in installer
    assert 'filesandordirs; Name: "{app}"' not in installer
    assert "#ifndef MyAppVersion" in installer
    assert "CloseApplications=yes" in installer
    assert "RestartApplications=no" in installer
    assert "Flags: ignoreversion" not in installer
    assert "AppUpdatesURL=" in installer
    assert "function InitializeSetup(): Boolean" in installer
    assert "ReleaseRank" in installer
    assert "CompareStr" in installer
    assert "SuppressibleMsgBox" in installer
    assert "\n      MsgBox(" not in installer


def test_installer_release_rank_orders_prereleases_and_prevents_downgrades():
    versions = [
        "5.0.0-dev.1",
        "5.0.0-alpha.1",
        "5.0.0-alpha.2",
        "5.0.0-beta.1",
        "5.0.0-rc.1",
        "5.0.0",
        "5.0.0.post1",
        "5.0.1-alpha.1",
    ]
    assert [release_rank(version) for version in versions] == sorted(
        release_rank(version) for version in versions
    )


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


def test_n_minus_one_workspace_upgrade_is_backed_up_and_preserves_data(tmp_path):
    root = tmp_path / "upgrade-workspace"
    latest_version = prepare_n_minus_one_workspace(root)
    workspace = WorkspaceManager(root)
    with closing(sqlite3.connect(workspace.paths.database)) as connection:
        applied = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        drive_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(google_drive_connections)")
        }
    assert latest_version not in applied
    assert "video_asset_metadata" in tables
    assert "content_pipeline" in tables
    assert "granted_scopes_json" not in drive_columns

    assert run_upgrade_smoke(root) == 0
    assert verify_upgraded_workspace(root) == 0
    with closing(sqlite3.connect(workspace.paths.database)) as connection:
        upgraded_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(google_drive_connections)")
        }
    assert {"granted_scopes_json", "token_expires_at", "last_synced_at"} <= upgraded_columns


def test_source_release_contract_and_exact_tag():
    checks = verify_source(ROOT, tag=f"v{APPLICATION_VERSION}")
    assert len(checks) >= 5


def test_release_artifact_checksum_contract(tmp_path):
    name = f"CreatorIntelligence-{APPLICATION_VERSION}-windows-x64-setup.exe"
    installer = tmp_path / name
    installer.write_bytes(b"x" * 2048)
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    (tmp_path / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="ascii")
    manifest = write_manifest(
        tmp_path,
        commit="a" * 40,
        built_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["installer"]["sha256"] == digest
    assert payload["commit"] == "a" * 40
    assert len(verify_artifacts(tmp_path)) == 3


def test_disposable_release_smoke_starts_with_no_creator_data():
    assert run_release_smoke() == 0


def test_standalone_bundle_contract_rejects_runtime_state(tmp_path):
    bundle = tmp_path / "CreatorIntelligence"
    (bundle / "_internal" / "config").mkdir(parents=True)
    (bundle / "CreatorIntelligence.exe").write_bytes(b"exe")
    (bundle / "_internal" / "config" / "modules.json").write_text("{}", encoding="utf-8")
    assert len(verify_bundle(bundle)) == 2
    (bundle / "_internal" / "workspace.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="runtime data"):
        verify_bundle(bundle)
