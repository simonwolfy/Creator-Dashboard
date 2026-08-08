from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from creator_intelligence.core.logging import SensitiveDataFilter
from creator_intelligence.core.credential_vault import CredentialVault
from creator_intelligence.services.connection_lifecycle import ConnectionState, ConnectionStatus

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
    state: ConnectionState = ConnectionState.NOT_CONFIGURED
    message: str = "Connect Google Drive to browse and synchronize folder metadata."
    granted_scopes: tuple[str, ...] = ()
    token_expires_at: str | None = None
    last_synced_at: str | None = None
    last_sync_summary: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = ConnectionStatus(
            provider="google drive",
            state=self.state,
            message=self.message,
            account_id=self.account_email,
            account_name=self.display_name,
            granted_scopes=self.granted_scopes,
            required_scopes=SCOPES,
            expires_at=self.token_expires_at,
            last_validated_at=self.last_tested_at,
            last_error=self.last_error,
        ).as_dict()
        result.update(
            status=self.status,
            client_secrets_path=self.client_secrets_path,
            last_synced_at=self.last_synced_at,
            last_sync_summary=self.last_sync_summary,
        )
        return result


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
        revoke_request: Callable[[str], Any] | None = None,
    ):
        self.db = db
        self.credential_store = credential_store or _VaultCredentialStore(CredentialVault.for_database(db))
        self.oauth_factory = oauth_factory or _default_oauth_factory
        self.drive_factory = drive_factory or _default_drive_factory
        self.revoke_request = revoke_request or _default_revoke_request

    def configure(self, client_secrets_path: str) -> None:
        path = Path(client_secrets_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError("Google OAuth client-secrets file was not found.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError("Client-secrets file is not valid JSON.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("installed"), dict):
            raise ValueError("Choose an OAuth client-secrets file created as a Google Desktop app.")
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
            scopes = self._credential_scopes(credentials)
            expiry = self._credential_expiry(credentials)
            self.db.execute(
                """
                UPDATE google_drive_connections
                SET account_email=?, display_name=?, status='Connected',
                    connected_at=?, last_tested_at=?, last_error=NULL, updated_at=?,
                    granted_scopes_json=?,token_expires_at=?
                WHERE id=1
                """,
                (
                    profile.get("user", {}).get("emailAddress"),
                    profile.get("user", {}).get("displayName"),
                    now,
                    now,
                    now,
                    json.dumps(scopes),
                    expiry,
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
            scopes = self._credential_scopes(credentials)
            self.db.execute(
                """
                UPDATE google_drive_connections
                SET account_email=?, display_name=?, status='Connected',
                    last_tested_at=?, last_error=NULL, updated_at=?,
                    granted_scopes_json=?,token_expires_at=?
                WHERE id=1
                """,
                (
                    profile.get("user", {}).get("emailAddress"),
                    profile.get("user", {}).get("displayName"),
                    now,
                    now,
                    json.dumps(scopes),
                    self._credential_expiry(credentials),
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
                connected_at=NULL, last_error=NULL,token_expires_at=NULL,
                granted_scopes_json='[]',updated_at=?
            WHERE id=1
            """,
            (now,),
        )
        return self.status()

    def revoke_and_disconnect(self) -> DriveConnectionStatus:
        warning = None
        raw = self.credential_store.load()
        if raw:
            try:
                payload = json.loads(raw)
                token = payload.get("refresh_token") or payload.get("token")
                if token:
                    self.revoke_request(str(token))
            except Exception as exc:
                warning = SensitiveDataFilter.redact(exc)
        status = self.disconnect()
        if warning:
            self.db.execute(
                "UPDATE google_drive_connections SET last_error=?,updated_at=? WHERE id=1",
                (f"Local credentials cleared; remote revocation could not be confirmed: {warning}", _now()),
            )
            status = self.status()
        return status

    def sync_now(self) -> dict[str, Any]:
        """Refresh account metadata and a lightweight My Drive folder summary."""
        try:
            credentials = self._load_credentials()
            drive = self.drive_factory(credentials)
            profile = drive.about().get(fields="user").execute()
            response = drive.files().list(
                q="mimeType='application/vnd.google-apps.folder' and trashed=false and 'root' in parents",
                fields="nextPageToken,files(id)",pageSize=1000,spaces="drive",
            ).execute()
            folder_count = len(response.get("files") or [])
            summary = f"Found {folder_count} top-level folder(s)"
            now = _now()
            self.db.execute(
                """UPDATE google_drive_connections SET account_email=?,display_name=?,
                   status='Connected',last_tested_at=?,last_synced_at=?,last_sync_summary=?,
                   last_error=NULL,granted_scopes_json=?,token_expires_at=?,updated_at=? WHERE id=1""",
                (
                    profile.get("user", {}).get("emailAddress"),
                    profile.get("user", {}).get("displayName"),now,now,summary,
                    json.dumps(self._credential_scopes(credentials)),
                    self._credential_expiry(credentials),now,
                ),
            )
            return {"folders": folder_count, "summary": summary, "last_synced_at": now}
        except Exception as exc:
            self._record_error(exc)
            raise RuntimeError(SensitiveDataFilter.redact(exc)) from None

    def status(self) -> DriveConnectionStatus:
        row = self._row()
        has_token = self.credential_store.exists()
        configured = bool(row.get("client_secrets_path"))
        saved_status = str(row.get("status") or "Not configured")
        state = self._state(saved_status, configured, has_token)
        connected = configured and has_token and state in {ConnectionState.CONNECTED, ConnectionState.LIMITED}
        try:
            granted = tuple(json.loads(row.get("granted_scopes_json") or "[]"))
        except (TypeError, ValueError):
            granted = ()
        return DriveConnectionStatus(
            configured=configured,
            connected=connected,
            status=saved_status,
            account_email=row.get("account_email"),
            display_name=row.get("display_name"),
            client_secrets_path=row.get("client_secrets_path"),
            last_tested_at=row.get("last_tested_at"),
            last_error=row.get("last_error"),
            state=state,
            message=self._message(state),
            granted_scopes=granted,
            token_expires_at=row.get("token_expires_at"),
            last_synced_at=row.get("last_synced_at"),
            last_sync_summary=row.get("last_sync_summary"),
        )

    def connection_status(self) -> dict[str, Any]:
        result = self.status().as_dict()
        result["capabilities"] = [
            {"capability": "Browse folder and file metadata", "available": result["can_sync"]},
            {"capability": "Download file contents", "available": False},
            {"capability": "Create, edit, move, or delete Drive files", "available": False},
        ]
        return result

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
            self.db.execute(
                "UPDATE google_drive_connections SET token_expires_at=?,updated_at=? WHERE id=1",
                (self._credential_expiry(credentials), _now()),
            )
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
        state = _connection_state_for_error(exc)
        self.db.execute(
            """
            UPDATE google_drive_connections
            SET status=?, last_error=?, last_tested_at=?, updated_at=?
            WHERE id=1
            """,
            (state.value.title(), SensitiveDataFilter.redact(exc), now, now),
        )

    @staticmethod
    def _credential_scopes(credentials) -> tuple[str, ...]:
        scopes = getattr(credentials, "scopes", None) or SCOPES
        return tuple(str(scope) for scope in scopes)

    @staticmethod
    def _credential_expiry(credentials) -> str | None:
        expiry = getattr(credentials, "expiry", None)
        return expiry.isoformat() if expiry else None

    @staticmethod
    def _state(status: str, configured: bool, has_token: bool) -> ConnectionState:
        if not configured:
            return ConnectionState.NOT_CONFIGURED
        if not has_token:
            return ConnectionState.DISCONNECTED
        normalized = status.strip().lower()
        mapping = {
            "connected": ConnectionState.CONNECTED,
            "limited": ConnectionState.LIMITED,
            "expired": ConnectionState.EXPIRED,
            "revoked": ConnectionState.REVOKED,
            "error": ConnectionState.ERROR,
        }
        return mapping.get(normalized, ConnectionState.CONNECTING)

    @staticmethod
    def _message(state: ConnectionState) -> str:
        return {
            ConnectionState.NOT_CONFIGURED: "Choose a Google Desktop OAuth file to start.",
            ConnectionState.DISCONNECTED: "Google Drive is configured but not connected.",
            ConnectionState.CONNECTING: "Google Drive setup is ready; finish connecting the account.",
            ConnectionState.CONNECTED: "Google Drive metadata access is ready.",
            ConnectionState.LIMITED: "Google Drive is connected, but an API limit is temporarily blocking refreshes.",
            ConnectionState.EXPIRED: "The Google Drive session expired and could not refresh. Reconnect the account.",
            ConnectionState.REVOKED: "Google Drive access was revoked. Reconnect the account to continue.",
            ConnectionState.ERROR: "Google Drive could not be validated. Review the error and try again.",
        }[state]


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


def _default_revoke_request(token: str) -> None:
    request = Request(
        "https://oauth2.googleapis.com/revoke",
        data=urlencode({"token": token}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(request, timeout=30):
        return None


def _connection_state_for_error(exc: Exception) -> ConnectionState:
    text = str(exc).lower()
    if "invalid_grant" in text or "revoked" in text or "deleted_client" in text:
        return ConnectionState.REVOKED
    if any(marker in text for marker in ("invalid credentials", "http 401", "unauthorized", "expired")):
        return ConnectionState.EXPIRED
    if any(marker in text for marker in (
        "quota", "ratelimitexceeded", "rate limit", "too many requests", "http 429",
    )):
        return ConnectionState.LIMITED
    return ConnectionState.ERROR


def _now() -> str:
    return datetime.now(UTC).isoformat()
