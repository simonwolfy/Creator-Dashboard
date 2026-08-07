from __future__ import annotations

import argparse
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

from creator_intelligence.core.application import CreatorIntelligenceApplication
from creator_intelligence.core.config import ConfigService
from creator_intelligence.core.loader import REQUIRED_MODULE_IDS
from creator_intelligence.core.workspace import WorkspaceManager
from creator_intelligence.data.database import Database
from creator_intelligence.data.migration_manager import MigrationManager

ALLOWED_FRESH_ROWS = {
    "google_drive_connections",
    "notifications",
    "schema_migrations",
    "watcher_settings",
}
UPGRADE_MARKER_KEY = "release-smoke-upgrade-marker"
UPGRADE_MARKER_VALUE = "preserve-across-upgrade-and-uninstall"


def run_release_smoke() -> int:
    """Exercise packaged imports, startup, migrations, and an empty disposable workspace."""
    _verify_packaged_oauth_dependencies()
    with tempfile.TemporaryDirectory(prefix="creator-intelligence-release-smoke-") as temporary:
        workspace = Path(temporary) / "workspace"
        app = CreatorIntelligenceApplication(workspace)
        runtime = app.start()
        try:
            if set(runtime.registry.modules) != set(REQUIRED_MODULE_IDS):
                raise RuntimeError("The packaged module set is incomplete.")
            if runtime.db.integrity_check() != "ok":
                raise RuntimeError("The fresh packaged database failed its integrity check.")
            if runtime.db.pending_migrations():
                raise RuntimeError("The fresh packaged database still has pending migrations.")
            unexpected = _tables_with_unexpected_rows(runtime.db.path)
            if unexpected:
                raise RuntimeError(
                    "The fresh packaged workspace contains creator data: " + ", ".join(unexpected)
                )
        finally:
            app.stop()
    return 0


def _verify_packaged_oauth_dependencies() -> None:
    # These imports are intentionally dynamic in product services. Importing them here makes
    # the release smoke test prove that the packaged app contains its OAuth runtime.
    import keyring  # noqa: F401
    from google.oauth2.credentials import Credentials  # noqa: F401
    from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
    from googleapiclient.discovery import build  # noqa: F401

    if not callable(getattr(InstalledAppFlow, "run_local_server", None)):
        raise RuntimeError("The packaged Google OAuth loopback callback is unavailable.")
    if not callable(build):
        raise RuntimeError("The packaged Google API client is unavailable.")
    if float(getattr(keyring.get_keyring(), "priority", 0)) <= 0:
        raise RuntimeError("The packaged operating-system credential backend is unavailable.")
    _verify_oauth_loopback_round_trip(InstalledAppFlow)


def _verify_oauth_loopback_round_trip(installed_app_flow) -> None:
    """Open a local OAuth listener and complete a credential-free callback round-trip."""
    flow = installed_app_flow.from_client_config(
        {
            "installed": {
                "client_id": "release-smoke.invalid",
                "client_secret": "release-smoke-placeholder",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=["openid"],
    )
    callback_thread = None
    callback_errors = []
    captured = {}

    def authorization_url(**_kwargs):
        nonlocal callback_thread

        def send_callback():
            try:
                url = f"{flow.redirect_uri}?code=release-smoke-code&state=release-smoke-state"
                with urlopen(url, timeout=5) as response:
                    response.read()
            except Exception as exc:  # pragma: no cover - surfaced below with context
                callback_errors.append(exc)

        callback_thread = Thread(target=send_callback, name="oauth-loopback-smoke", daemon=True)
        callback_thread.start()
        return "https://accounts.google.com/o/oauth2/auth", "release-smoke-state"

    def fetch_token(*, authorization_response, **_kwargs):
        captured["authorization_response"] = authorization_response
        flow.oauth2session.token = {
            "access_token": "release-smoke-access",
            "token_type": "Bearer",
            "expires_at": 4102444800,
        }

    flow.authorization_url = authorization_url
    flow.fetch_token = fetch_token
    credentials = flow.run_local_server(
        host="127.0.0.1",
        bind_addr="127.0.0.1",
        port=0,
        authorization_prompt_message=None,
        open_browser=False,
        timeout_seconds=5,
    )
    if callback_thread is not None:
        callback_thread.join(timeout=5)
    if callback_errors:
        raise RuntimeError("The packaged OAuth loopback request failed.") from callback_errors[0]
    response = str(captured.get("authorization_response") or "")
    if "code=release-smoke-code" not in response or credentials.token != "release-smoke-access":
        raise RuntimeError("The packaged OAuth loopback callback did not complete.")


def prepare_n_minus_one_workspace(workspace_root: Path) -> int:
    """Create a genuine previous-schema workspace for packaged upgrade verification."""
    workspace = WorkspaceManager(workspace_root, name="Release Upgrade Fixture")
    paths = workspace.initialize()
    database = Database(paths.database)
    migrations = database.migration_manager.migrations
    if len(migrations) < 2:
        raise RuntimeError("At least two migrations are required for an N-1 fixture.")
    previous_migrations = migrations[:-1]
    latest_version = int(migrations[-1][0])
    with database.connect() as connection:
        MigrationManager(previous_migrations).apply(connection)
        connection.execute(
            "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)",
            (UPGRADE_MARKER_KEY, UPGRADE_MARKER_VALUE, "2026-08-06T00:00:00Z"),
        )
    config_service = ConfigService(paths.config / "settings.json")
    config = config_service.load()
    config.auto_backup_on_start = False
    config_service.save(config)
    workspace.record_application_version("n-minus-one-release-fixture")
    return latest_version


def run_upgrade_smoke(workspace_root: Path) -> int:
    """Upgrade an N-1 external workspace and prove backup and data preservation."""
    workspace = WorkspaceManager(workspace_root)
    workspace.validate()
    before = Database(workspace.paths.database)
    pending = before.pending_migrations()
    if len(pending) != 1:
        raise RuntimeError(f"Expected exactly one pending migration, found {len(pending)}.")
    latest_version = int(pending[0][0])
    if before.scalar("SELECT value FROM app_settings WHERE key=?", (UPGRADE_MARKER_KEY,)) != UPGRADE_MARKER_VALUE:
        raise RuntimeError("The N-1 workspace marker is missing before upgrade.")

    app = CreatorIntelligenceApplication(workspace.paths.root)
    runtime = app.start()
    try:
        if runtime.db.pending_migrations():
            raise RuntimeError("The packaged app left migrations pending after upgrade.")
        if runtime.db.scalar("SELECT value FROM app_settings WHERE key=?", (UPGRADE_MARKER_KEY,)) != UPGRADE_MARKER_VALUE:
            raise RuntimeError("The packaged upgrade did not preserve workspace data.")
        backups = list(workspace.paths.backups.glob("*pre_upgrade*.db"))
        if len(backups) != 1:
            raise RuntimeError(f"Expected one pre-upgrade backup, found {len(backups)}.")
        with closing(sqlite3.connect(backups[0])) as connection:
            marker = connection.execute(
                "SELECT value FROM app_settings WHERE key=?", (UPGRADE_MARKER_KEY,)
            ).fetchone()
            applied = {
                int(row[0])
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
        if not marker or marker[0] != UPGRADE_MARKER_VALUE or latest_version in applied:
            raise RuntimeError("The pre-upgrade backup is not a valid N-1 snapshot.")
    finally:
        app.stop()
    return 0


def verify_upgraded_workspace(workspace_root: Path) -> int:
    """Prove an external upgraded workspace still exists after app uninstall."""
    workspace = WorkspaceManager(workspace_root)
    workspace.validate()
    database = Database(workspace.paths.database)
    if database.pending_migrations():
        raise RuntimeError("The preserved workspace is no longer at the current schema.")
    if database.scalar("SELECT value FROM app_settings WHERE key=?", (UPGRADE_MARKER_KEY,)) != UPGRADE_MARKER_VALUE:
        raise RuntimeError("The external workspace marker was not preserved.")
    if len(list(workspace.paths.backups.glob("*pre_upgrade*.db"))) != 1:
        raise RuntimeError("The external workspace upgrade backup was not preserved.")
    return 0


def _tables_with_unexpected_rows(database_path: Path) -> list[str]:
    unexpected = []
    with closing(sqlite3.connect(database_path)) as connection:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for table in tables:
            if table in ALLOWED_FRESH_ROWS:
                continue
            quoted = table.replace('"', '""')
            count = int(connection.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0])
            if count:
                unexpected.append(table)
    return unexpected


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated release smoke checks.")
    parser.add_argument("--prepare-n-minus-one", type=Path)
    parser.add_argument("--upgrade-workspace", type=Path)
    parser.add_argument("--verify-upgraded-workspace", type=Path)
    args = parser.parse_args(argv)
    selected = [
        args.prepare_n_minus_one,
        args.upgrade_workspace,
        args.verify_upgraded_workspace,
    ]
    if sum(value is not None for value in selected) > 1:
        parser.error("select only one workspace smoke operation")
    if args.prepare_n_minus_one:
        prepare_n_minus_one_workspace(args.prepare_n_minus_one)
        return 0
    if args.upgrade_workspace:
        return run_upgrade_smoke(args.upgrade_workspace)
    if args.verify_upgraded_workspace:
        return verify_upgraded_workspace(args.verify_upgraded_workspace)
    return run_release_smoke()


if __name__ == "__main__":
    raise SystemExit(main())
