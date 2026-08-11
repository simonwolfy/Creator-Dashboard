from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
import hashlib
import json
import math
import random
import re
import threading
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from creator_intelligence.core.credential_vault import CredentialVault
from creator_intelligence.services.connection_lifecycle import (
    ConnectionState,
    ConnectionStatus,
)

@dataclass
class LiveSnapshot:
    captured_at: str
    viewers: int
    followers_total: int | None = None
    subscribers_total: int | None = None
    revenue_total: float | None = None
    chat_messages_minute: int | None = None
    unique_chatters_5m: int | None = None
    current_game: str | None = None
    current_title: str | None = None
    obs_scene: str | None = None
    recording_active: bool | None = None

class LiveStreamService:
    TWITCH_SCOPES = (
        "user:read:chat",
        "moderator:read:followers",
        "channel:read:subscriptions",
    )
    TWITCH_SCOPE_CAPABILITIES = {
        "user:read:chat": "Read live chat",
        "moderator:read:followers": "Read follower totals and follow events",
        "channel:read:subscriptions": "Read subscriber totals",
    }
    TWITCH_VALIDATION_INTERVAL = timedelta(hours=1)

    def __init__(self, db, notifications=None, credential_vault=None):
        self.db = db
        self.notifications = notifications
        self.vault = credential_vault or CredentialVault.for_database(db)
        self._twitch_refresh_lock = threading.Lock()
        self._ensure_schema()
        self._migrate_credentials()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS live_sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key TEXT NOT NULL UNIQUE,
                platform TEXT NOT NULL DEFAULT 'Twitch',
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'Live',
                title TEXT,
                game TEXT,
                broadcaster_id TEXT,
                twitch_stream_id TEXT,
                obs_profile TEXT,
                obs_collection TEXT,
                starting_followers INTEGER,
                ending_followers INTEGER,
                starting_subscribers INTEGER,
                ending_subscribers INTEGER,
                starting_revenue REAL DEFAULT 0,
                ending_revenue REAL DEFAULT 0,
                predicted_average_viewers REAL,
                predicted_peak_viewers REAL,
                projected_average_viewers REAL,
                projected_peak_viewers REAL,
                actual_average_viewers REAL,
                actual_peak_viewers INTEGER,
                performance_score REAL,
                tracking_gap_seconds INTEGER DEFAULT 0,
                source_mode TEXT DEFAULT 'simulation',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS live_metric_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                elapsed_seconds INTEGER NOT NULL,
                viewers INTEGER DEFAULT 0,
                rolling_average_5m REAL,
                session_average REAL,
                projected_average REAL,
                projected_peak REAL,
                viewer_velocity_1m REAL,
                viewer_velocity_5m REAL,
                followers_total INTEGER,
                followers_gained INTEGER DEFAULT 0,
                subscribers_total INTEGER,
                subscribers_gained INTEGER DEFAULT 0,
                revenue_total REAL DEFAULT 0,
                revenue_per_hour REAL DEFAULT 0,
                chat_messages_minute INTEGER DEFAULT 0,
                unique_chatters_5m INTEGER DEFAULT 0,
                retention_estimate REAL,
                current_game TEXT,
                current_title TEXT,
                obs_scene TEXT,
                recording_active INTEGER DEFAULT 0,
                source_payload_json TEXT,
                UNIQUE(session_id,captured_at),
                FOREIGN KEY(session_id) REFERENCES live_sessions(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_live_snapshots_session
               ON live_metric_snapshots(session_id,captured_at)""",
            """CREATE TABLE IF NOT EXISTS live_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                occurred_at TEXT NOT NULL,
                elapsed_seconds INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT DEFAULT 'Info',
                title TEXT NOT NULL,
                description TEXT,
                source TEXT,
                external_id TEXT,
                payload_json TEXT,
                UNIQUE(session_id,source,external_id),
                FOREIGN KEY(session_id) REFERENCES live_sessions(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_live_events_session
               ON live_events(session_id,occurred_at)""",
            """CREATE TABLE IF NOT EXISTS stream_markers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                occurred_at TEXT NOT NULL,
                elapsed_seconds INTEGER NOT NULL,
                marker_type TEXT NOT NULL,
                label TEXT NOT NULL,
                strength_score REAL DEFAULT 0,
                confidence REAL DEFAULT 0,
                suggested_content_type TEXT,
                supporting_metrics_json TEXT,
                source_event_id INTEGER,
                review_status TEXT DEFAULT 'Unreviewed',
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES live_sessions(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_stream_markers_session
               ON stream_markers(session_id,elapsed_seconds)""",
            """CREATE TABLE IF NOT EXISTS live_integration_settings(
                id INTEGER PRIMARY KEY CHECK(id=1),
                twitch_enabled INTEGER DEFAULT 0,
                twitch_client_id TEXT,
                twitch_broadcaster_id TEXT,
                twitch_access_token TEXT,
                twitch_refresh_token TEXT,
                twitch_token_expires_at TEXT,
                twitch_account_name TEXT,
                twitch_connection_state TEXT DEFAULT 'not_configured',
                twitch_granted_scopes_json TEXT DEFAULT '[]',
                twitch_last_validated_at TEXT,
                twitch_last_error TEXT,
                obs_enabled INTEGER DEFAULT 0,
                obs_host TEXT DEFAULT '127.0.0.1',
                obs_port INTEGER DEFAULT 4455,
                obs_password TEXT,
                polling_interval_seconds INTEGER DEFAULT 60,
                store_raw_chat INTEGER DEFAULT 0,
                simulation_mode INTEGER DEFAULT 1,
                auto_start_session INTEGER DEFAULT 1,
                viewer_spike_stddev REAL DEFAULT 2.0,
                chat_spike_multiplier REAL DEFAULT 2.5,
                follow_spike_count INTEGER DEFAULT 3,
                follow_spike_window_minutes INTEGER DEFAULT 5,
                raid_marker_min_viewers INTEGER DEFAULT 10,
                updated_at TEXT
            )""",
            """INSERT OR IGNORE INTO live_integration_settings(
                id,updated_at
            ) VALUES(1,datetime('now'))""",
            """CREATE TABLE IF NOT EXISTS live_chat_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                message_id TEXT NOT NULL UNIQUE,
                captured_at TEXT NOT NULL,
                chatter_user_id TEXT,
                chatter_user_name TEXT NOT NULL,
                message_text TEXT NOT NULL,
                color TEXT,
                badges_json TEXT NOT NULL DEFAULT '[]',
                payload_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(session_id) REFERENCES live_sessions(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_live_chat_captured
               ON live_chat_messages(captured_at)""",
            """CREATE TABLE IF NOT EXISTS live_chat_activity_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                message_id TEXT NOT NULL UNIQUE,
                captured_at TEXT NOT NULL,
                chatter_hash TEXT,
                FOREIGN KEY(session_id) REFERENCES live_sessions(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_live_chat_activity_captured
               ON live_chat_activity_events(captured_at)""",
            """CREATE TABLE IF NOT EXISTS twitch_channel_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                broadcaster_id TEXT NOT NULL,
                is_live INTEGER NOT NULL DEFAULT 0,
                stream_id TEXT,
                title TEXT,
                game TEXT,
                viewers INTEGER NOT NULL DEFAULT 0,
                followers_total INTEGER,
                subscribers_total INTEGER,
                started_at TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}'
            )""",
            """CREATE INDEX IF NOT EXISTS idx_twitch_channel_snapshots_time
               ON twitch_channel_snapshots(captured_at)""",
            """CREATE TABLE IF NOT EXISTS twitch_api_content(
                content_key TEXT PRIMARY KEY,
                platform_content_id TEXT NOT NULL,
                content_type TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT,
                duration_seconds REAL,
                views INTEGER NOT NULL DEFAULT 0,
                url TEXT,
                thumbnail_url TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                synced_at TEXT NOT NULL
            )""",
        ]
        for sql in statements:
            self.db.execute(sql)
        columns = set(
            self.db.frame("PRAGMA table_info('live_integration_settings')").get(
                "name", []
            )
        )
        additions = {
            "twitch_account_name": "TEXT",
            "twitch_connection_state": "TEXT DEFAULT 'not_configured'",
            "twitch_granted_scopes_json": "TEXT DEFAULT '[]'",
            "twitch_last_validated_at": "TEXT",
            "twitch_last_error": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                self.db.execute(
                    f"ALTER TABLE live_integration_settings ADD COLUMN {name} {declaration}"
                )

    def _migrate_credentials(self):
        self.db.execute("PRAGMA secure_delete=ON")
        frame=self.db.frame("SELECT twitch_access_token,twitch_refresh_token,obs_password FROM live_integration_settings WHERE id=1")
        if frame.empty:return
        row=frame.iloc[0]
        had_secrets=any(row.get(key) for key in ("twitch_access_token","twitch_refresh_token","obs_password"))
        self.vault.save("twitch",{"twitch_access_token":row.get("twitch_access_token"),"twitch_refresh_token":row.get("twitch_refresh_token")})
        self.vault.save("obs",{"obs_password":row.get("obs_password")})
        self.db.execute("UPDATE live_integration_settings SET twitch_access_token=NULL,twitch_refresh_token=NULL,obs_password=NULL WHERE id=1")
        if had_secrets:
            self.db.execute("VACUUM")
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def settings(self, reveal=True):
        frame = self.db.frame("SELECT * FROM live_integration_settings WHERE id=1")
        result=frame.iloc[0].to_dict()
        result=(self.vault.reveal("twitch",result) if reveal else self.vault.masked("twitch",result))
        return self.vault.reveal("obs",result) if reveal else self.vault.masked("obs",result)

    def display_settings(self):return self.settings(reveal=False)

    def update_settings(self, **kwargs):
        allowed = {
            "twitch_enabled","twitch_client_id","twitch_broadcaster_id",
            "twitch_access_token","twitch_refresh_token","twitch_token_expires_at",
            "obs_enabled","obs_host","obs_port","obs_password",
            "polling_interval_seconds","store_raw_chat","simulation_mode",
            "auto_start_session","viewer_spike_stddev","chat_spike_multiplier",
            "follow_spike_count","follow_spike_window_minutes",
            "raid_marker_min_viewers"
        }
        filtered = {k:v for k,v in kwargs.items() if k in allowed}
        twitch_secrets={k:filtered.pop(k) for k in list(filtered) if k in {"twitch_access_token","twitch_refresh_token"}}
        obs_secrets={k:filtered.pop(k) for k in list(filtered) if k=="obs_password"}
        self.vault.save("twitch",twitch_secrets);self.vault.save("obs",obs_secrets)
        if not filtered:
            return
        filtered["updated_at"] = datetime.now().isoformat()
        columns = list(filtered)
        sql = "UPDATE live_integration_settings SET " + ",".join(
            f"{column}=?" for column in columns
        ) + " WHERE id=1"
        self.db.execute(sql, [filtered[column] for column in columns])

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _scope_list(value: Any) -> tuple[str, ...]:
        if isinstance(value, (list, tuple, set)):
            return tuple(sorted({str(item) for item in value if item}))
        try:
            parsed = json.loads(str(value or "[]"))
        except (TypeError, ValueError):
            parsed = []
        return tuple(sorted({str(item) for item in parsed if item}))

    def _set_twitch_connection_metadata(self, **values) -> None:
        allowed = {
            "twitch_account_name",
            "twitch_connection_state",
            "twitch_granted_scopes_json",
            "twitch_last_validated_at",
            "twitch_last_error",
            "twitch_token_expires_at",
            "twitch_broadcaster_id",
            "twitch_client_id",
            "twitch_enabled",
        }
        filtered = {key: value for key, value in values.items() if key in allowed}
        if not filtered:
            return
        filtered["updated_at"] = datetime.now().isoformat()
        columns = list(filtered)
        self.db.execute(
            "UPDATE live_integration_settings SET "
            + ",".join(f"{column}=?" for column in columns)
            + " WHERE id=1",
            [filtered[column] for column in columns],
        )

    def twitch_connection_status(self) -> dict[str, Any]:
        settings = self.settings()
        client_id = str(settings.get("twitch_client_id") or "").strip()
        broadcaster_id = str(settings.get("twitch_broadcaster_id") or "").strip()
        access_token = str(settings.get("twitch_access_token") or "").strip()
        granted = self._scope_list(settings.get("twitch_granted_scopes_json"))
        stored_state = str(
            settings.get("twitch_connection_state") or ConnectionState.NOT_CONFIGURED
        )
        try:
            state = ConnectionState(stored_state)
        except ValueError:
            state = ConnectionState.ERROR

        if not client_id:
            state = ConnectionState.NOT_CONFIGURED
            message = "Add the Twitch Client ID to begin secure device sign-in."
        elif not broadcaster_id or not access_token:
            if state != ConnectionState.CONNECTING:
                state = ConnectionState.DISCONNECTED
            message = (
                "Waiting for Twitch approval in the browser."
                if state == ConnectionState.CONNECTING
                else "Twitch is disconnected. Connect or reconnect the account."
            )
        else:
            expiry = self._parse_datetime(settings.get("twitch_token_expires_at"))
            if expiry and expiry <= datetime.now():
                state = ConnectionState.EXPIRED
            if state in {ConnectionState.NOT_CONFIGURED, ConnectionState.DISCONNECTED}:
                state = ConnectionState.CONNECTED
            missing = [scope for scope in self.TWITCH_SCOPES if granted and scope not in granted]
            if missing and state == ConnectionState.CONNECTED:
                state = ConnectionState.LIMITED
            message = {
                ConnectionState.CONNECTED: "Connected securely and ready for Twitch tracking.",
                ConnectionState.LIMITED: "Connected with limited permissions. Reconnect to enable every feature.",
                ConnectionState.EXPIRED: "The Twitch access token expired. Refresh or reconnect the account.",
                ConnectionState.REVOKED: "Twitch access was revoked. Reconnect the account.",
                ConnectionState.ERROR: "The Twitch connection needs attention.",
                ConnectionState.CONNECTING: "Waiting for Twitch approval in the browser.",
            }.get(state, "Twitch connection status is unavailable.")

        return ConnectionStatus(
            provider="twitch",
            state=state,
            message=message,
            account_id=broadcaster_id or None,
            account_name=str(settings.get("twitch_account_name") or "") or None,
            granted_scopes=granted,
            required_scopes=self.TWITCH_SCOPES,
            expires_at=str(settings.get("twitch_token_expires_at") or "") or None,
            last_validated_at=str(settings.get("twitch_last_validated_at") or "") or None,
            last_error=str(settings.get("twitch_last_error") or "") or None,
        ).as_dict()

    def twitch_capabilities(self) -> list[dict[str, Any]]:
        status = self.twitch_connection_status()
        granted = set(status.get("granted_scopes") or [])
        capabilities = [
            {
                "capability": "Live status, viewers, VODs, and clips",
                "permission": "Standard signed-in Twitch access",
                "available": bool(status.get("can_sync")),
            }
        ]
        capabilities.extend(
            {
                "capability": label,
                "permission": scope,
                "available": scope in granted,
            }
            for scope, label in self.TWITCH_SCOPE_CAPABILITIES.items()
        )
        return capabilities

    def validate_twitch_connection(self) -> dict[str, Any]:
        settings = self.settings()
        token = str(settings.get("twitch_access_token") or "").strip()
        if not token:
            return self.twitch_connection_status()
        checked_at = datetime.now().isoformat()
        request = Request(
            "https://id.twitch.tv/oauth2/validate",
            headers={"Authorization": f"OAuth {token}"},
        )
        try:
            payload = self._json_request(request)
        except HTTPError:
            state = (
                ConnectionState.EXPIRED
                if (
                    self._parse_datetime(settings.get("twitch_token_expires_at"))
                    or datetime.max
                )
                <= datetime.now()
                else ConnectionState.REVOKED
            )
            self._set_twitch_connection_metadata(
                twitch_connection_state=state.value,
                twitch_last_validated_at=checked_at,
                twitch_last_error="Twitch rejected the saved access token.",
            )
            return self.twitch_connection_status()
        except Exception as exc:
            safe = self.vault.redact(exc)
            self._set_twitch_connection_metadata(
                twitch_connection_state=ConnectionState.ERROR.value,
                twitch_last_validated_at=checked_at,
                twitch_last_error=safe,
            )
            return self.twitch_connection_status()

        configured_client = str(settings.get("twitch_client_id") or "")
        configured_user = str(settings.get("twitch_broadcaster_id") or "")
        token_client = str(payload.get("client_id") or "")
        token_user = str(payload.get("user_id") or "")
        mismatch = None
        if configured_client and token_client != configured_client:
            mismatch = "The access token belongs to a different Twitch application."
        elif configured_user and token_user != configured_user:
            mismatch = "The access token belongs to a different Twitch account."
        scopes = self._scope_list(payload.get("scopes") or payload.get("scope"))
        missing = [scope for scope in self.TWITCH_SCOPES if scope not in scopes]
        state = (
            ConnectionState.ERROR
            if mismatch
            else ConnectionState.LIMITED
            if missing
            else ConnectionState.CONNECTED
        )
        expires_at = (
            datetime.now() + timedelta(seconds=int(payload.get("expires_in") or 0))
        ).isoformat()
        self._set_twitch_connection_metadata(
            twitch_enabled=1,
            twitch_broadcaster_id=token_user or configured_user,
            twitch_account_name=payload.get("login") or settings.get("twitch_account_name"),
            twitch_connection_state=state.value,
            twitch_granted_scopes_json=json.dumps(list(scopes)),
            twitch_token_expires_at=expires_at,
            twitch_last_validated_at=checked_at,
            twitch_last_error=mismatch,
        )
        return self.twitch_connection_status()

    def ensure_twitch_connection(self, *, force_validation: bool = False) -> dict[str, Any]:
        status = self.twitch_connection_status()
        refreshed = False
        if status["state"] == ConnectionState.EXPIRED.value and self.settings().get(
            "twitch_refresh_token"
        ):
            try:
                self.refresh_twitch_connection()
            except Exception:
                status = self.twitch_connection_status()
            else:
                refreshed = True
                force_validation = True
        last_checked = self._parse_datetime(status.get("last_validated_at"))
        validation_due = not last_checked or datetime.now() - last_checked >= self.TWITCH_VALIDATION_INTERVAL
        if status["configured"] and (force_validation or validation_due):
            status = self.validate_twitch_connection()
        if (
            status["state"] in {
                ConnectionState.EXPIRED.value,
                ConnectionState.REVOKED.value,
            }
            and not refreshed
            and self.settings().get("twitch_refresh_token")
        ):
            try:
                self.refresh_twitch_connection()
                status = self.validate_twitch_connection()
            except Exception:
                status = self.twitch_connection_status()
        if not status["can_sync"]:
            raise RuntimeError(status.get("last_error") or status["message"])
        return status

    def begin_twitch_connection(self, client_id: str) -> dict[str, Any]:
        client_id = str(client_id or "").strip()
        if not client_id:
            raise ValueError("Paste the Twitch Client ID first.")
        payload = self._post_form("https://id.twitch.tv/oauth2/device", {
            "client_id": client_id, "scopes": " ".join(self.TWITCH_SCOPES),
        })
        required = ("device_code", "user_code", "verification_uri")
        if any(not payload.get(key) for key in required):
            raise RuntimeError("Twitch did not return a complete device sign-in response.")
        payload["client_id"] = client_id
        payload["requested_at"] = datetime.now().isoformat()
        self._set_twitch_connection_metadata(
            twitch_client_id=client_id,
            twitch_connection_state=ConnectionState.CONNECTING.value,
            twitch_last_error=None,
        )
        return payload

    def poll_twitch_connection(self, connection: dict[str, Any]) -> dict[str, Any] | None:
        requested_at = self._parse_datetime(connection.get("requested_at"))
        if requested_at and datetime.now() >= requested_at + timedelta(
            seconds=int(connection.get("expires_in") or 1800)
        ):
            self._set_twitch_connection_metadata(
                twitch_connection_state=ConnectionState.ERROR.value,
                twitch_last_error="The Twitch device sign-in request expired.",
            )
            raise RuntimeError("Twitch sign-in expired. Start Connect Twitch again.")
        try:
            payload = self._post_form("https://id.twitch.tv/oauth2/token", {
                "client_id": connection.get("client_id"),
                "scopes": " ".join(self.TWITCH_SCOPES),
                "device_code": connection.get("device_code"),
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
        except HTTPError as exc:
            try:
                error = json.loads(exc.read().decode("utf-8"))
            except Exception:
                error = {}
            message = str(error.get("message") or error.get("error") or exc)
            if message.lower() == "slow_down":
                connection["interval"] = int(connection.get("interval") or 5) + 5
                return None
            if message.lower() == "authorization_pending":
                return None
            self._set_twitch_connection_metadata(
                twitch_connection_state=ConnectionState.ERROR.value,
                twitch_last_error=self.vault.redact(message),
            )
            raise RuntimeError(self.vault.redact(message)) from None
        access_token = payload.get("access_token") or ""
        if not access_token:
            return None
        identity = self._json_request(Request(
            "https://api.twitch.tv/helix/users",
            headers={
                "Client-Id": str(connection.get("client_id") or ""),
                "Authorization": f"Bearer {access_token}",
            },
        ))
        users = identity.get("data") or []
        if not users:
            raise RuntimeError("Twitch sign-in succeeded but no broadcaster account was returned.")
        user = users[0]
        scopes = self._scope_list(payload.get("scope") or self.TWITCH_SCOPES)
        missing = [scope for scope in self.TWITCH_SCOPES if scope not in scopes]
        self.vault.replace(
            "twitch",
            {
                "twitch_access_token": access_token,
                "twitch_refresh_token": payload.get("refresh_token") or "",
            },
        )
        self._set_twitch_connection_metadata(
            twitch_enabled=1,
            twitch_client_id=str(connection.get("client_id") or ""),
            twitch_broadcaster_id=str(user.get("id") or ""),
            twitch_account_name=str(user.get("display_name") or user.get("login") or ""),
            twitch_connection_state=(
                ConnectionState.LIMITED.value
                if missing
                else ConnectionState.CONNECTED.value
            ),
            twitch_granted_scopes_json=json.dumps(list(scopes)),
            twitch_token_expires_at=(
                datetime.now() + timedelta(seconds=int(payload.get("expires_in") or 0))
            ).isoformat(),
            twitch_last_validated_at=datetime.now().isoformat(),
            twitch_last_error=None,
        )
        return {
            "connected": True, "broadcaster_id": str(user.get("id") or ""),
            "account_name": str(user.get("display_name") or user.get("login") or ""),
            "status": self.twitch_connection_status(),
        }

    def refresh_twitch_connection(self) -> dict[str, Any]:
        with self._twitch_refresh_lock:
            settings = self.settings()
            if not settings.get("twitch_refresh_token"):
                raise ValueError("Reconnect Twitch to obtain a refresh token.")
            try:
                payload = self._post_form("https://id.twitch.tv/oauth2/token", {
                    "client_id": settings.get("twitch_client_id"),
                    "grant_type": "refresh_token",
                    "refresh_token": settings.get("twitch_refresh_token"),
                })
                access_token = str(payload.get("access_token") or "")
                refresh_token = str(payload.get("refresh_token") or "")
                if not access_token or not refresh_token:
                    raise RuntimeError("Twitch did not return a complete refreshed token pair.")
            except Exception as exc:
                safe = self.vault.redact(exc)
                self._set_twitch_connection_metadata(
                    twitch_connection_state=ConnectionState.EXPIRED.value,
                    twitch_last_error=f"Token refresh failed: {safe}",
                )
                raise RuntimeError(f"Reconnect Twitch. Token refresh failed: {safe}") from None
            self.vault.replace(
                "twitch",
                {
                    "twitch_access_token": access_token,
                    "twitch_refresh_token": refresh_token,
                },
            )
            scopes = self._scope_list(
                payload.get("scope")
                or settings.get("twitch_granted_scopes_json")
                or self.TWITCH_SCOPES
            )
            self._set_twitch_connection_metadata(
                twitch_connection_state=ConnectionState.CONNECTED.value,
                twitch_granted_scopes_json=json.dumps(list(scopes)),
                twitch_token_expires_at=(
                    datetime.now() + timedelta(seconds=int(payload.get("expires_in") or 0))
                ).isoformat(),
                twitch_last_validated_at=None,
                twitch_last_error=None,
            )
            return {"refreshed": True, "expires_in": payload.get("expires_in")}

    def revoke_twitch_access(self) -> None:
        settings = self.settings()
        token = settings.get("twitch_access_token")
        client_id = settings.get("twitch_client_id")
        if token and client_id:
            self._post_form("https://id.twitch.tv/oauth2/revoke", {
                "client_id": client_id, "token": token,
            })

    def disconnect_integration(self,provider):
        provider=str(provider).lower()
        if provider not in {"twitch","obs"}:raise ValueError(provider)
        self.vault.delete(provider)
        if provider == "twitch":
            self.db.execute(
                """UPDATE live_integration_settings SET twitch_enabled=0,
                   twitch_broadcaster_id=NULL,twitch_account_name=NULL,
                   twitch_connection_state=?,twitch_granted_scopes_json='[]',
                   twitch_token_expires_at=NULL,twitch_last_validated_at=NULL,
                   twitch_last_error=NULL,updated_at=? WHERE id=1""",
                (ConnectionState.DISCONNECTED.value, datetime.now().isoformat()),
            )
        else:
            self.db.execute(
                "UPDATE live_integration_settings SET obs_enabled=0,updated_at=? WHERE id=1",
                (datetime.now().isoformat(),),
            )

    @staticmethod
    def _json_request(request: Request) -> dict[str, Any]:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}

    @classmethod
    def _post_form(cls, url: str, values: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            url,
            data=urlencode({key: value for key, value in values.items() if value is not None}).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return cls._json_request(request)

    def _twitch_request(
        self, path: str, query: dict[str, Any] | None = None, *,
        method: str = "GET", payload: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        self.ensure_twitch_connection()
        settings = self.settings()
        client_id = str(settings.get("twitch_client_id") or "").strip()
        access_token = str(settings.get("twitch_access_token") or "").strip()
        broadcaster_id = str(settings.get("twitch_broadcaster_id") or "").strip()
        if not client_id or not access_token or not broadcaster_id:
            raise ValueError("Connect Twitch before syncing live data.")
        url = f"https://api.twitch.tv/helix/{path.lstrip('/')}"
        if query:
            url += "?" + urlencode({key: value for key, value in query.items() if value is not None})
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url, data=body, method=method,
            headers={
                "Client-Id": client_id,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            return self._json_request(request)
        except HTTPError as exc:
            if exc.code == 401 and retry and settings.get("twitch_refresh_token"):
                try:
                    self.refresh_twitch_connection()
                except Exception:
                    raise RuntimeError(self.twitch_connection_status()["message"]) from None
                return self._twitch_request(
                    path, query, method=method, payload=payload, retry=False
                )
            if exc.code == 401:
                self._set_twitch_connection_metadata(
                    twitch_connection_state=ConnectionState.REVOKED.value,
                    twitch_last_error="Twitch rejected the saved access token.",
                )
            try:
                response = json.loads(exc.read().decode("utf-8"))
                message = response.get("message") or str(exc)
            except Exception:
                message = str(exc)
            if exc.code == 429:
                message = "Twitch rate limit reached. Wait before syncing again."
            raise RuntimeError(self.vault.redact(message)) from None

    def twitch_channel_status(self, *, store: bool = True) -> dict[str, Any]:
        settings = self.settings()
        broadcaster_id = str(settings.get("twitch_broadcaster_id") or "").strip()
        streams = self._twitch_request("streams", {"user_id": broadcaster_id}).get("data") or []
        channels = self._twitch_request("channels", {"broadcaster_id": broadcaster_id}).get("data") or []
        stream = streams[0] if streams else {}
        channel = channels[0] if channels else {}
        try:
            followers = self._twitch_request(
                "channels/followers", {"broadcaster_id": broadcaster_id, "first": 1}
            ).get("total")
        except RuntimeError:
            followers = None
        try:
            subscribers = self._twitch_request(
                "subscriptions", {"broadcaster_id": broadcaster_id, "first": 1}
            ).get("total")
        except RuntimeError:
            subscribers = None
        now = datetime.now().isoformat()
        status = {
            "captured_at": now,
            "broadcaster_id": broadcaster_id,
            "is_live": bool(stream),
            "stream_id": stream.get("id"),
            "title": stream.get("title") or channel.get("title"),
            "game": stream.get("game_name") or channel.get("game_name"),
            "viewers": int(stream.get("viewer_count") or 0),
            "followers_total": self._optional_int(followers),
            "subscribers_total": self._optional_int(subscribers),
            "started_at": stream.get("started_at"),
        }
        if store:
            self.db.execute(
                """INSERT INTO twitch_channel_snapshots(
                    captured_at,broadcaster_id,is_live,stream_id,title,game,viewers,
                    followers_total,subscribers_total,started_at,payload_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    now, broadcaster_id, int(status["is_live"]), status["stream_id"],
                    status["title"], status["game"], status["viewers"],
                    status["followers_total"], status["subscribers_total"],
                    status["started_at"], json.dumps({"stream": stream, "channel": channel}),
                ),
            )
        return status

    def poll_twitch_live(self) -> dict[str, Any]:
        status = self.twitch_channel_status(store=True)
        active = self.active_session()
        if not status["is_live"]:
            if active and active.get("source_mode") == "twitch":
                self.end_session(active["id"])
                status["session_ended"] = True
            return status
        if active and active.get("source_mode") != "twitch":
            raise RuntimeError("End the simulation session before starting real Twitch tracking.")
        if not active:
            if not bool(self.settings().get("auto_start_session")):
                return status
            active = self.start_session(
                title=status["title"], game=status["game"],
                starting_followers=status["followers_total"],
                starting_subscribers=status["subscribers_total"],
                source_mode="twitch", twitch_stream_id=status["stream_id"],
            )
            status["session_started"] = True
        elif status["title"] or status["game"]:
            self.db.execute(
                """UPDATE live_sessions SET title=COALESCE(?,title),game=COALESCE(?,game),
                   twitch_stream_id=COALESCE(?,twitch_stream_id),updated_at=? WHERE id=?""",
                (status["title"], status["game"], status["stream_id"], datetime.now().isoformat(), active["id"]),
            )
        chat = self.chat_activity()
        self.record_snapshot(
            LiveSnapshot(
                captured_at=status["captured_at"], viewers=status["viewers"],
                followers_total=status["followers_total"],
                subscribers_total=status["subscribers_total"],
                chat_messages_minute=chat["messages_minute"],
                unique_chatters_5m=chat["unique_chatters_5m"],
                current_game=status["game"], current_title=status["title"],
            ),
            active["id"],
        )
        status["session_id"] = active["id"]
        return status

    def sync_twitch_content(self) -> dict[str, Any]:
        settings = self.settings()
        broadcaster_id = str(settings.get("twitch_broadcaster_id") or "")
        status = self.twitch_channel_status(store=True)
        videos = self._twitch_request(
            "videos", {"user_id": broadcaster_id, "first": 100, "type": "archive"}
        ).get("data") or []
        clips = self._twitch_request(
            "clips", {"broadcaster_id": broadcaster_id, "first": 100}
        ).get("data") or []
        now = datetime.now().isoformat()
        for content_type, records in (("video", videos), ("clip", clips)):
            for record in records:
                content_id = str(record.get("id") or "").strip()
                if not content_id:
                    continue
                duration = (
                    self._twitch_duration_seconds(record.get("duration"))
                    if content_type == "video" else float(record.get("duration") or 0)
                )
                self.db.execute(
                    """INSERT INTO twitch_api_content(
                        content_key,platform_content_id,content_type,title,created_at,
                        duration_seconds,views,url,thumbnail_url,payload_json,synced_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(content_key) DO UPDATE SET
                        title=excluded.title,created_at=excluded.created_at,
                        duration_seconds=excluded.duration_seconds,views=excluded.views,
                        url=excluded.url,thumbnail_url=excluded.thumbnail_url,
                        payload_json=excluded.payload_json,synced_at=excluded.synced_at""",
                    (
                        f"{content_type}:{content_id}", content_id, content_type,
                        str(record.get("title") or "Untitled"),
                        record.get("created_at") or record.get("published_at"), duration,
                        int(record.get("view_count") or 0), record.get("url"),
                        record.get("thumbnail_url"), json.dumps(record), now,
                    ),
                )
        return {"status": status, "videos": len(videos), "clips": len(clips)}

    def twitch_api_content(self):
        return self.db.frame(
            """SELECT content_type,title,created_at,duration_seconds,views,url,synced_at
               FROM twitch_api_content ORDER BY COALESCE(created_at,synced_at) DESC"""
        )

    def latest_twitch_status(self):
        frame = self.db.frame(
            "SELECT * FROM twitch_channel_snapshots ORDER BY id DESC LIMIT 1"
        )
        return frame.iloc[0].to_dict() if not frame.empty else None

    def record_chat_message(self, event: dict[str, Any], message_id: str | None = None):
        message = event.get("message") or {}
        text = str(message.get("text") or "").strip()
        if not text:
            return None
        active = self.active_session()
        external_id = str(message_id or event.get("message_id") or uuid.uuid4())
        captured_at = datetime.now().isoformat()
        chatter_name = str(
            event.get("chatter_user_name")
            or event.get("chatter_user_login")
            or "Unknown"
        )
        chatter_identifier = str(
            event.get("chatter_user_id") or event.get("chatter_user_login") or ""
        )
        chatter_hash = (
            hashlib.sha256(chatter_identifier.encode("utf-8")).hexdigest()
            if chatter_identifier
            else None
        )
        self.db.execute(
            """INSERT OR IGNORE INTO live_chat_activity_events(
                session_id,message_id,captured_at,chatter_hash) VALUES(?,?,?,?)""",
            (
                active.get("id") if active else None,
                external_id,
                captured_at,
                chatter_hash,
            ),
        )
        result = {
            "captured_at": captured_at,
            "chatter_user_name": chatter_name,
            "message_text": text,
            "retained": False,
        }
        if not bool(self.settings().get("store_raw_chat")):
            return result
        self.db.execute(
            """INSERT OR IGNORE INTO live_chat_messages(
                session_id,message_id,captured_at,chatter_user_id,chatter_user_name,
                message_text,color,badges_json,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                active.get("id") if active else None, external_id, captured_at,
                event.get("chatter_user_id"),
                chatter_name,
                text, event.get("color"), json.dumps(event.get("badges") or []),
                json.dumps(event, default=str),
            ),
        )
        frame = self.db.frame(
            "SELECT * FROM live_chat_messages WHERE message_id=?", (external_id,)
        )
        if frame.empty:
            return result
        stored = frame.iloc[0].to_dict()
        stored["retained"] = True
        return stored

    def chat_messages(self, session_id=None, limit: int = 500):
        if session_id is None:
            return self.db.frame(
                """SELECT captured_at,chatter_user_name,message_text
                   FROM live_chat_messages ORDER BY id DESC LIMIT ?""", (int(limit),)
            ).iloc[::-1].reset_index(drop=True)
        return self.db.frame(
            """SELECT captured_at,chatter_user_name,message_text
               FROM live_chat_messages WHERE session_id=? ORDER BY id DESC LIMIT ?""",
            (int(session_id), int(limit)),
        ).iloc[::-1].reset_index(drop=True)

    def chat_activity(self) -> dict[str, int]:
        one_minute = (datetime.now() - timedelta(minutes=1)).isoformat()
        five_minutes = (datetime.now() - timedelta(minutes=5)).isoformat()
        messages = int(self.db.scalar(
            "SELECT COUNT(*) FROM live_chat_activity_events WHERE captured_at>=?",
            (one_minute,), 0
        ))
        chatters = int(self.db.scalar(
            """SELECT COUNT(DISTINCT chatter_hash) FROM live_chat_activity_events
               WHERE captured_at>=?""", (five_minutes,), 0
        ))
        return {"messages_minute": messages, "unique_chatters_5m": chatters}

    def subscribe_twitch_eventsub(self, websocket_session_id: str) -> dict[str, Any]:
        self.ensure_twitch_connection()
        settings = self.settings()
        broadcaster_id = str(settings.get("twitch_broadcaster_id") or "")
        granted = set(self._scope_list(settings.get("twitch_granted_scopes_json")))
        subscriptions = [
            ("stream.online", "1", {"broadcaster_user_id": broadcaster_id}, None),
            ("stream.offline", "1", {"broadcaster_user_id": broadcaster_id}, None),
            ("channel.update", "2", {"broadcaster_user_id": broadcaster_id}, None),
            ("channel.follow", "2", {
                "broadcaster_user_id": broadcaster_id, "moderator_user_id": broadcaster_id,
            }, "moderator:read:followers"),
            ("channel.raid", "1", {"to_broadcaster_user_id": broadcaster_id}, None),
            ("channel.subscribe", "1", {
                "broadcaster_user_id": broadcaster_id,
            }, "channel:read:subscriptions"),
            ("channel.chat.message", "1", {
                "broadcaster_user_id": broadcaster_id, "user_id": broadcaster_id,
            }, "user:read:chat"),
        ]
        subscribed, errors = [], []
        for event_type, version, condition, required_scope in subscriptions:
            if required_scope and required_scope not in granted:
                errors.append({
                    "type": event_type,
                    "error": f"Missing permission: {required_scope}",
                })
                continue
            try:
                self._twitch_request(
                    "eventsub/subscriptions", method="POST",
                    payload={
                        "type": event_type, "version": version, "condition": condition,
                        "transport": {"method": "websocket", "session_id": websocket_session_id},
                    },
                )
                subscribed.append(event_type)
            except Exception as exc:
                errors.append({"type": event_type, "error": self.vault.redact(exc)})
        return {"subscribed": subscribed, "errors": errors}

    @staticmethod
    def _optional_int(value):
        return int(value) if value is not None else None

    @staticmethod
    def _twitch_duration_seconds(value: Any) -> float:
        text = str(value or "")
        match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
        if not match:
            return 0.0
        hours, minutes, seconds = (int(part or 0) for part in match.groups())
        return float(hours * 3600 + minutes * 60 + seconds)

    def active_session(self):
        frame = self.db.frame(
            """SELECT * FROM live_sessions
               WHERE status='Live' ORDER BY id DESC LIMIT 1"""
        )
        return frame.iloc[0].to_dict() if not frame.empty else None

    def start_session(
        self, title=None, game=None, predicted_average_viewers=None,
        predicted_peak_viewers=None, starting_followers=None,
        starting_subscribers=None, starting_revenue=0.0,
        source_mode="simulation", twitch_stream_id=None
    ):
        existing = self.active_session()
        if existing:
            return existing
        now = datetime.now().isoformat()
        session_key = str(uuid.uuid4())
        self.db.execute(
            """INSERT INTO live_sessions(
                session_key,started_at,status,title,game,twitch_stream_id,
                starting_followers,starting_subscribers,starting_revenue,
                predicted_average_viewers,predicted_peak_viewers,
                source_mode,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_key,now,"Live",title,game,twitch_stream_id,
                starting_followers,starting_subscribers,starting_revenue,
                predicted_average_viewers,predicted_peak_viewers,
                source_mode,now,now
            )
        )
        session = self.active_session()
        self.add_event(
            session["id"],"stream_started","Stream started",
            f"Live session started in {source_mode} mode.","System"
        )
        if self.notifications:
            self.notifications.create(
                "System","Success","Live tracking started",
                f'Live session "{title or "Untitled stream"}" is now being tracked.',
                "live_session",session["id"]
            )
        return session

    def end_session(self, session_id=None):
        session = self._get_session(session_id)
        snapshots = self.snapshots(session["id"])
        now = datetime.now().isoformat()
        actual_average = float(snapshots["viewers"].mean()) if not snapshots.empty else 0
        actual_peak = int(snapshots["viewers"].max()) if not snapshots.empty else 0
        latest = snapshots.iloc[-1].to_dict() if not snapshots.empty else {}
        score = self.performance_score(session["id"])
        self.db.execute(
            """UPDATE live_sessions SET ended_at=?,status='Complete',
               ending_followers=?,ending_subscribers=?,ending_revenue=?,
               actual_average_viewers=?,actual_peak_viewers=?,
               performance_score=?,updated_at=? WHERE id=?""",
            (
                now,latest.get("followers_total"),latest.get("subscribers_total"),
                latest.get("revenue_total"),actual_average,actual_peak,
                score,now,session["id"]
            )
        )
        self.add_event(
            session["id"],"stream_ended","Stream ended",
            f"Final average viewers: {actual_average:.1f}; peak: {actual_peak}.",
            "System"
        )
        if self.notifications:
            self.notifications.create(
                "System","Success","Live session completed",
                f"Average viewers: {actual_average:.1f}; peak viewers: {actual_peak}; performance score: {score:.0f}.",
                "live_session",session["id"]
            )
        return self._get_session(session["id"])

    def _get_session(self, session_id=None):
        if session_id is None:
            session = self.active_session()
            if not session:
                raise ValueError("No active live session.")
            return session
        frame = self.db.frame("SELECT * FROM live_sessions WHERE id=?", (int(session_id),))
        if frame.empty:
            raise KeyError(session_id)
        return frame.iloc[0].to_dict()

    def elapsed_seconds(self, session, at=None):
        started = datetime.fromisoformat(session["started_at"])
        current = at or datetime.now()
        return max(0, int((current - started).total_seconds()))

    def add_event(
        self, session_id, event_type, title, description=None,
        source="Manual", external_id=None, payload=None,
        occurred_at=None, severity="Info"
    ):
        session = self._get_session(session_id)
        occurred = occurred_at or datetime.now()
        if isinstance(occurred, str):
            occurred_dt = datetime.fromisoformat(occurred)
            occurred_text = occurred
        else:
            occurred_dt = occurred
            occurred_text = occurred.isoformat()
        elapsed = self.elapsed_seconds(session, occurred_dt)
        self.db.execute(
            """INSERT OR IGNORE INTO live_events(
                session_id,occurred_at,elapsed_seconds,event_type,severity,
                title,description,source,external_id,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                session["id"],occurred_text,elapsed,event_type,severity,
                title,description,source,external_id,
                json.dumps(payload or {},default=str)
            )
        )
        frame = self.db.frame(
            """SELECT * FROM live_events WHERE session_id=?
               ORDER BY id DESC LIMIT 1""",(session["id"],)
        )
        return frame.iloc[0].to_dict() if not frame.empty else None

    def add_raid(self, viewers, source_channel, external_id=None):
        session = self._get_session()
        event = self.add_event(
            session["id"],"raid","Raid received",
            f"{source_channel} raided with {int(viewers)} viewers.",
            "Twitch",external_id,
            {"viewer_count":int(viewers),"source_channel":source_channel},
            severity="Success"
        )
        settings = self.settings()
        if int(viewers) >= int(settings["raid_marker_min_viewers"] or 10):
            strength = min(100, 55 + math.log10(max(viewers,1))*20)
            self.create_marker(
                session["id"],"Raid",
                f"Raid from {source_channel}",
                strength_score=strength,confidence=0.99,
                suggested_content_type="Highlight or Short",
                supporting_metrics={"raid_viewers":int(viewers)},
                source_event_id=event["id"] if event else None
            )
        return event

    def add_follow(self, user_name=None, external_id=None):
        session = self._get_session()
        event = self.add_event(
            session["id"],"follow","New follower",
            f"{user_name or 'A viewer'} followed the channel.",
            "Twitch",external_id,{"user_name":user_name}
        )
        self._detect_follow_spike(session["id"])
        return event

    def add_game_change(self, game, title=None):
        session = self._get_session()
        old_game = session.get("game")
        self.db.execute(
            """UPDATE live_sessions SET game=?,title=COALESCE(?,title),
               updated_at=? WHERE id=?""",
            (game,title,datetime.now().isoformat(),session["id"])
        )
        event = self.add_event(
            session["id"],"game_change","Game changed",
            f"{old_game or 'Unknown'} → {game}.","Twitch",
            payload={"old_game":old_game,"new_game":game,"title":title}
        )
        self.create_marker(
            session["id"],"Game change",f"Started playing {game}",
            strength_score=35,confidence=1.0,
            suggested_content_type="Chapter boundary",
            supporting_metrics={"old_game":old_game,"new_game":game},
            source_event_id=event["id"] if event else None
        )
        return event

    def add_scene_change(self, scene):
        session = self._get_session()
        return self.add_event(
            session["id"],"scene_change","OBS scene changed",
            f"Program scene changed to {scene}.","OBS",
            payload={"scene":scene}
        )

    def add_manual_marker(self, label="Manual moment", notes=None):
        session = self._get_session()
        event = self.add_event(
            session["id"],"manual_marker",label,notes or "Manual stream marker.",
            "Manual"
        )
        return self.create_marker(
            session["id"],"Manual",label,
            strength_score=70,confidence=1.0,
            suggested_content_type="Review manually",
            supporting_metrics={},
            source_event_id=event["id"] if event else None,
            notes=notes
        )

    def create_marker(
        self, session_id, marker_type, label, strength_score=0,
        confidence=0, suggested_content_type=None,
        supporting_metrics=None, source_event_id=None, notes=None,
        occurred_at=None
    ):
        session = self._get_session(session_id)
        occurred = occurred_at or datetime.now()
        occurred_dt = datetime.fromisoformat(occurred) if isinstance(occurred,str) else occurred
        elapsed = self.elapsed_seconds(session,occurred_dt)
        now = datetime.now().isoformat()
        marker_id = int(self.db.execute(
            """INSERT INTO stream_markers(
                session_id,occurred_at,elapsed_seconds,marker_type,label,
                strength_score,confidence,suggested_content_type,
                supporting_metrics_json,source_event_id,notes,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session["id"],occurred_dt.isoformat(),elapsed,marker_type,label,
                float(strength_score),float(confidence),suggested_content_type,
                json.dumps(supporting_metrics or {},default=str),
                source_event_id,notes,now
            )
        ))
        if self.notifications and float(strength_score) >= 80:
            self.notifications.create(
                "System","Success","Strong highlight marker created",
                f"{label} scored {float(strength_score):.0f}/100.",
                "stream_marker",marker_id
            )
        return self.db.frame(
            "SELECT * FROM stream_markers ORDER BY id DESC LIMIT 1"
        ).iloc[0].to_dict()

    def record_snapshot(self, snapshot: LiveSnapshot | dict[str,Any], session_id=None):
        session = self._get_session(session_id)
        if isinstance(snapshot, dict):
            snapshot = LiveSnapshot(**snapshot)
        captured = datetime.fromisoformat(snapshot.captured_at)
        elapsed = self.elapsed_seconds(session,captured)
        prior = self.snapshots(session["id"])
        viewers = int(snapshot.viewers or 0)

        session_average = (
            (prior["viewers"].sum() + viewers) / (len(prior)+1)
            if not prior.empty else float(viewers)
        )
        rolling = self._rolling_average(prior, captured, minutes=5, include=viewers)
        velocity_1m = self._velocity(prior,captured,viewers,minutes=1)
        velocity_5m = self._velocity(prior,captured,viewers,minutes=5)
        projected_average = self._project_average(
            session_average,velocity_5m,elapsed,
            session.get("predicted_average_viewers")
        )
        projected_peak = max(
            viewers,
            float(prior["viewers"].max()) if not prior.empty else viewers,
            projected_average + max(0,velocity_5m)*2
        )
        start_followers = session.get("starting_followers")
        follows_gained = (
            max(0,int(snapshot.followers_total)-int(start_followers))
            if snapshot.followers_total is not None and start_followers is not None
            else 0
        )
        start_subs = session.get("starting_subscribers")
        subs_gained = (
            max(0,int(snapshot.subscribers_total)-int(start_subs))
            if snapshot.subscribers_total is not None and start_subs is not None
            else 0
        )
        revenue_total = float(snapshot.revenue_total or 0)
        revenue_per_hour = (
            revenue_total / max(elapsed/3600, 1/60)
            if elapsed > 0 else 0
        )
        retention = self._retention_estimate(session_average,projected_average,velocity_5m)

        payload = {
            "viewers": viewers,
            "followers_total": snapshot.followers_total,
            "subscribers_total": snapshot.subscribers_total,
            "revenue_total": snapshot.revenue_total,
            "chat_messages_minute": snapshot.chat_messages_minute,
            "unique_chatters_5m": snapshot.unique_chatters_5m,
            "current_game": snapshot.current_game,
            "current_title": snapshot.current_title,
            "obs_scene": snapshot.obs_scene,
            "recording_active": snapshot.recording_active,
        }
        self.db.execute(
            """INSERT OR REPLACE INTO live_metric_snapshots(
                session_id,captured_at,elapsed_seconds,viewers,
                rolling_average_5m,session_average,projected_average,
                projected_peak,viewer_velocity_1m,viewer_velocity_5m,
                followers_total,followers_gained,subscribers_total,
                subscribers_gained,revenue_total,revenue_per_hour,
                chat_messages_minute,unique_chatters_5m,retention_estimate,
                current_game,current_title,obs_scene,recording_active,
                source_payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session["id"],snapshot.captured_at,elapsed,viewers,
                rolling,session_average,projected_average,projected_peak,
                velocity_1m,velocity_5m,snapshot.followers_total,follows_gained,
                snapshot.subscribers_total,subs_gained,revenue_total,
                revenue_per_hour,int(snapshot.chat_messages_minute or 0),
                int(snapshot.unique_chatters_5m or 0),retention,
                snapshot.current_game,snapshot.current_title,snapshot.obs_scene,
                int(bool(snapshot.recording_active)),
                json.dumps(payload,default=str)
            )
        )
        self.db.execute(
            """UPDATE live_sessions SET projected_average_viewers=?,
               projected_peak_viewers=?,updated_at=? WHERE id=?""",
            (
                projected_average,projected_peak,
                datetime.now().isoformat(),session["id"]
            )
        )
        self._detect_snapshot_markers(session["id"])
        return self.latest_snapshot(session["id"])

    def _rolling_average(self, prior, captured, minutes, include):
        if prior.empty:
            return float(include)
        threshold = captured - timedelta(minutes=minutes)
        frame = prior.copy()
        frame["captured_dt"] = frame["captured_at"].apply(datetime.fromisoformat)
        values = frame.loc[frame["captured_dt"]>=threshold,"viewers"].tolist()
        values.append(include)
        return sum(values)/len(values)

    def _velocity(self, prior, captured, current, minutes):
        if prior.empty:
            return 0.0
        target = captured - timedelta(minutes=minutes)
        frame = prior.copy()
        frame["captured_dt"] = frame["captured_at"].apply(datetime.fromisoformat)
        eligible = frame[frame["captured_dt"]<=target]
        reference = eligible.iloc[-1] if not eligible.empty else frame.iloc[0]
        delta_minutes = max(
            (captured-reference["captured_dt"]).total_seconds()/60, 1/60
        )
        return (current-float(reference["viewers"]))/delta_minutes

    def _project_average(self,current_average,velocity_5m,elapsed,predicted):
        stabilization = min(1.0,max(0.15,elapsed/7200))
        live_projection = max(0,current_average + velocity_5m*2.5)
        if predicted is None:
            return live_projection
        return float(predicted)*(1-stabilization) + live_projection*stabilization

    def _retention_estimate(self,current_average,projected_average,velocity):
        if current_average <= 0:
            return 0
        momentum = max(-0.25,min(0.25,velocity/max(current_average,1)))
        estimate = (projected_average/max(current_average,1))*0.75 + 0.25 + momentum
        return max(0,min(1.5,estimate))

    def _detect_snapshot_markers(self, session_id):
        frame = self.snapshots(session_id)
        if len(frame) < 4:
            return
        latest = frame.iloc[-1]
        history = frame.iloc[:-1]
        settings = self.settings()

        mean = float(history["viewers"].mean())
        std = float(history["viewers"].std(ddof=0) or 0)
        threshold = mean + float(settings["viewer_spike_stddev"] or 2.0)*std
        if std > 0 and float(latest["viewers"]) >= threshold:
            recent = self.db.frame(
                """SELECT COUNT(*) AS count FROM stream_markers
                   WHERE session_id=? AND marker_type='Viewer spike'
                   AND elapsed_seconds>=?""",
                (session_id,max(0,int(latest["elapsed_seconds"])-300))
            )
            if int(recent.iloc[0]["count"]) == 0:
                strength = min(
                    100,60 + ((float(latest["viewers"])-mean)/max(std,1))*10
                )
                self.create_marker(
                    session_id,"Viewer spike","Viewer spike detected",
                    strength_score=strength,confidence=0.9,
                    suggested_content_type="Short or highlight",
                    supporting_metrics={
                        "current_viewers":int(latest["viewers"]),
                        "historical_mean":round(mean,2),
                        "standard_deviation":round(std,2),
                        "threshold":round(threshold,2)
                    },
                    occurred_at=latest["captured_at"]
                )

        chat_history = history["chat_messages_minute"]
        baseline = float(chat_history.tail(15).mean()) if not chat_history.empty else 0
        multiplier = float(settings["chat_spike_multiplier"] or 2.5)
        current_chat = float(latest["chat_messages_minute"] or 0)
        if baseline >= 1 and current_chat >= baseline*multiplier:
            recent = self.db.frame(
                """SELECT COUNT(*) AS count FROM stream_markers
                   WHERE session_id=? AND marker_type='Chat spike'
                   AND elapsed_seconds>=?""",
                (session_id,max(0,int(latest["elapsed_seconds"])-300))
            )
            if int(recent.iloc[0]["count"]) == 0:
                strength = min(100,55+(current_chat/baseline)*12)
                self.create_marker(
                    session_id,"Chat spike","Chat activity spike",
                    strength_score=strength,confidence=0.88,
                    suggested_content_type="Short, clip, or highlight",
                    supporting_metrics={
                        "messages_per_minute":int(current_chat),
                        "baseline":round(baseline,2),
                        "multiplier":round(current_chat/baseline,2)
                    },
                    occurred_at=latest["captured_at"]
                )

        previous_peak = int(history["viewers"].max())
        if int(latest["viewers"]) > previous_peak:
            self.add_event(
                session_id,"new_peak","New viewer peak",
                f'Viewer count reached {int(latest["viewers"])}.',
                "Analytics",
                external_id=f'peak:{int(latest["viewers"])}',
                occurred_at=latest["captured_at"],
                severity="Success"
            )

    def _detect_follow_spike(self, session_id):
        settings = self.settings()
        window = int(settings["follow_spike_window_minutes"] or 5)
        threshold = int(settings["follow_spike_count"] or 3)
        session = self._get_session(session_id)
        elapsed = self.elapsed_seconds(session)
        frame = self.db.frame(
            """SELECT COUNT(*) AS count FROM live_events
               WHERE session_id=? AND event_type='follow'
               AND elapsed_seconds>=?""",
            (session_id,max(0,elapsed-window*60))
        )
        count = int(frame.iloc[0]["count"])
        if count >= threshold:
            recent = self.db.frame(
                """SELECT COUNT(*) AS count FROM stream_markers
                   WHERE session_id=? AND marker_type='Follow spike'
                   AND elapsed_seconds>=?""",
                (session_id,max(0,elapsed-window*60))
            )
            if int(recent.iloc[0]["count"]) == 0:
                self.create_marker(
                    session_id,"Follow spike","Follower spike detected",
                    strength_score=min(100,60+count*8),confidence=0.95,
                    suggested_content_type="Review surrounding moment",
                    supporting_metrics={
                        "follows":count,
                        "window_minutes":window
                    }
                )

    def snapshots(self, session_id):
        return self.db.frame(
            """SELECT * FROM live_metric_snapshots
               WHERE session_id=? ORDER BY captured_at""",(int(session_id),)
        )

    def latest_snapshot(self, session_id=None):
        session = self._get_session(session_id)
        frame = self.db.frame(
            """SELECT * FROM live_metric_snapshots
               WHERE session_id=? ORDER BY captured_at DESC LIMIT 1""",
            (session["id"],)
        )
        return frame.iloc[0].to_dict() if not frame.empty else None

    def events(self, session_id=None):
        session = self._get_session(session_id)
        return self.db.frame(
            """SELECT * FROM live_events
               WHERE session_id=? ORDER BY occurred_at""",(session["id"],)
        )

    def markers(self, session_id=None):
        session = self._get_session(session_id)
        return self.db.frame(
            """SELECT * FROM stream_markers
               WHERE session_id=? ORDER BY occurred_at""",(session["id"],)
        )

    def timeline(self, session_id=None):
        session = self._get_session(session_id)
        events = self.db.frame(
            """SELECT occurred_at,elapsed_seconds,'Event' AS item_kind,
               event_type AS item_type,title,description,
               NULL AS strength_score,NULL AS confidence
               FROM live_events WHERE session_id=?""",(session["id"],)
        )
        markers = self.db.frame(
            """SELECT occurred_at,elapsed_seconds,'Marker' AS item_kind,
               marker_type AS item_type,label AS title,notes AS description,
               strength_score,confidence
               FROM stream_markers WHERE session_id=?""",(session["id"],)
        )
        if events.empty:
            combined = markers
        elif markers.empty:
            combined = events
        else:
            import pandas as pd
            combined = pd.concat([events,markers],ignore_index=True)
        if not combined.empty:
            combined = combined.sort_values(["occurred_at","item_kind"])
        return combined

    def dashboard(self, session_id=None):
        session = self._get_session(session_id)
        latest = self.latest_snapshot(session["id"])
        snapshots = self.snapshots(session["id"])
        if not latest:
            return {
                "session":session,"current_viewers":0,"average_viewers":0,
                "peak_viewers":0,"viewer_velocity_5m":0,
                "followers_gained":0,"subscribers_gained":0,
                "revenue_total":0,"revenue_per_hour":0,
                "chat_messages_minute":0,"retention_estimate":0,
                "projected_average":session.get("predicted_average_viewers") or 0,
                "projected_peak":session.get("predicted_peak_viewers") or 0,
                "performance_score":0
            }
        return {
            "session":session,
            "current_viewers":int(latest["viewers"]),
            "average_viewers":float(latest["session_average"] or 0),
            "peak_viewers":int(snapshots["viewers"].max()),
            "viewer_velocity_1m":float(latest["viewer_velocity_1m"] or 0),
            "viewer_velocity_5m":float(latest["viewer_velocity_5m"] or 0),
            "followers_gained":int(latest["followers_gained"] or 0),
            "subscribers_gained":int(latest["subscribers_gained"] or 0),
            "revenue_total":float(latest["revenue_total"] or 0),
            "revenue_per_hour":float(latest["revenue_per_hour"] or 0),
            "chat_messages_minute":int(latest["chat_messages_minute"] or 0),
            "retention_estimate":float(latest["retention_estimate"] or 0),
            "projected_average":float(latest["projected_average"] or 0),
            "projected_peak":float(latest["projected_peak"] or 0),
            "performance_score":self.performance_score(session["id"]),
        }

    def performance_score(self, session_id=None):
        session = self._get_session(session_id)
        latest = self.latest_snapshot(session["id"])
        if not latest:
            return 0.0
        predicted = float(session.get("predicted_average_viewers") or latest["session_average"] or 1)
        viewer_score = min(130,float(latest["projected_average"] or 0)/max(predicted,1)*100)
        retention_score = min(130,float(latest["retention_estimate"] or 0)*100)
        chat_score = min(130,float(latest["chat_messages_minute"] or 0)/20*100)
        follower_score = min(130,float(latest["followers_gained"] or 0)/5*100)
        revenue_score = min(130,float(latest["revenue_per_hour"] or 0)/25*100)
        score = (
            viewer_score*0.35 + retention_score*0.20 +
            chat_score*0.20 + follower_score*0.15 +
            revenue_score*0.10
        )
        return max(0,min(100,score))

class LiveSimulationAdapter:
    def __init__(self, service: LiveStreamService, seed=42):
        self.service=service
        self.random=random.Random(seed)
        self.viewer_level=24
        self.followers=4800
        self.subscribers=45
        self.revenue=0.0
        self.chat=8
        self.tick_count=0

    def start(self,title="Simulation Stream",game="Minecraft"):
        return self.service.start_session(
            title=title,game=game,predicted_average_viewers=28,
            predicted_peak_viewers=45,starting_followers=self.followers,
            starting_subscribers=self.subscribers,
            starting_revenue=self.revenue,source_mode="simulation"
        )

    def tick(self, at=None):
        session=self.service.active_session() or self.start()
        self.tick_count += 1
        drift=self.random.choice([-2,-1,0,1,1,2,3])
        if self.tick_count in {8,18}:
            drift += self.random.randint(12,22)
            self.chat += self.random.randint(25,45)
        else:
            self.chat=max(1,int(self.chat+self.random.choice([-3,-1,0,1,2,3])))
        self.viewer_level=max(1,self.viewer_level+drift)
        if self.random.random()<0.22:
            self.followers += 1
            self.service.add_follow(f"sim_viewer_{self.tick_count}",f"follow-{self.tick_count}")
        if self.random.random()<0.08:
            self.subscribers += 1
        if self.random.random()<0.18:
            self.revenue += round(self.random.uniform(1,8),2)
        captured=(at or datetime.now()).isoformat()
        snapshot=LiveSnapshot(
            captured_at=captured,viewers=self.viewer_level,
            followers_total=self.followers,subscribers_total=self.subscribers,
            revenue_total=self.revenue,chat_messages_minute=self.chat,
            unique_chatters_5m=max(1,int(self.chat*0.7)),
            current_game=session.get("game"),current_title=session.get("title"),
            obs_scene="Gameplay",recording_active=True
        )
        return self.service.record_snapshot(snapshot,session["id"])
