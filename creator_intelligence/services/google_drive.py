from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from creator_intelligence.core.logging import SensitiveDataFilter
from creator_intelligence.core.credential_vault import CredentialVault

SCOPES = ("https://www.googleapis.com/auth/drive.metadata.readonly",)
KEYRING_SERVICE = "Creator Intelligence"
KEYRING_USERNAME = "google-drive-oauth"


@dataclass(frozen=True)
class DriveConnectionStatus:
    configured: bool
    connected: bool
    status: str
    account_email: str | None = None
    display_name: str | None = None
    client_secrets_path: str | None = None
    last_tested_at: str | None = None
    last_error: str | None = None


class GoogleDriveService:
    """OAuth and connection foundation for Google Drive.

    OAuth tokens are stored in the operating-system credential vault through
    keyring. The SQLite database stores only non-secret connection metadata.
    """

    def __init__(
        self,
        db,
        *,
        credential_store: Any | None = None,
        oauth_factory: Callable[[str, tuple[str, ...]], Any] | None = None,
        drive_factory: Callable[[Any], Any] | None = None,
    ):
        self.db = db
        self.credential_store = credential_store or _VaultCredentialStore(CredentialVault.for_database(db))
        self.oauth_factory = oauth_factory or _default_oauth_factory
        self.drive_factory = drive_factory or _default_drive_factory

    def configure(self, client_secrets_path: str) -> None:
        path = Path(client_secrets_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError("Google OAuth client-secrets file was not found.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError("Client-secrets file is not valid JSON.") from exc
        if not isinstance(payload, dict) or not ({"installed", "web"} & payload.keys()):
            raise ValueError("This is not a Google OAuth client-secrets file.")
        now = _now()
        self.db.execute(
            """
            UPDATE google_drive_connections
            SET client_secrets_path=?, status='Configured', scopes_json=?,
                last_error=NULL, updated_at=?
            WHERE id=1
            """,
            (str(path), json.dumps(SCOPES), now),
        )

    def connect(self) -> DriveConnectionStatus:
        row = self._row()
        path = row.get("client_secrets_path")
        if not path:
            raise ValueError("Choose a Google OAuth client-secrets file first.")
        try:
            credentials = self.oauth_factory(str(path), SCOPES)
            self.credential_store.save(credentials.to_json())
            profile = self._read_profile(credentials)
            now = _now()
            self.db.execute(
                """
                UPDATE google_drive_connections
                SET account_email=?, display_name=?, status='Connected',
                    connected_at=?, last_tested_at=?, last_error=NULL, updated_at=?
                WHERE id=1
                """,
                (
                    profile.get("user", {}).get("emailAddress"),
                    profile.get("user", {}).get("displayName"),
                    now,
                    now,
                    now,
                ),
            )
        except Exception as exc:
            self._record_error(exc)
            raise
        return self.status()

    def test_connection(self) -> DriveConnectionStatus:
        try:
            credentials = self._load_credentials()
            profile = self._read_profile(credentials)
            now = _now()
            self.db.execute(
                """
                UPDATE google_drive_connections
                SET account_email=?, display_name=?, status='Connected',
                    last_tested_at=?, last_error=NULL, updated_at=?
                WHERE id=1
                """,
                (
                    profile.get("user", {}).get("emailAddress"),
                    profile.get("user", {}).get("displayName"),
                    now,
                    now,
                ),
            )
        except Exception as exc:
            self._record_error(exc)
            raise
        return self.status()

    def disconnect(self) -> DriveConnectionStatus:
        self.credential_store.delete()
        now = _now()
        self.db.execute(
            """
            UPDATE google_drive_connections
            SET account_email=NULL, display_name=NULL, status='Configured',
                connected_at=NULL, last_error=NULL, updated_at=?
            WHERE id=1
            """,
            (now,),
        )
        return self.status()

    def status(self) -> DriveConnectionStatus:
        row = self._row()
        has_token = self.credential_store.exists()
        configured = bool(row.get("client_secrets_path"))
        connected = configured and has_token and row.get("status") == "Connected"
        return DriveConnectionStatus(
            configured=configured,
            connected=connected,
            status=str(row.get("status") or "Not configured"),
            account_email=row.get("account_email"),
            display_name=row.get("display_name"),
            client_secrets_path=row.get("client_secrets_path"),
            last_tested_at=row.get("last_tested_at"),
            last_error=row.get("last_error"),
        )

    def _load_credentials(self):
        raw = self.credential_store.load()
        if not raw:
            raise RuntimeError("Google Drive is not connected.")
        try:
            from google.oauth2.credentials import Credentials
        except ImportError as exc:
            raise RuntimeError("Install Google Drive dependencies before connecting.") from exc
        credentials = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request

            credentials.refresh(Request())
            self.credential_store.save(credentials.to_json())
        return credentials

    def _read_profile(self, credentials) -> dict[str, Any]:
        drive = self.drive_factory(credentials)
        return drive.about().get(fields="user").execute()

    def _row(self) -> dict[str, Any]:
        frame = self.db.frame("SELECT * FROM google_drive_connections WHERE id=1")
        if frame.empty:
            raise RuntimeError("Google Drive migration has not been applied.")
        return frame.iloc[0].to_dict()

    def _record_error(self, exc: Exception) -> None:
        now = _now()
        self.db.execute(
            """
            UPDATE google_drive_connections
            SET status='Error', last_error=?, last_tested_at=?, updated_at=?
            WHERE id=1
            """,
            (SensitiveDataFilter.redact(exc), now, now),
        )


class _KeyringCredentialStore:
    def _keyring(self):
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError("Install the keyring package to store Google credentials securely.") from exc
        return keyring

    def save(self, value: str) -> None:
        self._keyring().set_password(KEYRING_SERVICE, KEYRING_USERNAME, value)

    def load(self) -> str | None:
        return self._keyring().get_password(KEYRING_SERVICE, KEYRING_USERNAME)

    def exists(self) -> bool:
        try:
            return bool(self.load())
        except RuntimeError:
            return False

    def delete(self) -> None:
        keyring = self._keyring()
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except keyring.errors.PasswordDeleteError:
            pass


class _VaultCredentialStore:
    def __init__(self,vault):self.vault=vault
    def save(self,value):self.vault.replace("google-drive",{"oauth_credentials":value})
    def load(self):return self.vault.load("google-drive").get("oauth_credentials")
    def exists(self):return bool(self.load())
    def delete(self):self.vault.delete("google-drive")


def _default_oauth_factory(client_secrets_path: str, scopes: tuple[str, ...]):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError("Install Google Drive dependencies before connecting.") from exc
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, scopes=scopes)
    return flow.run_local_server(port=0, open_browser=True)


def _default_drive_factory(credentials):
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("Install Google Drive dependencies before connecting.") from exc
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
