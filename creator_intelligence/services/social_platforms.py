from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from creator_intelligence.core.credential_vault import CredentialVault
from creator_intelligence.services.connection_lifecycle import ConnectionState, ConnectionStatus
from creator_intelligence.services.desktop_oauth import oauth_state, pkce_pair


class SocialPlatformService:
    """Shared credentials, sync state, and published-content analytics."""

    YOUTUBE_SCOPES = (
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    )
    INSTAGRAM_SCOPES = (
        "instagram_business_basic",
        "instagram_business_manage_insights",
    )
    TIKTOK_SCOPES = ("user.info.basic", "video.list")

    FIELDS = {
        "youtube": (
            "api_key", "channel_id", "oauth_client_id", "oauth_client_secret",
            "access_token", "refresh_token", "token_expires_at", "account_name",
            "granted_scopes", "connection_state", "last_validated_at",
        ),
        "instagram": (
            "app_id", "app_secret", "access_token", "account_id", "redirect_uri",
            "token_expires_at", "account_name", "granted_scopes", "connection_state",
            "last_validated_at",
        ),
        "tiktok": (
            "client_key", "client_secret", "access_token", "refresh_token", "user_id",
            "redirect_uri", "token_expires_at", "refresh_expires_at", "account_name",
            "granted_scopes", "connection_state", "last_validated_at",
        ),
    }

    def __init__(self, db, credential_vault=None):
        self.db = db
        self.vault = credential_vault or CredentialVault.for_database(db)
        self._refresh_locks = {platform: threading.Lock() for platform in self.FIELDS}
        self._last_sync_warnings: list[str] = []
        self._ensure_schema()
        self._migrate_legacy_credentials()

    def _ensure_schema(self) -> None:
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS integration_settings(
                integration_id TEXT PRIMARY KEY, enabled INTEGER DEFAULT 0,
                config_json TEXT NOT NULL DEFAULT '{}', last_connected_at TEXT,
                last_error TEXT, updated_at TEXT NOT NULL)"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_published_titles(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL DEFAULT 'twitch',
                content_type TEXT NOT NULL DEFAULT 'clip', title TEXT NOT NULL,
                game TEXT, published_at TEXT, views INTEGER, likes INTEGER,
                comments INTEGER, watch_time REAL,
                example_type TEXT NOT NULL DEFAULT 'published',
                source_video_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                shares INTEGER, reach INTEGER, duration_seconds REAL,
                description TEXT)"""
        )
        columns = {str(row["name"]) for _, row in self.db.frame(
            "PRAGMA table_info(creator_published_titles)"
        ).iterrows()}
        for name, sql_type in (("shares", "INTEGER"), ("reach", "INTEGER"),
                               ("duration_seconds", "REAL"), ("description", "TEXT")):
            if name not in columns:
                self.db.execute(f"ALTER TABLE creator_published_titles ADD COLUMN {name} {sql_type}")
        self._remove_legacy_title_uniqueness()
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_creator_titles_source "
            "ON creator_published_titles(platform,source_video_id)"
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_title_sync_state(
                platform TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'Never synced',
                last_cursor TEXT, last_synced_at TEXT, last_error TEXT,
                records_seen INTEGER NOT NULL DEFAULT 0,
                records_changed INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)"""
        )

    def _remove_legacy_title_uniqueness(self) -> None:
        """Allow two platform posts to legitimately share the same visible title.

        Older workspaces used a title-based UNIQUE constraint. Platform IDs are the
        real record identity; keeping that constraint made a normal re-sync crash
        when an imported title was later associated with its platform ID.
        """
        row = self.db.frame(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='creator_published_titles'"
        )
        if row.empty:
            return
        normalized = "".join(str(row.iloc[0]["sql"] or "").lower().split())
        if "unique(platform,content_type,title)" not in normalized:
            return
        columns = [
            "id", "platform", "content_type", "title", "game", "published_at",
            "views", "likes", "comments", "watch_time", "example_type",
            "source_video_id", "created_at", "updated_at", "shares", "reach",
            "duration_seconds", "description",
        ]
        create_sql = """CREATE TABLE creator_published_titles_new(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL DEFAULT 'twitch',
            content_type TEXT NOT NULL DEFAULT 'clip', title TEXT NOT NULL,
            game TEXT, published_at TEXT, views INTEGER, likes INTEGER,
            comments INTEGER, watch_time REAL,
            example_type TEXT NOT NULL DEFAULT 'published',
            source_video_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            shares INTEGER, reach INTEGER, duration_seconds REAL, description TEXT)"""
        copy_sql = (
            f"INSERT INTO creator_published_titles_new({','.join(columns)}) "
            f"SELECT {','.join(columns)} FROM creator_published_titles"
        )
        if callable(getattr(self.db, "connect", None)):
            with self.db.connect() as connection:
                connection.execute("DROP TABLE IF EXISTS creator_published_titles_new")
                connection.execute(create_sql)
                connection.execute(copy_sql)
                connection.execute("DROP TABLE creator_published_titles")
                connection.execute(
                    "ALTER TABLE creator_published_titles_new RENAME TO creator_published_titles"
                )
            return
        connection = getattr(self.db, "connection", None)
        if connection is None:
            raise RuntimeError("Database connection does not support the title schema upgrade.")
        with connection:
            connection.execute("DROP TABLE IF EXISTS creator_published_titles_new")
            connection.execute(create_sql)
            connection.execute(copy_sql)
            connection.execute("DROP TABLE creator_published_titles")
            connection.execute(
                "ALTER TABLE creator_published_titles_new RENAME TO creator_published_titles"
            )

    def _migrate_legacy_credentials(self) -> None:
        self.db.execute("PRAGMA secure_delete=ON")
        rows=self.db.frame("SELECT integration_id,config_json FROM integration_settings")
        changed=False
        for _,row in rows.iterrows():
            integration_id=str(row["integration_id"])
            platform=integration_id.removesuffix("_title_sync")
            if platform not in self.FIELDS:continue
            try:config=json.loads(row["config_json"] or "{}")
            except (TypeError,ValueError):config={}
            public=self.vault.protect(platform,config)
            if public!=config:
                self.db.execute("UPDATE integration_settings SET config_json=?,updated_at=? WHERE integration_id=?",
                                (json.dumps(public),datetime.now().isoformat(),integration_id))
                changed=True
        if changed:
            self.db.execute("VACUUM")
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def configuration(self, platform: str, reveal: bool = True) -> dict[str, Any]:
        platform = self._platform(platform)
        frame = self.db.frame(
            "SELECT enabled,config_json,last_connected_at,last_error FROM integration_settings WHERE integration_id=?",
            (f"{platform}_title_sync",),
        )
        if frame.empty:
            public = {"enabled": False, **{field: "" for field in self.FIELDS[platform]}}
            return self.vault.reveal(platform,public) if reveal else self.vault.masked(platform,public)
        row = frame.iloc[0]
        result = json.loads(row["config_json"] or "{}")
        result.update(enabled=bool(row["enabled"]), last_connected_at=row["last_connected_at"],
                      last_error=row["last_error"])
        return self.vault.reveal(platform,result) if reveal else self.vault.masked(platform,result)

    def display_configuration(self, platform: str) -> dict[str, Any]:
        return self.configuration(platform,reveal=False)

    def save_configuration(self, platform: str, values: dict[str, Any], enabled: bool = True) -> None:
        platform = self._platform(platform)
        current = self.configuration(platform) if not self.db.frame(
            "SELECT 1 FROM integration_settings WHERE integration_id=?",
            (f"{platform}_title_sync",),
        ).empty else {}
        clean = {
            field: str(values.get(field) if field in values else current.get(field) or "").strip()
            for field in self.FIELDS[platform]
        }
        public = self.vault.protect(platform,clean)
        now = datetime.now().isoformat()
        self.db.execute(
            """INSERT INTO integration_settings(integration_id,enabled,config_json,updated_at)
               VALUES(?,?,?,?) ON CONFLICT(integration_id) DO UPDATE SET
               enabled=excluded.enabled,config_json=excluded.config_json,updated_at=excluded.updated_at""",
            (f"{platform}_title_sync", int(enabled), json.dumps(public), now),
        )

    def disconnect(self, platform: str, revoke=None) -> dict[str, Any]:
        platform=self._platform(platform); config=self.configuration(platform)
        if revoke:
            try:revoke(config)
            except Exception as exc:raise RuntimeError(self.vault.redact(exc)) from None
        self.vault.delete(platform)
        self.db.execute("UPDATE integration_settings SET enabled=0,last_connected_at=NULL,last_error=NULL,updated_at=? WHERE integration_id=?",
                        (datetime.now().isoformat(),f"{platform}_title_sync"))
        return self.connection_status(platform)

    def revoke_and_disconnect(self, platform: str) -> dict[str, Any]:
        platform=self._platform(platform)
        config=self.configuration(platform)
        revoke_error = None
        if platform=="youtube" and (config.get("refresh_token") or config.get("access_token")):
            try:
                self._post_form("https://oauth2.googleapis.com/revoke", {
                    "token": config.get("refresh_token") or config.get("access_token")
                })
            except Exception as exc:
                revoke_error = self.vault.redact(exc)
        elif platform=="tiktok":
            try:
                self._post_form("https://open.tiktokapis.com/v2/oauth/revoke/",{
                    "client_key":config.get("client_key"),"client_secret":config.get("client_secret"),
                    "token":config.get("access_token")})
            except Exception as exc:
                revoke_error = self.vault.redact(exc)
        status = self.disconnect(platform)
        if revoke_error:
            provider = "Google" if platform == "youtube" else "TikTok"
            status["revocation_warning"] = (
                f"Local credentials were cleared, but {provider} could not confirm remote revocation: "
                + revoke_error
            )
        elif platform == "instagram":
            status["revocation_warning"] = (
                "Local credentials were cleared. To remove the remote permission too, open "
                "Instagram Settings > Website permissions > Apps and Websites and remove this app."
            )
        return status

    def connection_status(self, platform: str) -> dict[str, Any]:
        platform = self._platform(platform)
        config = self.configuration(platform)
        if platform == "youtube":
            missing = []
            if not config.get("channel_id"):
                missing.append("channel_id")
            if not (config.get("access_token") or config.get("api_key")):
                missing.append("google_sign_in_or_api_key")
            access_token = bool(config.get("access_token"))
            api_key = bool(config.get("api_key"))
            granted = self._scope_values(config.get("granted_scopes"))
            saved_state = str(config.get("connection_state") or "")
            if not (access_token or api_key):
                state = (
                    ConnectionState.DISCONNECTED
                    if config.get("oauth_client_id") or config.get("channel_id")
                    else ConnectionState.NOT_CONFIGURED
                )
                message = "Connect a Google account to import channel content and analytics."
            elif access_token:
                state = self._connection_state(saved_state, ConnectionState.CONNECTED)
                if self._token_expired(config.get("token_expires_at")) and not config.get("refresh_token"):
                    state = ConnectionState.EXPIRED
                missing_scopes = [scope for scope in self.YOUTUBE_SCOPES if scope not in granted]
                if state == ConnectionState.CONNECTED and missing_scopes:
                    state = ConnectionState.LIMITED
                message = self._youtube_state_message(state, missing_scopes)
            else:
                state = ConnectionState.LIMITED
                message = "API-key mode can sync public videos, but private YouTube Analytics requires Google sign-in."
            lifecycle = ConnectionStatus(
                provider="youtube",
                state=state,
                message=message,
                account_id=config.get("channel_id") or None,
                account_name=config.get("account_name") or None,
                granted_scopes=granted,
                required_scopes=self.YOUTUBE_SCOPES,
                expires_at=config.get("token_expires_at") or None,
                last_validated_at=config.get("last_validated_at") or None,
                last_error=config.get("last_error") or None,
            ).as_dict()
        elif platform == "instagram":
            required = ("app_id", "app_secret", "access_token", "account_id")
            missing = [field for field in required if not config.get(field)]
            granted = self._scope_values(config.get("granted_scopes"))
            state, message = self._social_connection_state(
                platform, config, granted, self.INSTAGRAM_SCOPES,
            )
            lifecycle = ConnectionStatus(
                provider="instagram", state=state, message=message,
                account_id=config.get("account_id") or None,
                account_name=config.get("account_name") or None,
                granted_scopes=granted, required_scopes=self.INSTAGRAM_SCOPES,
                expires_at=config.get("token_expires_at") or None,
                last_validated_at=config.get("last_validated_at") or None,
                last_error=config.get("last_error") or None,
            ).as_dict()
        else:
            required = ("client_key", "client_secret", "access_token", "refresh_token", "user_id")
            missing = [field for field in required if not config.get(field)]
            granted = self._scope_values(config.get("granted_scopes"))
            state, message = self._social_connection_state(
                platform, config, granted, self.TIKTOK_SCOPES,
            )
            lifecycle = ConnectionStatus(
                provider="tiktok", state=state, message=message,
                account_id=config.get("user_id") or None,
                account_name=config.get("account_name") or None,
                granted_scopes=granted, required_scopes=self.TIKTOK_SCOPES,
                expires_at=config.get("token_expires_at") or None,
                last_validated_at=config.get("last_validated_at") or None,
                last_error=config.get("last_error") or None,
            ).as_dict()
        sync = self.db.frame(
            "SELECT * FROM creator_title_sync_state WHERE platform=?", (platform,)
        )
        sync_row = sync.iloc[0].to_dict() if not sync.empty else {}
        legacy = {
            "platform": platform,
            "configured": not missing,
            "missing": missing,
            "sync_status": sync_row.get("status") or "Never synced",
            "last_synced_at": sync_row.get("last_synced_at"),
            "last_error": sync_row.get("last_error") or config.get("last_error"),
            "credential_storage": "Operating-system credential vault",
            "account_name": config.get("account_name"),
        }
        if platform == "youtube":
            lifecycle.update(legacy)
            lifecycle["configured"] = lifecycle["state"] not in {
                ConnectionState.NOT_CONFIGURED.value,
                ConnectionState.DISCONNECTED.value,
            }
            lifecycle["can_sync"] = lifecycle["state"] in {
                ConnectionState.CONNECTED.value,
                ConnectionState.LIMITED.value,
            }
            lifecycle["capabilities"] = self.youtube_capabilities(lifecycle)
            return lifecycle
        lifecycle.update(legacy)
        lifecycle["configured"] = lifecycle["state"] not in {
            ConnectionState.NOT_CONFIGURED.value,
            ConnectionState.DISCONNECTED.value,
        }
        granted_set = set(lifecycle.get("granted_scopes") or ())
        lifecycle["can_sync"] = (
            self.INSTAGRAM_SCOPES[0] in granted_set
            if platform == "instagram"
            else self.TIKTOK_SCOPES[1] in granted_set
        ) and lifecycle["state"] in {
            ConnectionState.CONNECTED.value,
            ConnectionState.LIMITED.value,
        }
        lifecycle["capabilities"] = self.social_capabilities(platform, lifecycle)
        lifecycle["account_policy"] = "One active account per platform in each workspace"
        return lifecycle

    def youtube_capabilities(self, status: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        status = status or self.connection_status("youtube")
        granted = set(status.get("granted_scopes") or ())
        has_public = bool(self.configuration("youtube").get("api_key"))
        return [
            {
                "capability": "Channel identity and published videos",
                "available": has_public or self.YOUTUBE_SCOPES[0] in granted,
                "permission": "YouTube read-only",
            },
            {
                "capability": "Watch time, retention, subscribers, and shares",
                "available": self.YOUTUBE_SCOPES[1] in granted,
                "permission": "YouTube Analytics read-only",
            },
            {
                "capability": "Edit, upload, or delete videos",
                "available": False,
                "permission": "Not requested by Creator Intelligence",
            },
        ]

    def social_capabilities(
        self, platform: str, status: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        platform = self._platform(platform)
        status = status or self.connection_status(platform)
        granted = set(status.get("granted_scopes") or ())
        if platform == "instagram":
            return [
                {
                    "capability": "Professional account identity and published media",
                    "available": self.INSTAGRAM_SCOPES[0] in granted,
                    "permission": "Instagram business basic",
                },
                {
                    "capability": "Available media views, reach, interactions, saves, and shares",
                    "available": self.INSTAGRAM_SCOPES[1] in granted,
                    "permission": "Instagram business insights",
                },
                {
                    "capability": "Personal Instagram accounts",
                    "available": False,
                    "permission": "Not supported by the Instagram professional API",
                },
                {
                    "capability": "Publish, edit, or delete media",
                    "available": False,
                    "permission": "Not requested by Creator Intelligence",
                },
            ]
        return [
            {
                "capability": "TikTok account identity",
                "available": self.TIKTOK_SCOPES[0] in granted,
                "permission": "User info basic",
            },
            {
                "capability": "Public videos, views, likes, comments, and shares",
                "available": self.TIKTOK_SCOPES[1] in granted,
                "permission": "Video list",
            },
            {
                "capability": "Watch time, retention, revenue, and audience analytics",
                "available": False,
                "permission": "Not exposed by TikTok Display API",
            },
            {
                "capability": "Publish, edit, or delete videos",
                "available": False,
                "permission": "Not requested by Creator Intelligence",
            },
        ]

    def content(self, platform: str):
        platform = self._platform(platform)
        return self.db.frame(
            """SELECT id,title,description,content_type,published_at,views,likes,comments,shares,
               reach,watch_time,duration_seconds,source_video_id FROM creator_published_titles
               WHERE platform=? ORDER BY COALESCE(published_at,created_at) DESC""",
            (platform,),
        )

    def summary(self, platform: str) -> dict[str, Any]:
        frame = self.content(platform)
        if frame.empty:
            return {"posts": 0, "views": 0, "likes": 0, "comments": 0, "shares": 0,
                    "watch_time": 0.0, "engagement_rate": 0.0}
        for column in ("views", "likes", "comments", "shares", "watch_time"):
            frame[column] = frame[column].fillna(0)
        views = int(frame["views"].sum())
        engagements = int(frame["likes"].sum() + frame["comments"].sum() + frame["shares"].sum())
        return {"posts": len(frame), "views": views,
                "likes": int(frame["likes"].sum()),
                "comments": int(frame["comments"].sum()),
                "shares": int(frame["shares"].sum()),
                "watch_time": float(frame["watch_time"].sum()),
                "engagement_rate": engagements / views * 100 if views else 0.0}

    def import_youtube_oauth_client(self, path: str | Path) -> dict[str, str]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError("That file is not a valid Google OAuth client JSON file.") from exc
        client = payload.get("installed") if isinstance(payload, dict) else None
        if not isinstance(client, dict) or not client.get("client_id"):
            raise ValueError("Choose OAuth credentials created as a Google Desktop app.")
        values = {
            "oauth_client_id": client.get("client_id"),
            "oauth_client_secret": client.get("client_secret") or "",
        }
        self.save_configuration("youtube", values, True)
        return values

    def begin_oauth(
        self, platform: str, redirect_uri: str | None = None, *, state: str | None = None,
    ) -> dict[str, str]:
        platform = self._platform(platform)
        config = self.configuration(platform)
        state = state or oauth_state()
        if platform == "youtube":
            if not config.get("oauth_client_id"):
                raise ValueError("Import a Google Desktop OAuth client JSON file first.")
            if not redirect_uri:
                raise ValueError("YouTube sign-in needs a local callback address.")
            verifier, challenge = pkce_pair()
            params = {
                "client_id": config.get("oauth_client_id"), "redirect_uri": redirect_uri,
                "response_type": "code", "scope": " ".join(self.YOUTUBE_SCOPES),
                "access_type": "offline", "include_granted_scopes": "true", "prompt": "consent",
                "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
            }
            base = "https://accounts.google.com/o/oauth2/v2/auth"
        elif platform == "instagram":
            target = redirect_uri or config.get("redirect_uri")
            if not config.get("app_id") or not config.get("app_secret") or not target:
                raise ValueError("Save the Meta app ID, app secret, and OAuth redirect URI first.")
            verifier = ""
            params = {"client_id": config.get("app_id"), "redirect_uri": target,
                      "response_type": "code", "scope": "instagram_business_basic,instagram_business_manage_insights",
                      "state": state}
            base = "https://www.instagram.com/oauth/authorize"
        elif platform == "tiktok":
            target = redirect_uri or config.get("redirect_uri")
            if not config.get("client_key") or not config.get("client_secret") or not target:
                raise ValueError("Save the TikTok client key, client secret, and desktop redirect URI first.")
            verifier, challenge = pkce_pair(hex_challenge=True)
            params = {
                "client_key": config.get("client_key"), "redirect_uri": target,
                "response_type": "code", "scope": "user.info.basic,video.list", "state": state,
                "code_challenge": challenge, "code_challenge_method": "S256",
            }
            base = "https://www.tiktok.com/v2/auth/authorize/"
        else:
            raise ValueError(platform)
        return {
            "platform": platform, "authorization_url": base + "?" + urlencode(params),
            "redirect_uri": str(params["redirect_uri"]), "state": state, "code_verifier": verifier,
        }

    def authorization_url(self, platform: str, state: str | None = None) -> str:
        platform = self._platform(platform)
        config = self.configuration(platform)
        return self.begin_oauth(
            platform, config.get("redirect_uri"), state=state,
        )["authorization_url"]

    def complete_oauth(self, platform: str, callback: dict[str, str], flow: dict[str, str]) -> dict[str, Any]:
        platform = self._platform(platform)
        if callback.get("error"):
            raise ValueError(callback.get("error_description") or callback["error"])
        if not callback.get("state") or callback.get("state") != flow.get("state"):
            raise ValueError("The sign-in response did not match this connection request. Please try again.")
        code = callback.get("code") or ""
        if not code:
            raise ValueError("The provider did not return an authorization code.")
        return self.exchange_authorization_code(
            platform, code, redirect_uri=flow.get("redirect_uri"),
            code_verifier=flow.get("code_verifier"),
        )

    def exchange_authorization_code(
        self, platform: str, code: str, *, redirect_uri: str | None = None,
        code_verifier: str | None = None,
    ) -> dict[str, Any]:
        platform = self._platform(platform)
        config = self.configuration(platform)
        target = redirect_uri or config.get("redirect_uri")
        if platform == "youtube":
            payload = self._post_form("https://oauth2.googleapis.com/token", {
                "client_id": config.get("oauth_client_id"),
                "client_secret": config.get("oauth_client_secret"), "code": code,
                "code_verifier": code_verifier, "grant_type": "authorization_code",
                "redirect_uri": target,
            })
            config.update(
                access_token=payload.get("access_token") or "",
                refresh_token=payload.get("refresh_token") or config.get("refresh_token") or "",
                token_expires_at=self._expires_at(payload.get("expires_in")),
                granted_scopes=payload.get("scope") or " ".join(self.YOUTUBE_SCOPES),
                connection_state=ConnectionState.CONNECTING.value,
            )
            identity = self._youtube_identity(config)
            config.update(
                identity,
                connection_state=ConnectionState.CONNECTED.value,
                last_validated_at=datetime.now().isoformat(),
            )
        elif platform == "instagram":
            payload = self._post_form("https://api.instagram.com/oauth/access_token", {
                "client_id": config.get("app_id"), "client_secret": config.get("app_secret"),
                "grant_type": "authorization_code", "redirect_uri": target, "code": code,
            })
            config.update(
                access_token=payload.get("access_token") or "",
                account_id=str(payload.get("user_id") or payload.get("id") or ""),
                granted_scopes=payload.get("scope") or " ".join(self.INSTAGRAM_SCOPES),
                connection_state=ConnectionState.CONNECTING.value,
            )
            try:
                long_lived = self._json_request(Request(
                    "https://graph.instagram.com/access_token?" + urlencode({
                        "grant_type": "ig_exchange_token", "client_secret": config.get("app_secret"),
                        "access_token": config.get("access_token"),
                    })
                ))
                config["access_token"] = long_lived.get("access_token") or config["access_token"]
                config["token_expires_at"] = self._expires_at(long_lived.get("expires_in"))
            except Exception:
                config["token_expires_at"] = self._expires_at(payload.get("expires_in"))
            identity = self._instagram_identity(config)
            config.update(
                identity,
                connection_state=ConnectionState.CONNECTED.value,
                last_validated_at=datetime.now().isoformat(),
            )
        elif platform == "tiktok":
            payload = self._post_form("https://open.tiktokapis.com/v2/oauth/token/", {
                "client_key": config.get("client_key"), "client_secret": config.get("client_secret"),
                "code": code, "code_verifier": code_verifier,
                "grant_type": "authorization_code", "redirect_uri": target,
            })
            config.update(
                access_token=payload.get("access_token") or "",
                refresh_token=payload.get("refresh_token") or "",
                user_id=payload.get("open_id") or config.get("user_id") or "",
                token_expires_at=self._expires_at(payload.get("expires_in")),
                refresh_expires_at=self._expires_at(payload.get("refresh_expires_in")),
                granted_scopes=payload.get("scope") or " ".join(self.TIKTOK_SCOPES),
                connection_state=ConnectionState.CONNECTING.value,
            )
            identity = self._tiktok_identity(config)
            config.update(
                identity,
                connection_state=ConnectionState.CONNECTED.value,
                last_validated_at=datetime.now().isoformat(),
            )
        else:
            raise ValueError(platform)
        if target and platform != "youtube":
            config["redirect_uri"] = target
        self.save_configuration(platform, config, True)
        self._set_integration_error(platform, None, connected=True)
        return {
            "connected": True, "expires_in": payload.get("expires_in"),
            "account_id": config.get("channel_id") or config.get("account_id") or config.get("user_id"),
            "account_name": config.get("account_name"),
        }

    def refresh_access_token(self, platform: str) -> dict[str, Any]:
        platform = self._platform(platform)
        with self._refresh_locks[platform]:
            config = self.configuration(platform)
            try:
                if platform == "youtube":
                    if not config.get("refresh_token"):
                        raise ValueError("Reconnect YouTube to obtain a refresh token.")
                    payload = self._post_form("https://oauth2.googleapis.com/token", {
                        "client_id": config.get("oauth_client_id"),
                        "client_secret": config.get("oauth_client_secret"),
                        "grant_type": "refresh_token", "refresh_token": config.get("refresh_token"),
                    })
                elif platform == "instagram":
                    payload = self._json_request(Request(
                        "https://graph.instagram.com/refresh_access_token?" + urlencode({
                            "grant_type": "ig_refresh_token", "access_token": config.get("access_token")
                        })
                    ))
                elif platform == "tiktok":
                    payload = self._post_form("https://open.tiktokapis.com/v2/oauth/token/", {
                        "client_key": config.get("client_key"), "client_secret": config.get("client_secret"),
                        "grant_type": "refresh_token", "refresh_token": config.get("refresh_token"),
                    })
                else:
                    raise ValueError("This platform does not use token refresh here.")
            except Exception as exc:
                safe = self.vault.redact(exc)
                state = self._state_for_error(exc)
                if state == ConnectionState.ERROR:
                    state = ConnectionState.EXPIRED
                config.update(connection_state=state.value)
                self.save_configuration(platform, config, True)
                self._set_integration_error(platform, safe)
                raise
            config["access_token"] = payload.get("access_token") or config.get("access_token") or ""
            if payload.get("refresh_token"):
                config["refresh_token"] = payload["refresh_token"]
            if payload.get("scope"):
                config["granted_scopes"] = payload["scope"]
            config["token_expires_at"] = self._expires_at(payload.get("expires_in"))
            if payload.get("refresh_expires_in"):
                config["refresh_expires_at"] = self._expires_at(payload.get("refresh_expires_in"))
            required = {
                "youtube": self.YOUTUBE_SCOPES,
                "instagram": self.INSTAGRAM_SCOPES,
                "tiktok": self.TIKTOK_SCOPES,
            }[platform]
            granted = set(self._scope_values(config.get("granted_scopes")))
            config["connection_state"] = (
                ConnectionState.CONNECTED.value
                if all(scope in granted for scope in required)
                else ConnectionState.LIMITED.value
            )
            self.save_configuration(platform, config, True)
            return {"refreshed": True, "expires_in": payload.get("expires_in")}

    def validate_connection(self, platform: str) -> dict[str, Any]:
        """Validate provider access, refreshing an expired token once when possible."""
        platform = self._platform(platform)
        config = self.configuration(platform)
        if not config.get("access_token"):
            return self.connection_status(platform)
        can_refresh = bool(
            config.get("refresh_token")
            or (platform == "instagram" and config.get("access_token"))
        )
        try:
            refresh_due = self._token_expired(config.get("token_expires_at"))
            if platform == "instagram":
                refresh_due = self._token_near_expiry(
                    config.get("token_expires_at"), days=7,
                )
            if refresh_due and can_refresh:
                self.refresh_access_token(platform)
                config = self.configuration(platform)
            try:
                identity = {
                    "youtube": self._youtube_identity,
                    "instagram": self._instagram_identity,
                    "tiktok": self._tiktok_identity,
                }[platform](config)
            except Exception as first_error:
                if not self._is_auth_error(first_error) or not can_refresh:
                    raise
                self.refresh_access_token(platform)
                config = self.configuration(platform)
                identity = {
                    "youtube": self._youtube_identity,
                    "instagram": self._instagram_identity,
                    "tiktok": self._tiktok_identity,
                }[platform](config)
            required = {
                "youtube": self.YOUTUBE_SCOPES,
                "instagram": self.INSTAGRAM_SCOPES,
                "tiktok": self.TIKTOK_SCOPES,
            }[platform]
            granted = set(self._scope_values(config.get("granted_scopes")))
            config.update(
                identity,
                connection_state=(
                    ConnectionState.CONNECTED.value
                    if all(scope in granted for scope in required)
                    else ConnectionState.LIMITED.value
                ),
                last_validated_at=datetime.now().isoformat(),
            )
            self.save_configuration(platform, config, True)
            self._set_integration_error(platform, None, connected=True)
        except Exception as exc:
            safe = self.vault.redact(exc)
            config = self.configuration(platform)
            state = self._state_for_error(exc)
            config["connection_state"] = state.value
            self.save_configuration(platform, config, True)
            self._set_integration_error(platform, safe)
        return self.connection_status(platform)

    def _youtube_identity(self, config: dict[str, Any]) -> dict[str, str]:
        payload = self._json_request(Request(
            "https://www.googleapis.com/youtube/v3/channels?" + urlencode({
                "part": "id,snippet", "mine": "true",
            }),
            headers={"Authorization": f"Bearer {config.get('access_token')}"},
        ))
        items = payload.get("items") or []
        if not items:
            raise ValueError("The selected Google account does not have a YouTube channel.")
        item = items[0]
        return {
            "channel_id": str(item.get("id") or ""),
            "account_name": str((item.get("snippet") or {}).get("title") or ""),
        }

    @staticmethod
    def _scope_values(value: Any) -> tuple[str, ...]:
        if isinstance(value, (list, tuple, set)):
            return tuple(str(scope) for scope in value if scope)
        return tuple(str(value or "").replace(",", " ").split())

    @staticmethod
    def _connection_state(value: str, fallback: ConnectionState) -> ConnectionState:
        try:
            return ConnectionState(value)
        except ValueError:
            return fallback

    def _social_connection_state(
        self,
        platform: str,
        config: dict[str, Any],
        granted_scopes: tuple[str, ...],
        required_scopes: tuple[str, ...],
    ) -> tuple[ConnectionState, str]:
        access_token = bool(config.get("access_token"))
        setup_started = bool(
            config.get("app_id") or config.get("client_key")
            or config.get("account_id") or config.get("user_id")
        )
        if not access_token:
            state = ConnectionState.DISCONNECTED if setup_started else ConnectionState.NOT_CONFIGURED
        else:
            state = self._connection_state(
                str(config.get("connection_state") or ""), ConnectionState.CONNECTED,
            )
            if self._token_expired(config.get("token_expires_at")):
                state = (
                    ConnectionState.REVOKED
                    if platform == "tiktok" and self._token_expired(config.get("refresh_expires_at"))
                    else ConnectionState.EXPIRED
                )
            missing = [scope for scope in required_scopes if scope not in granted_scopes]
            if state == ConnectionState.CONNECTED and missing:
                state = ConnectionState.LIMITED
        missing = [scope for scope in required_scopes if scope not in granted_scopes]
        return state, self._social_state_message(platform, state, missing)

    @staticmethod
    def _social_state_message(
        platform: str, state: ConnectionState, missing_scopes: list[str],
    ) -> str:
        name = platform.title()
        if state == ConnectionState.CONNECTED:
            return f"{name} is connected and ready for read-only content syncing."
        if state == ConnectionState.LIMITED:
            if missing_scopes:
                return (
                    f"{name} is connected with limited access. Reconnect to approve the "
                    "missing read-only permissions."
                )
            return f"{name} is connected, but an API limit is temporarily blocking part of the sync."
        if state == ConnectionState.EXPIRED:
            return f"The {name} session expired and could not refresh. Reconnect the account."
        if state == ConnectionState.REVOKED:
            return f"{name} access was revoked or invalidated. Reconnect the account to continue."
        if state == ConnectionState.ERROR:
            return f"{name} could not be validated. Review the error and try again."
        if state == ConnectionState.DISCONNECTED:
            return f"{name} setup is saved, but no account is connected."
        return f"Add the {name} app details, then connect an account."

    @staticmethod
    def _token_expired(value: Any) -> bool:
        if not value:
            return False
        try:
            expires = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            now = datetime.now(expires.tzinfo) if expires.tzinfo else datetime.now()
            return expires <= now + timedelta(minutes=2)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _token_near_expiry(value: Any, *, days: int) -> bool:
        if not value:
            return False
        try:
            expires = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            now = datetime.now(expires.tzinfo) if expires.tzinfo else datetime.now()
            return expires <= now + timedelta(days=days)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(marker in text for marker in (
            "http 401", "invalid credentials", "invalid_grant", "unauthorized", "expired token",
            "access token has expired", "invalid oauth access token", "error validating access token",
            "invalid access token",
        ))

    @classmethod
    def _state_for_error(cls, exc: Exception) -> ConnectionState:
        text = str(exc).lower()
        if any(marker in text for marker in (
            "invalid_grant", "revoked", "deleted_client", "invalid oauth access token",
            "invalid access token",
        )):
            return ConnectionState.REVOKED
        if cls._is_auth_error(exc):
            return ConnectionState.EXPIRED
        if any(marker in text for marker in (
            "quotaexceeded", "dailylimitexceeded", "ratelimitexceeded",
            "userratelimitexceeded", "http 429", "too many requests",
        )):
            return ConnectionState.LIMITED
        return ConnectionState.ERROR

    @staticmethod
    def _youtube_state_message(state: ConnectionState, missing_scopes: list[str]) -> str:
        if state == ConnectionState.CONNECTED:
            return "YouTube content and read-only Analytics access are ready."
        if state == ConnectionState.LIMITED:
            if missing_scopes:
                return "YouTube is connected with limited access. Reconnect to approve the missing read-only permissions."
            return "YouTube is connected, but an API limit is temporarily blocking part of the sync."
        if state == ConnectionState.EXPIRED:
            return "The YouTube session expired and could not refresh. Reconnect the Google account."
        if state == ConnectionState.REVOKED:
            return "Google access was revoked or invalidated. Reconnect the account to continue."
        if state == ConnectionState.ERROR:
            return "YouTube could not be validated. Review the error and try again."
        return "Connect a Google account to import channel content and analytics."

    def _set_integration_error(
        self, platform: str, error: str | None, *, connected: bool = False,
    ) -> None:
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE integration_settings
               SET last_error=?,last_connected_at=CASE WHEN ? THEN ? ELSE last_connected_at END,
                   updated_at=? WHERE integration_id=?""",
            (error, int(connected), now, now, f"{platform}_title_sync"),
        )

    def _instagram_identity(self, config: dict[str, Any]) -> dict[str, str]:
        payload = self._json_request(Request(
            "https://graph.instagram.com/me?" + urlencode({
                "fields": "id,user_id,username", "access_token": config.get("access_token"),
            })
        ))
        account_id = str(payload.get("user_id") or payload.get("id") or config.get("account_id") or "")
        if not account_id:
            raise ValueError(
                "Instagram did not return a professional account ID. Business or Creator accounts are required."
            )
        return {
            "account_id": account_id,
            "account_name": str(payload.get("username") or config.get("account_name") or ""),
        }

    def _tiktok_identity(self, config: dict[str, Any]) -> dict[str, str]:
        payload = self._json_request(Request(
            "https://open.tiktokapis.com/v2/user/info/?fields=open_id,union_id,avatar_url,display_name",
            headers={"Authorization": f"Bearer {config.get('access_token')}"},
        ))
        user = ((payload.get("data") or {}).get("user") or {})
        user_id = str(user.get("open_id") or config.get("user_id") or "")
        if not user_id:
            raise ValueError("TikTok did not return an account ID. Confirm that user.info.basic is approved.")
        return {"user_id": user_id, "account_name": str(user.get("display_name") or "")}

    @staticmethod
    def _expires_at(expires_in: Any) -> str:
        try:
            seconds = max(0, int(expires_in or 0))
        except (TypeError, ValueError):
            seconds = 0
        return (datetime.now() + timedelta(seconds=seconds)).isoformat() if seconds else ""

    def sync(self, platform: str, fetcher=None) -> dict[str, Any]:
        platform = self._platform(platform)
        now = datetime.now().isoformat()
        self._last_sync_warnings = []
        prior = self.connection_status(platform)
        if not prior["configured"]:
            raise ValueError("Complete the API setup before syncing.")
        cursor_frame = self.db.frame("SELECT last_cursor FROM creator_title_sync_state WHERE platform=?", (platform,))
        cursor = cursor_frame.iloc[0]["last_cursor"] if not cursor_frame.empty else None
        try:
            try:
                records = list((fetcher or self._fetch_records)(platform, cursor))
            except Exception as first_error:
                token_error = self._is_auth_error(first_error)
                config = self.configuration(platform)
                can_refresh = bool(
                    config.get("refresh_token")
                    or (platform == "instagram" and config.get("access_token"))
                )
                if fetcher is not None or not token_error or not can_refresh:
                    raise
                self.refresh_access_token(platform)
                records = list(self._fetch_records(platform, cursor))
            changed = 0
            newest = cursor
            for record in records:
                changed += self._upsert_record(platform, record)
                newest = max(filter(None, [newest, str(record.get("published_at") or "")]), default=newest)
            from creator_intelligence.services.publishing_outcomes import PublishingOutcomeService
            outcomes = PublishingOutcomeService(self.db).process_sync(platform)
            self._record_sync(platform, "Completed", newest, len(records), changed, None, now)
            if self.configuration(platform).get("access_token"):
                config = self.configuration(platform)
                required = {
                    "youtube": self.YOUTUBE_SCOPES,
                    "instagram": self.INSTAGRAM_SCOPES,
                    "tiktok": self.TIKTOK_SCOPES,
                }[platform]
                granted = set(self._scope_values(config.get("granted_scopes")))
                config["connection_state"] = (
                    ConnectionState.LIMITED.value
                    if self._last_sync_warnings or not all(scope in granted for scope in required)
                    else ConnectionState.CONNECTED.value
                )
                self.save_configuration(platform, config, True)
                self._set_integration_error(
                    platform, "; ".join(self._last_sync_warnings) or None, connected=True
                )
            return {"platform": platform, "seen": len(records), "changed": changed,
                    "unchanged": len(records) - changed, "last_cursor": newest,
                    "outcomes_matched": outcomes["matched"],
                    "outcome_snapshots": outcomes["snapshots"],
                    "warnings": list(self._last_sync_warnings)}
        except Exception as exc:
            safe=self.vault.redact(exc)
            self._record_sync(platform, "Failed", cursor, 0, 0, safe, now)
            config = self.configuration(platform)
            config["connection_state"] = self._state_for_error(exc).value
            self.save_configuration(platform, config, True)
            self._set_integration_error(platform, safe)
            raise RuntimeError(safe) from None

    def _upsert_record(self, platform: str, record: dict[str, Any]) -> int:
        from creator_intelligence.services.creator_dna import CreatorDNAService
        dna = CreatorDNAService(self.db)
        dna.ensure_event_history()
        source_id = str(record.get("source_video_id") or record.get("id") or "").strip()
        if not source_id:
            raise ValueError("Platform record is missing its source ID.")
        title = str(record.get("title") or record.get("caption") or "Untitled post").strip()
        content_type = str(record.get("content_type") or "short")
        existing = self.db.frame(
            "SELECT * FROM creator_published_titles WHERE platform=? AND source_video_id=?",
            (platform, source_id),
        )
        if existing.empty:
            # Claim legacy/manual title history instead of inserting a duplicate.
            existing = self.db.frame(
                """SELECT * FROM creator_published_titles
                   WHERE platform=? AND content_type=? AND title=?
                     AND (source_video_id IS NULL OR source_video_id='')
                   ORDER BY id LIMIT 1""",
                (platform, content_type, title),
            )
        values = (record.get("content_type") or "short", title, record.get("description"), record.get("published_at"),
                  self._number(record.get("views"), int), self._number(record.get("likes"), int),
                  self._number(record.get("comments"), int), self._number(record.get("shares"), int),
                  self._number(record.get("reach"), int), self._number(record.get("watch_time"), float),
                  self._number(record.get("duration_seconds"), float))
        changed = existing.empty or tuple(self._normalized(existing.iloc[0].get(name)) for name in (
            "content_type", "title", "description", "published_at", "views", "likes", "comments", "shares",
            "reach", "watch_time", "duration_seconds")) != values
        now = datetime.now().isoformat()
        if existing.empty:
            self.db.execute("""INSERT INTO creator_published_titles(
                platform,content_type,title,description,published_at,views,likes,comments,shares,reach,
                watch_time,duration_seconds,example_type,source_video_id,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'published',?,?,?)""",
                (platform, *values, source_id, now, now))
        else:
            self.db.execute("""UPDATE creator_published_titles SET content_type=?,title=?,description=?,published_at=?,
                views=?,likes=?,comments=?,shares=?,reach=?,watch_time=?,duration_seconds=?,source_video_id=?,
                example_type='published',updated_at=? WHERE id=?""",
                (*values, source_id, now, int(existing.iloc[0]["id"])))
        if changed:
            current = self.db.frame(
                "SELECT * FROM creator_published_titles WHERE platform=? AND source_video_id=?",
                (platform, source_id),
            ).iloc[0].to_dict()
            before_safe = dna._json_safe(existing.iloc[0].to_dict()) if not existing.empty else None
            current_safe = dna._json_safe(current)
            polarity, weight = dna.historical_title_evidence(current_safe)
            compared = (
                "platform", "content_type", "title", "description", "published_at",
                "views", "likes", "comments", "shares", "reach", "watch_time",
                "duration_seconds", "example_type", "source_video_id",
            )
            fingerprint = hashlib.sha256(
                json.dumps(
                    {name: current_safe.get(name) for name in compared}, sort_keys=True
                ).encode("utf-8")
            ).hexdigest()
            dna.record_event(
                "historical_title_recorded" if before_safe is None else "historical_title_updated",
                subject_type="published_title",
                subject_id=int(current_safe["id"]),
                platform=platform,
                evidence_polarity=polarity,
                evidence_weight=weight,
                field_name="title",
                old_value=before_safe.get("title") if before_safe else None,
                new_value=title,
                metadata={"record": current_safe, "sync_source": platform},
                source="social_platform_sync",
                event_key=f"historical-title:{current_safe['id']}:{fingerprint}",
            )
        if platform == "youtube":
            self._mirror_youtube_content(record, title)
        return int(changed)

    def _mirror_youtube_content(self, record: dict[str, Any], title: str) -> None:
        columns = {str(row["name"]) for _, row in self.db.frame(
            "PRAGMA table_info(youtube_content)"
        ).iterrows()}
        if not columns:
            return
        values = {
            "content_id": str(record.get("source_video_id") or record.get("id")),
            "title": title, "description": record.get("description"),
            "publish_time": record.get("published_at"),
            "duration_seconds": self._number_or_zero(record.get("duration_seconds"), float),
            "views": self._number_or_zero(record.get("views"), int),
            "likes": self._number_or_zero(record.get("likes"), int),
            "comments": self._number_or_zero(record.get("comments"), int),
            "shares": self._number_or_zero(record.get("shares"), int),
            "engaged_views": self._number_or_zero(record.get("engaged_views"), int),
            "watch_time_hours": self._number_or_zero(record.get("watch_time_hours"), float),
            "avg_percentage_viewed": self._number_or_zero(record.get("avg_percentage_viewed"), float),
            "subscribers_gained": self._number_or_zero(record.get("subscribers_gained"), int),
            "subscribers_lost": self._number_or_zero(record.get("subscribers_lost"), int),
        }
        available = [name for name in values if name in columns]
        update = [name for name in available if name != "content_id"]
        self.db.execute(
            f"""INSERT INTO youtube_content({','.join(available)})
                VALUES({','.join('?' for _ in available)})
                ON CONFLICT(content_id) DO UPDATE SET
                {','.join(f'{name}=excluded.{name}' for name in update)}""",
            tuple(values[name] for name in available),
        )

    def _fetch_records(self, platform: str, cursor: str | None):
        if platform == "youtube":
            return self._fetch_youtube(cursor)
        return self._fetch_instagram(cursor) if platform == "instagram" else self._fetch_tiktok(cursor)

    def _fetch_youtube(self, cursor: str | None):
        config = self.configuration("youtube")
        channel_params = {
            "part": "contentDetails",
            "id": config["channel_id"],
        }
        if config.get("api_key"):
            channel_params["key"] = config["api_key"]
        headers = ({"Authorization": f"Bearer {config.get('access_token')}"}
                   if config.get("access_token") else {})
        channel = self._json_request(Request(
            "https://www.googleapis.com/youtube/v3/channels?" + urlencode(channel_params),
            headers=headers,
        ))
        channel_items = channel.get("items") or []
        uploads_playlist = (
            ((channel_items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
            if channel_items else None
        )
        if not uploads_playlist:
            raise ValueError("YouTube did not return the channel uploads playlist.")
        params = {"part": "snippet,contentDetails", "playlistId": uploads_playlist, "maxResults": 50}
        if config.get("api_key"):
            params["key"] = config["api_key"]
        snippets = {}
        while True:
            payload = self._json_request(Request(
                "https://www.googleapis.com/youtube/v3/playlistItems?" + urlencode(params), headers=headers,
            ))
            for item in payload.get("items", []):
                video_id = str((item.get("contentDetails") or {}).get("videoId") or "")
                if video_id:
                    snippets[video_id] = item.get("snippet", {})
            if not payload.get("nextPageToken"):
                break
            params["pageToken"] = payload["nextPageToken"]
        records = []
        ids = list(snippets)
        for offset in range(0, len(ids), 50):
            detail_params = {
                "part": "statistics,contentDetails", "id": ",".join(ids[offset:offset + 50]),
            }
            if config.get("api_key"):
                detail_params["key"] = config["api_key"]
            detail = self._json_request(Request(
                "https://www.googleapis.com/youtube/v3/videos?" + urlencode(detail_params),
                headers=headers,
            ))
            for item in detail.get("items", []):
                snippet = snippets[item["id"]]
                stats = item.get("statistics") or {}
                duration = self._iso_duration_seconds((item.get("contentDetails") or {}).get("duration") or "")
                records.append({"source_video_id": item["id"], "title": snippet.get("title"),
                                "description": snippet.get("description"),
                                "content_type": "short" if duration <= 180 else "video",
                                "published_at": snippet.get("publishedAt"), "duration_seconds": duration,
                                "views": stats.get("viewCount"), "likes": stats.get("likeCount"),
                                "comments": stats.get("commentCount")})
        granted = set(self._scope_values(config.get("granted_scopes")))
        if config.get("access_token") and self.YOUTUBE_SCOPES[1] in granted:
            try:
                analytics = self._fetch_youtube_analytics(config)
            except Exception as exc:
                self._last_sync_warnings.append(
                    "Published videos synced, but YouTube Analytics is temporarily unavailable: "
                    + self.vault.redact(exc)
                )
            else:
                for record in records:
                    record.update(analytics.get(record["source_video_id"], {}))
        elif config.get("access_token"):
            self._last_sync_warnings.append(
                "Reconnect YouTube to grant read-only Analytics access for watch time, retention, and subscriber stats."
            )
        return records

    def _fetch_youtube_analytics(self, config: dict[str, Any]) -> dict[str, dict[str, Any]]:
        metrics = (
            "views,engagedViews,estimatedMinutesWatched,averageViewPercentage,"
            "subscribersGained,subscribersLost,likes,comments,shares"
        )
        start_index = 1
        result: dict[str, dict[str, Any]] = {}
        while True:
            params = {
                "ids": "channel==MINE",
                "startDate": "2000-01-01",
                "endDate": datetime.now(UTC).date().isoformat(),
                "metrics": metrics,
                "dimensions": "video",
                "sort": "-views",
                "maxResults": 200,
                "startIndex": start_index,
            }
            payload = self._json_request(Request(
                "https://youtubeanalytics.googleapis.com/v2/reports?" + urlencode(params),
                headers={"Authorization": f"Bearer {config.get('access_token')}"},
            ))
            names = [str(column.get("name") or "") for column in payload.get("columnHeaders", [])]
            rows = payload.get("rows") or []
            for values in rows:
                row = dict(zip(names, values, strict=False))
                video_id = str(row.get("video") or "")
                if not video_id:
                    continue
                minutes = self._number_or_zero(row.get("estimatedMinutesWatched"), float)
                result[video_id] = {
                    "views": self._number_or_zero(row.get("views"), int),
                    "engaged_views": self._number_or_zero(row.get("engagedViews"), int),
                    "watch_time": minutes / 60,
                    "watch_time_hours": minutes / 60,
                    "avg_percentage_viewed": self._number_or_zero(row.get("averageViewPercentage"), float),
                    "subscribers_gained": self._number_or_zero(row.get("subscribersGained"), int),
                    "subscribers_lost": self._number_or_zero(row.get("subscribersLost"), int),
                    "likes": self._number_or_zero(row.get("likes"), int),
                    "comments": self._number_or_zero(row.get("comments"), int),
                    "shares": self._number_or_zero(row.get("shares"), int),
                }
            if len(rows) < 200:
                break
            start_index += len(rows)
        return result

    def _fetch_instagram(self, cursor: str | None):
        config = self.configuration("instagram")
        url = f"https://graph.instagram.com/{config['account_id']}/media?" + urlencode({
            "fields": "id,caption,media_type,timestamp,like_count,comments_count",
            "limit": 100, "access_token": config["access_token"],
        })
        records = []
        granted = set(self._scope_values(config.get("granted_scopes")))
        insights_available = (
            self.INSTAGRAM_SCOPES[1] in granted or not granted
        )
        page_count = 0
        while url and page_count < 10:
            page_count += 1
            payload = self._json_request(Request(url))
            for item in payload.get("data", []):
                timestamp = item.get("timestamp")
                insights = (
                    self._instagram_media_insights(
                        str(item.get("id") or ""), config["access_token"],
                    )
                    if insights_available else {}
                )
                records.append({"source_video_id": item.get("id"), "title": item.get("caption") or "Untitled post",
                                "content_type": str(item.get("media_type") or "post").lower(),
                                "published_at": timestamp, "views": insights.get("views"),
                                "reach": insights.get("reach"), "shares": insights.get("shares"),
                                "likes": item.get("like_count"),
                                "comments": item.get("comments_count")})
            url = (payload.get("paging") or {}).get("next")
        if url:
            self._append_sync_warning(
                "Instagram returned more than 1,000 recent media items; this sync was capped to protect API limits."
            )
        return records

    def _instagram_media_insights(self, media_id: str, access_token: str) -> dict[str, Any]:
        metrics = ("views", "reach", "total_interactions", "saved", "shares")

        def request(names: tuple[str, ...]) -> dict[str, Any]:
            payload = self._json_request(Request(
                f"https://graph.instagram.com/{media_id}/insights?" + urlencode({
                    "metric": ",".join(names), "access_token": access_token,
                })
            ))
            result: dict[str, Any] = {}
            for metric in payload.get("data", []):
                values = metric.get("values") or []
                total = metric.get("total_value") or {}
                result[str(metric.get("name") or "")] = (
                    values[0].get("value") if values else total.get("value", metric.get("value"))
                )
            return result

        try:
            return request(metrics)
        except Exception as combined_error:
            if self._is_auth_error(combined_error):
                raise
            result: dict[str, Any] = {}
            failures = []
            for metric in metrics:
                try:
                    result.update(request((metric,)))
                except Exception as metric_error:
                    if self._is_auth_error(metric_error):
                        raise
                    failures.append(metric)
            if failures:
                self._append_sync_warning(
                    "Some Instagram insights were unavailable for this account or media type: "
                    + ", ".join(failures)
                )
            return result

    def _fetch_tiktok(self, cursor: str | None):
        config = self.configuration("tiktok")
        url = "https://open.tiktokapis.com/v2/video/list/?fields=id,title,video_description,duration,create_time,view_count,like_count,comment_count,share_count"
        body = {"max_count": 20}
        records = []
        page_count = 0
        while page_count < 10:
            page_count += 1
            payload = self._json_request(Request(
                url, data=json.dumps(body).encode("utf-8"), method="POST",
                headers={"Authorization": f"Bearer {config['access_token']}", "Content-Type": "application/json"},
            ))
            data = payload.get("data") or {}
            for item in data.get("videos", []):
                published = datetime.fromtimestamp(
                    int(item.get("create_time") or 0), UTC,
                ).isoformat()
                records.append({"source_video_id": item.get("id"),
                                "title": item.get("title") or item.get("video_description") or "Untitled video",
                                "content_type": "short", "published_at": published,
                                "duration_seconds": item.get("duration"), "views": item.get("view_count"),
                                "likes": item.get("like_count"), "comments": item.get("comment_count"),
                                "shares": item.get("share_count")})
            if not data.get("has_more"):
                break
            body["cursor"] = data.get("cursor")
        else:
            self._append_sync_warning(
                "TikTok returned more than 200 recent videos; this sync was capped to protect API limits."
            )
        return records

    def _append_sync_warning(self, warning: str) -> None:
        if warning not in self._last_sync_warnings:
            self._last_sync_warnings.append(warning)

    def _record_sync(self, platform, status, cursor, seen, changed, error, now):
        self.db.execute("""INSERT INTO creator_title_sync_state(
            platform,status,last_cursor,last_synced_at,last_error,records_seen,records_changed,updated_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(platform) DO UPDATE SET status=excluded.status,
            last_cursor=excluded.last_cursor,last_synced_at=excluded.last_synced_at,last_error=excluded.last_error,
            records_seen=excluded.records_seen,records_changed=excluded.records_changed,updated_at=excluded.updated_at""",
            (platform, status, cursor, now if status == "Completed" else None, error, seen, changed, now))

    @staticmethod
    def _number(value, cast):
        return cast(value) if value not in (None, "") else None

    @classmethod
    def _number_or_zero(cls, value, cast):
        number = cls._number(value, cast)
        return number if number is not None else cast(0)

    @staticmethod
    def _normalized(value):
        return None if value is None or value != value else value

    @staticmethod
    def _iso_duration_seconds(value: str) -> int:
        import re
        match = re.fullmatch(r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?", value)
        if not match:
            return 181
        parts = {key: int(number or 0) for key, number in match.groupdict().items()}
        return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]

    @staticmethod
    def _json_request(request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8").strip()
                return json.loads(body) if body else {}
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {}
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                message = str(error.get("message") or exc.reason or "Provider request failed")
                details = error.get("errors") or []
                reason = str(error.get("code") or "")
                if not reason and details:
                    reason = str(details[0].get("reason") or "")
            else:
                message = str(error or exc.reason or "Provider request failed")
                reason = ""
            suffix = f" ({reason})" if reason else ""
            raise RuntimeError(f"HTTP {exc.code}: {message}{suffix}") from None

    @classmethod
    def _post_form(cls, url: str, values: dict[str, Any]) -> dict[str, Any]:
        request = Request(url, data=urlencode({k: v for k, v in values.items() if v is not None}).encode("utf-8"),
                          method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        return cls._json_request(request)

    def _platform(self, platform: str) -> str:
        clean = platform.strip().lower()
        if clean not in self.FIELDS:
            raise ValueError(f"Unsupported social platform: {platform}")
        return clean
