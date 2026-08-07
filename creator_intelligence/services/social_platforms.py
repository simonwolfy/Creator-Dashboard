from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from creator_intelligence.core.credential_vault import CredentialVault


class SocialPlatformService:
    """Shared credentials, sync state, and published-content analytics."""

    FIELDS = {
        "youtube": ("api_key", "channel_id"),
        "instagram": ("app_id", "app_secret", "access_token", "account_id", "redirect_uri"),
        "tiktok": ("client_key", "client_secret", "access_token", "refresh_token", "user_id", "redirect_uri"),
    }

    def __init__(self, db, credential_vault=None):
        self.db = db
        self.vault = credential_vault or CredentialVault.for_database(db)
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
                UNIQUE(platform,content_type,title))"""
        )
        columns = {str(row["name"]) for _, row in self.db.frame(
            "PRAGMA table_info(creator_published_titles)"
        ).iterrows()}
        for name, sql_type in (("shares", "INTEGER"), ("reach", "INTEGER"),
                               ("duration_seconds", "REAL"), ("description", "TEXT")):
            if name not in columns:
                self.db.execute(f"ALTER TABLE creator_published_titles ADD COLUMN {name} {sql_type}")
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_title_sync_state(
                platform TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'Never synced',
                last_cursor TEXT, last_synced_at TEXT, last_error TEXT,
                records_seen INTEGER NOT NULL DEFAULT 0,
                records_changed INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)"""
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
        clean = {field: str(values.get(field) or "").strip() for field in self.FIELDS[platform]}
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
        if platform=="tiktok":
            config=self.configuration(platform)
            try:
                self._post_form("https://open.tiktokapis.com/v2/oauth/revoke/",{
                    "client_key":config.get("client_key"),"client_secret":config.get("client_secret"),
                    "token":config.get("access_token")})
            except Exception as exc:
                raise RuntimeError(self.vault.redact(exc)) from None
        return self.disconnect(platform)

    def connection_status(self, platform: str) -> dict[str, Any]:
        platform = self._platform(platform)
        config = self.configuration(platform)
        missing = [field for field in self.FIELDS[platform] if not config.get(field)]
        sync = self.db.frame(
            "SELECT * FROM creator_title_sync_state WHERE platform=?", (platform,)
        )
        sync_row = sync.iloc[0].to_dict() if not sync.empty else {}
        return {
            "platform": platform,
            "configured": not missing,
            "missing": missing,
            "sync_status": sync_row.get("status") or "Never synced",
            "last_synced_at": sync_row.get("last_synced_at"),
            "last_error": sync_row.get("last_error") or config.get("last_error"),
            "credential_storage": "Operating-system credential vault",
        }

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

    def authorization_url(self, platform: str, state: str = "creator-intelligence") -> str:
        platform = self._platform(platform)
        config = self.configuration(platform)
        if platform == "instagram":
            params = {"client_id": config.get("app_id"), "redirect_uri": config.get("redirect_uri"),
                      "response_type": "code", "scope": "instagram_business_basic,instagram_business_manage_insights",
                      "state": state}
            base = "https://www.instagram.com/oauth/authorize"
        elif platform == "tiktok":
            params = {"client_key": config.get("client_key"), "redirect_uri": config.get("redirect_uri"),
                      "response_type": "code", "scope": "user.info.basic,video.list", "state": state}
            base = "https://www.tiktok.com/v2/auth/authorize/"
        else:
            raise ValueError("YouTube uses its API key setup for public channel synchronization.")
        if not all(params.values()):
            raise ValueError("Save the app credentials and redirect URI before starting OAuth.")
        return base + "?" + urlencode(params)

    def exchange_authorization_code(self, platform: str, code: str) -> dict[str, Any]:
        platform = self._platform(platform)
        config = self.configuration(platform)
        if platform == "instagram":
            payload = self._post_form("https://api.instagram.com/oauth/access_token", {
                "client_id": config.get("app_id"), "client_secret": config.get("app_secret"),
                "grant_type": "authorization_code", "redirect_uri": config.get("redirect_uri"), "code": code,
            })
            config["access_token"] = payload.get("access_token") or ""
            config["user_id"] = str(payload.get("user_id") or "")
        elif platform == "tiktok":
            payload = self._post_form("https://open.tiktokapis.com/v2/oauth/token/", {
                "client_key": config.get("client_key"), "client_secret": config.get("client_secret"),
                "code": code, "grant_type": "authorization_code", "redirect_uri": config.get("redirect_uri"),
            })
            config.update(access_token=payload.get("access_token") or "",
                          refresh_token=payload.get("refresh_token") or "",
                          user_id=payload.get("open_id") or config.get("user_id") or "")
        else:
            raise ValueError("Authorization-code exchange is not used for this YouTube setup.")
        self.save_configuration(platform, config, True)
        return {"connected": True, "expires_in": payload.get("expires_in")}

    def refresh_access_token(self, platform: str) -> dict[str, Any]:
        platform = self._platform(platform)
        config = self.configuration(platform)
        if platform == "instagram":
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
        config["access_token"] = payload.get("access_token") or config.get("access_token") or ""
        if payload.get("refresh_token"):
            config["refresh_token"] = payload["refresh_token"]
        self.save_configuration(platform, config, True)
        return {"refreshed": True, "expires_in": payload.get("expires_in")}

    def sync(self, platform: str, fetcher=None) -> dict[str, Any]:
        platform = self._platform(platform)
        now = datetime.now().isoformat()
        prior = self.connection_status(platform)
        if not prior["configured"]:
            raise ValueError("Complete the API setup before syncing.")
        cursor_frame = self.db.frame("SELECT last_cursor FROM creator_title_sync_state WHERE platform=?", (platform,))
        cursor = cursor_frame.iloc[0]["last_cursor"] if not cursor_frame.empty else None
        try:
            try:
                records = list((fetcher or self._fetch_records)(platform, cursor))
            except Exception as first_error:
                token_error = "401" in str(first_error) or "expired" in str(first_error).lower()
                if fetcher is not None or platform == "youtube" or not token_error:
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
            return {"platform": platform, "seen": len(records), "changed": changed,
                    "unchanged": len(records) - changed, "last_cursor": newest,
                    "outcomes_matched": outcomes["matched"],
                    "outcome_snapshots": outcomes["snapshots"]}
        except Exception as exc:
            safe=self.vault.redact(exc)
            self._record_sync(platform, "Failed", cursor, 0, 0, safe, now)
            raise RuntimeError(safe) from None

    def _upsert_record(self, platform: str, record: dict[str, Any]) -> int:
        from creator_intelligence.services.creator_dna import CreatorDNAService
        dna = CreatorDNAService(self.db)
        dna.ensure_event_history()
        source_id = str(record.get("source_video_id") or record.get("id") or "").strip()
        if not source_id:
            raise ValueError("Platform record is missing its source ID.")
        existing = self.db.frame(
            "SELECT * FROM creator_published_titles WHERE platform=? AND source_video_id=?",
            (platform, source_id),
        )
        title = str(record.get("title") or record.get("caption") or "Untitled post").strip()
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
                views=?,likes=?,comments=?,shares=?,reach=?,watch_time=?,duration_seconds=?,updated_at=?
                WHERE id=?""", (*values, now, int(existing.iloc[0]["id"])))
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
        params = {"part": "snippet", "channelId": config["channel_id"], "type": "video",
                  "order": "date", "maxResults": 50, "key": config["api_key"]}
        if cursor:
            params["publishedAfter"] = cursor
        snippets = {}
        while True:
            payload = self._json_request(Request(
                "https://www.googleapis.com/youtube/v3/search?" + urlencode(params)
            ))
            snippets.update({item["id"]["videoId"]: item.get("snippet", {})
                             for item in payload.get("items", [])})
            if not payload.get("nextPageToken"):
                break
            params["pageToken"] = payload["nextPageToken"]
        records = []
        ids = list(snippets)
        for offset in range(0, len(ids), 50):
            detail = self._json_request(Request(
                "https://www.googleapis.com/youtube/v3/videos?" + urlencode({
                    "part": "statistics,contentDetails", "id": ",".join(ids[offset:offset + 50]),
                    "key": config["api_key"],
                })
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
        return records

    def _fetch_instagram(self, cursor: str | None):
        config = self.configuration("instagram")
        url = f"https://graph.instagram.com/{config['account_id']}/media?" + urlencode({
            "fields": "id,caption,media_type,timestamp,like_count,comments_count",
            "limit": 100, "access_token": config["access_token"],
        })
        records = []
        while url:
            payload = self._json_request(Request(url))
            for item in payload.get("data", []):
                timestamp = item.get("timestamp")
                if cursor and timestamp and timestamp <= cursor:
                    continue
                insights = {}
                try:
                    insight_payload = self._json_request(Request(
                        f"https://graph.instagram.com/{item.get('id')}/insights?" + urlencode({
                            "metric": "views,reach,total_interactions", "access_token": config["access_token"]
                        })
                    ))
                    for metric in insight_payload.get("data", []):
                        values = metric.get("values") or []
                        insights[metric.get("name")] = values[0].get("value") if values else metric.get("value")
                except Exception:
                    # Basic media permissions still provide captions and engagement counts.
                    insights = {}
                records.append({"source_video_id": item.get("id"), "title": item.get("caption") or "Untitled post",
                                "content_type": str(item.get("media_type") or "post").lower(),
                                "published_at": timestamp, "views": insights.get("views"),
                                "reach": insights.get("reach"), "likes": item.get("like_count"),
                                "comments": item.get("comments_count")})
            url = (payload.get("paging") or {}).get("next")
        return records

    def _fetch_tiktok(self, cursor: str | None):
        config = self.configuration("tiktok")
        url = "https://open.tiktokapis.com/v2/video/list/?fields=id,title,video_description,duration,create_time,view_count,like_count,comment_count,share_count"
        body = {"max_count": 20}
        records = []
        while True:
            payload = self._json_request(Request(
                url, data=json.dumps(body).encode("utf-8"), method="POST",
                headers={"Authorization": f"Bearer {config['access_token']}", "Content-Type": "application/json"},
            ))
            data = payload.get("data") or {}
            for item in data.get("videos", []):
                published = datetime.fromtimestamp(int(item.get("create_time") or 0)).isoformat()
                if cursor and published <= cursor:
                    continue
                records.append({"source_video_id": item.get("id"),
                                "title": item.get("title") or item.get("video_description") or "Untitled video",
                                "content_type": "short", "published_at": published,
                                "duration_seconds": item.get("duration"), "views": item.get("view_count"),
                                "likes": item.get("like_count"), "comments": item.get("comment_count"),
                                "shares": item.get("share_count")})
            if not data.get("has_more"):
                break
            body["cursor"] = data.get("cursor")
        return records

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
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

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
