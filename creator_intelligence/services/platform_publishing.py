from __future__ import annotations

import http.client
import json
import math
import mimetypes
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
INSTAGRAM_PUBLISH_SCOPE = "instagram_business_content_publish"
TIKTOK_PUBLISH_SCOPE = "video.publish"


@dataclass(frozen=True)
class PublishResult:
    platform: str
    state: str
    remote_upload_id: str | None = None
    platform_post_id: str | None = None
    url: str | None = None
    retryable: bool = False
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: dict[str, Any]


class _HttpTransport:
    """Small streaming HTTP transport; upload bodies are never loaded into RAM."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> HttpResponse:
        request_headers = dict(headers or {})
        data = None
        if payload is not None and form is not None:
            raise ValueError("Choose either a JSON payload or form values, not both.")
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json; charset=UTF-8")
        elif form is not None:
            data = urlencode({key: _form_value(value) for key, value in form.items()}).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        request = Request(url, data=data, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read()
                return HttpResponse(
                    int(response.status),
                    {str(key).lower(): str(value) for key, value in response.headers.items()},
                    _json_body(raw),
                )
        except HTTPError as exc:
            raw = exc.read()
            raise RuntimeError(_http_error(exc.code, raw)) from None

    def upload(
        self,
        method: str,
        url: str,
        path: Path,
        *,
        offset: int = 0,
        length: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        parts = urlsplit(url)
        if parts.scheme not in {"https", "http"} or not parts.hostname:
            raise ValueError("The provider returned an invalid upload address.")
        size = path.stat().st_size
        count = size - offset if length is None else length
        connection_type = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(parts.hostname, parts.port, timeout=120)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        request_headers = dict(headers or {})
        request_headers.setdefault("Content-Length", str(count))
        try:
            connection.putrequest(method, target)
            for key, value in request_headers.items():
                connection.putheader(str(key), str(value))
            connection.endheaders()
            with path.open("rb") as stream:
                stream.seek(offset)
                remaining = count
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise OSError("The source video ended before the upload completed.")
                    connection.send(chunk)
                    remaining -= len(chunk)
            response = connection.getresponse()
            raw = response.read()
            result = HttpResponse(
                int(response.status),
                {str(key).lower(): str(value) for key, value in response.getheaders()},
                _json_body(raw),
            )
            if result.status >= 400:
                raise RuntimeError(_http_error(result.status, raw))
            return result
        finally:
            connection.close()


class PlatformPublishingService:
    """Idempotent adapters for approved YouTube, TikTok, and Instagram posts.

    A durable dispatch row is written before media transfer. Re-running a dispatch
    reconciles its provider ID/session instead of creating another remote post.
    """

    def __init__(self, db, social_platforms, publishing_planner=None, transport=None):
        self.db = db
        self.social = social_platforms
        self.planner = publishing_planner
        self.transport = transport or _HttpTransport()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS platform_publication_dispatches(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publishing_item_id INTEGER NOT NULL UNIQUE,
                platform TEXT NOT NULL,
                source_path TEXT,
                state TEXT NOT NULL DEFAULT 'Pending',
                remote_upload_id TEXT,
                platform_post_id TEXT,
                upload_session_key TEXT,
                result_url TEXT,
                request_json TEXT NOT NULL DEFAULT '{}',
                last_error TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(publishing_item_id) REFERENCES publishing_items(id)
            )"""
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_platform_dispatch_state "
            "ON platform_publication_dispatches(state,platform)"
        )

    def dispatch(
        self,
        publishing_item_id: int,
        source_path: str | Path,
        *,
        metadata: dict[str, Any] | None = None,
        instagram_video_url: str | None = None,
    ) -> dict[str, Any]:
        existing = self.db.frame(
            "SELECT * FROM platform_publication_dispatches WHERE publishing_item_id=?",
            (int(publishing_item_id),),
        )
        if not existing.empty and existing.iloc[0].get("platform_post_id"):
            return self._result_from_row(existing.iloc[0].to_dict()).as_dict()
        item = self._publishing_item(publishing_item_id)
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        platform = _platform_key(item.get("platform"))
        request = dict(metadata or {})
        request.setdefault("title", str(item.get("title") or path.stem))
        if instagram_video_url:
            request["video_url"] = instagram_video_url
        self._start_dispatch(publishing_item_id, platform, path, request)
        saved = self._dispatch_row(publishing_item_id)
        if saved.get("platform_post_id"):
            return self._result_from_row(saved).as_dict()
        try:
            if platform == "youtube":
                result = self.publish_youtube(publishing_item_id, path, request)
            elif platform == "tiktok":
                result = self.publish_tiktok(publishing_item_id, path, request)
            elif platform == "instagram":
                result = self.publish_instagram(
                    publishing_item_id,
                    instagram_video_url or str(request.get("video_url") or ""),
                    request,
                )
            else:
                raise ValueError(f"Publishing is not supported for {item.get('platform') or platform}.")
            self._apply_result(publishing_item_id, result)
            return result.as_dict()
        except Exception as exc:
            self._fail(publishing_item_id, str(exc))
            raise

    def reconcile(self, publishing_item_id: int) -> dict[str, Any]:
        row = self._dispatch_row(publishing_item_id)
        if row.get("platform_post_id"):
            return self._result_from_row(row).as_dict()
        request = _json_object(row.get("request_json"))
        path = Path(str(row.get("source_path") or ""))
        platform = str(row.get("platform") or "")
        try:
            if platform == "youtube":
                result = self.publish_youtube(publishing_item_id, path, request)
            elif platform == "tiktok":
                result = self.publish_tiktok(publishing_item_id, path, request)
            elif platform == "instagram":
                result = self.publish_instagram(
                    publishing_item_id, str(request.get("video_url") or ""), request
                )
            else:
                raise ValueError(f"Unsupported publishing platform: {platform}")
            self._apply_result(publishing_item_id, result)
            return result.as_dict()
        except Exception as exc:
            self._fail(publishing_item_id, str(exc))
            raise

    def publish_youtube(
        self, publishing_item_id: int, source_path: Path, metadata: dict[str, Any]
    ) -> PublishResult:
        config = self._authorized("youtube", YOUTUBE_UPLOAD_SCOPE)
        if source_path.stat().st_size <= 0:
            raise ValueError("The source video is empty.")
        row = self._dispatch_row(publishing_item_id)
        upload_url = str(row.get("upload_url") or "")
        mime_type = mimetypes.guess_type(source_path.name)[0] or "video/mp4"
        size = source_path.stat().st_size
        if not upload_url:
            body = {
                "snippet": {
                    "title": str(metadata.get("title") or source_path.stem),
                    "description": str(metadata.get("description") or metadata.get("caption") or ""),
                    "tags": list(metadata.get("tags") or metadata.get("hashtags") or []),
                    "categoryId": str(metadata.get("category_id") or "20"),
                },
                "status": {
                    "privacyStatus": str(metadata.get("privacy_status") or "private"),
                    "selfDeclaredMadeForKids": bool(metadata.get("made_for_kids", False)),
                },
            }
            response = self.transport.request(
                "POST",
                "https://www.googleapis.com/upload/youtube/v3/videos?"
                + urlencode({"uploadType": "resumable", "part": "snippet,status"}),
                headers={
                    "Authorization": f"Bearer {config['access_token']}",
                    "X-Upload-Content-Length": str(size),
                    "X-Upload-Content-Type": mime_type,
                },
                payload=body,
            )
            upload_url = response.headers.get("location", "")
            if not upload_url:
                raise RuntimeError("YouTube did not return a resumable upload session.")
            self._save_remote(publishing_item_id, upload_url=upload_url, state="Uploading")
        offset = 0
        if row.get("upload_url"):
            probe = self.transport.upload(
                "PUT",
                upload_url,
                source_path,
                offset=size,
                length=0,
                headers={
                    "Authorization": f"Bearer {config['access_token']}",
                    "Content-Range": f"bytes */{size}",
                },
            )
            if probe.status in {200, 201} and probe.body.get("id"):
                return _youtube_result(probe.body)
            if probe.status == 308:
                offset = _next_offset(probe.headers.get("range"))
        headers = {
            "Authorization": f"Bearer {config['access_token']}",
            "Content-Type": mime_type,
        }
        if offset:
            headers["Content-Range"] = f"bytes {offset}-{size - 1}/{size}"
        response = self.transport.upload(
            "PUT", upload_url, source_path, offset=offset, headers=headers
        )
        if response.status == 308:
            return PublishResult(
                "youtube", "Uploading", retryable=True,
                detail="YouTube retained the resumable session; retry will continue it.",
            )
        if response.status not in {200, 201} or not response.body.get("id"):
            raise RuntimeError("YouTube accepted the transfer but did not return a video ID.")
        return _youtube_result(response.body)

    def publish_tiktok(
        self, publishing_item_id: int, source_path: Path, metadata: dict[str, Any]
    ) -> PublishResult:
        config = self._authorized("tiktok", TIKTOK_PUBLISH_SCOPE)
        if source_path.stat().st_size <= 0:
            raise ValueError("The source video is empty.")
        headers = {"Authorization": f"Bearer {config['access_token']}"}
        row = self._dispatch_row(publishing_item_id)
        publish_id = str(row.get("remote_upload_id") or "")
        if publish_id:
            current = self._tiktok_status(headers, publish_id)
            if str(row.get("state") or "") != "Uploading" or current.state == "Published":
                return current
        upload_url = str(row.get("upload_url") or "")
        if not publish_id:
            creator_body = self.transport.request(
                "POST",
                "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
                headers=headers,
                payload={},
            ).body
            _raise_tiktok_error(creator_body)
            creator = creator_body.get("data") or {}
            privacy = str(metadata.get("privacy_level") or "SELF_ONLY")
            allowed = set(creator.get("privacy_level_options") or [])
            if allowed and privacy not in allowed:
                raise ValueError(f"TikTok does not allow the selected privacy level: {privacy}.")
            size = source_path.stat().st_size
            chunk_size = min(10 * 1024 * 1024, size)
            count = max(1, math.ceil(size / max(1, chunk_size)))
            if count > 1000:
                raise ValueError("The source video needs more than TikTok's 1,000 upload chunks.")
            init = self.transport.request(
                "POST",
                "https://open.tiktokapis.com/v2/post/publish/video/init/",
                headers=headers,
                payload={
                    "post_info": {
                        "title": str(metadata.get("caption") or metadata.get("title") or "")[:2200],
                        "privacy_level": privacy,
                        "disable_duet": bool(metadata.get("disable_duet", False)),
                        "disable_comment": bool(metadata.get("disable_comment", False)),
                        "disable_stitch": bool(metadata.get("disable_stitch", False)),
                        "video_cover_timestamp_ms": int(metadata.get("cover_timestamp_ms") or 1000),
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": size,
                        "chunk_size": chunk_size,
                        "total_chunk_count": count,
                    },
                },
            ).body
            _raise_tiktok_error(init)
            data = init.get("data") or {}
            publish_id = str(data.get("publish_id") or "")
            upload_url = str(data.get("upload_url") or "")
            if not publish_id or not upload_url:
                raise RuntimeError("TikTok did not return an upload session.")
            self._save_remote(
                publishing_item_id,
                remote_upload_id=publish_id,
                upload_url=upload_url,
                state="Uploading",
            )
        size = source_path.stat().st_size
        chunk_size = min(10 * 1024 * 1024, size)
        for offset in range(0, size, max(1, chunk_size)):
            length = min(chunk_size, size - offset)
            self.transport.upload(
                "PUT",
                upload_url,
                source_path,
                offset=offset,
                length=length,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes {offset}-{offset + length - 1}/{size}",
                },
            )
        self._save_remote(publishing_item_id, state="Processing")
        return self._tiktok_status(headers, publish_id)

    def publish_instagram(
        self, publishing_item_id: int, video_url: str, metadata: dict[str, Any]
    ) -> PublishResult:
        config = self._authorized("instagram", INSTAGRAM_PUBLISH_SCOPE)
        if not video_url.startswith("https://"):
            raise ValueError(
                "Instagram publishing needs a public HTTPS video URL. "
                "Configure an upload/staging URL before dispatching this local file."
            )
        row = self._dispatch_row(publishing_item_id)
        container_id = str(row.get("remote_upload_id") or "")
        base = "https://graph.instagram.com/v24.0"
        if not container_id:
            created = self.transport.request(
                "POST",
                f"{base}/{config['account_id']}/media",
                headers={"Authorization": f"Bearer {config['access_token']}"},
                form={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": str(metadata.get("caption") or metadata.get("description") or ""),
                    "share_to_feed": bool(metadata.get("share_to_feed", True)),
                },
            ).body
            container_id = str(created.get("id") or "")
            if not container_id:
                raise RuntimeError("Instagram did not return a Reel container ID.")
            self._save_remote(
                publishing_item_id,
                remote_upload_id=container_id,
                state="Processing",
            )
        status = self.transport.request(
            "GET",
            f"{base}/{container_id}?" + urlencode({"fields": "status_code"}),
            headers={"Authorization": f"Bearer {config['access_token']}"},
        ).body
        code = str(status.get("status_code") or "").upper()
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram Reel processing ended with {code}.")
        if code != "FINISHED":
            return PublishResult(
                "instagram", "Processing", remote_upload_id=container_id,
                retryable=True, detail="Instagram is still processing the Reel container.",
            )
        published = self.transport.request(
            "POST",
            f"{base}/{config['account_id']}/media_publish",
            headers={"Authorization": f"Bearer {config['access_token']}"},
            form={"creation_id": container_id},
        ).body
        post_id = str(published.get("id") or "")
        if not post_id:
            raise RuntimeError("Instagram did not return a published media ID.")
        self._save_remote(
            publishing_item_id,
            state="Published",
            remote_upload_id=container_id,
            platform_post_id=post_id,
        )
        try:
            media = self.transport.request(
                "GET",
                f"{base}/{post_id}?" + urlencode({"fields": "id,permalink"}),
                headers={"Authorization": f"Bearer {config['access_token']}"},
            ).body
        except Exception:
            media = {}
        return PublishResult(
            "instagram", "Published", remote_upload_id=container_id,
            platform_post_id=post_id, url=str(media.get("permalink") or "") or None,
        )

    def _tiktok_status(self, headers: dict[str, str], publish_id: str) -> PublishResult:
        response = self.transport.request(
            "POST",
            "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
            headers=headers,
            payload={"publish_id": publish_id},
        ).body
        _raise_tiktok_error(response)
        data = response.get("data") or {}
        status = str(data.get("status") or "").upper()
        post_ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
        if status in {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"}:
            post_id = str(post_ids[0]) if post_ids else None
            return PublishResult(
                "tiktok", "Published", remote_upload_id=publish_id,
                platform_post_id=post_id,
                url=f"https://www.tiktok.com/@me/video/{post_id}" if post_id else None,
            )
        if status in {"FAILED", "PUBLISH_FAILED"}:
            raise RuntimeError(
                "TikTok publishing failed: " + str(data.get("fail_reason") or "unknown reason")
            )
        return PublishResult(
            "tiktok", "Processing" if status else "Uploading",
            remote_upload_id=publish_id, retryable=True,
            detail=f"TikTok status: {status or 'pending upload'}.",
        )

    def _authorized(self, platform: str, required_scope: str) -> dict[str, Any]:
        config = self.social.configuration(platform)
        if not config.get("access_token"):
            raise ValueError(f"Connect {platform.title()} before publishing.")
        scopes = set(self.social._scope_values(config.get("granted_scopes")))
        if required_scope not in scopes:
            raise ValueError(
                f"Reconnect {platform.title()} and approve the {required_scope} permission."
            )
        if self.social._token_expired(config.get("token_expires_at")):
            self.social.refresh_access_token(platform)
            config = self.social.configuration(platform)
        return config

    def _publishing_item(self, item_id: int) -> dict[str, Any]:
        frame = self.db.frame("SELECT * FROM publishing_items WHERE id=?", (int(item_id),))
        if frame.empty:
            raise KeyError(item_id)
        item = frame.iloc[0].to_dict()
        if str(item.get("status") or "") not in {"Ready", "Planned", "Scheduled"}:
            raise ValueError("Only approved, ready, or scheduled items can be published.")
        return item

    def _start_dispatch(
        self, item_id: int, platform: str, path: Path, request: dict[str, Any]
    ) -> None:
        existing = self.db.frame(
            "SELECT platform,platform_post_id FROM platform_publication_dispatches "
            "WHERE publishing_item_id=?", (int(item_id),)
        )
        if not existing.empty:
            saved_platform = str(existing.iloc[0]["platform"])
            if saved_platform != platform:
                raise ValueError("This publishing item already has a dispatch for another platform.")
            if existing.iloc[0]["platform_post_id"]:
                return
        now = _now()
        self.db.execute(
            """INSERT INTO platform_publication_dispatches(
                publishing_item_id,platform,source_path,state,request_json,
                attempt_count,created_at,updated_at
            ) VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(publishing_item_id) DO UPDATE SET
                source_path=excluded.source_path,request_json=excluded.request_json,
                attempt_count=platform_publication_dispatches.attempt_count+1,
                last_error=NULL,updated_at=excluded.updated_at""",
            (int(item_id), platform, str(path), "Pending", json.dumps(request), now, now),
        )

    def _dispatch_row(self, item_id: int) -> dict[str, Any]:
        frame = self.db.frame(
            "SELECT * FROM platform_publication_dispatches WHERE publishing_item_id=?",
            (int(item_id),),
        )
        if frame.empty:
            raise KeyError(f"No platform dispatch exists for publishing item {item_id}.")
        row = frame.iloc[0].to_dict()
        session_key = str(row.get("upload_session_key") or "")
        row["upload_url"] = (
            self.social.vault.load("generic").get(session_key, "") if session_key else ""
        )
        return row

    def _save_remote(self, item_id: int, **changes: Any) -> None:
        upload_url = changes.pop("upload_url", None)
        if upload_url:
            session_key = f"publishing_upload_session_{int(item_id)}"
            self.social.vault.save("generic", {session_key: upload_url})
            changes["upload_session_key"] = session_key
        allowed = {
            "state", "remote_upload_id", "platform_post_id",
            "upload_session_key", "result_url", "last_error",
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        values["updated_at"] = _now()
        self.db.execute(
            "UPDATE platform_publication_dispatches SET "
            + ",".join(f"{key}=?" for key in values)
            + " WHERE publishing_item_id=?",
            [*values.values(), int(item_id)],
        )

    def _apply_result(self, item_id: int, result: PublishResult) -> None:
        self._save_remote(
            item_id,
            state=result.state,
            remote_upload_id=result.remote_upload_id,
            platform_post_id=result.platform_post_id,
            result_url=result.url,
            last_error=None,
        )
        if result.state == "Published":
            self._clear_upload_session(item_id)
        if self.planner is None:
            return
        if result.state == "Published":
            self.planner.update_item(
                item_id,
                status="Published",
                upload_status="Published",
                external_url=result.url,
            )
        else:
            self.planner.update_item(item_id, upload_status=result.state)

    def _fail(self, item_id: int, error: str) -> None:
        safe = self.social.vault.redact(error)
        self._save_remote(item_id, state="Failed", last_error=safe)
        if self.planner is not None:
            self.planner.update_item(item_id, upload_status="Failed")

    def _clear_upload_session(self, item_id: int) -> None:
        key = f"publishing_upload_session_{int(item_id)}"
        values = self.social.vault.load("generic")
        if key in values:
            values.pop(key, None)
            self.social.vault.replace("generic", values)
        self.db.execute(
            "UPDATE platform_publication_dispatches SET upload_session_key=NULL,updated_at=? "
            "WHERE publishing_item_id=?",
            (_now(), int(item_id)),
        )

    @staticmethod
    def _result_from_row(row: dict[str, Any]) -> PublishResult:
        return PublishResult(
            str(row.get("platform") or ""),
            "Published" if row.get("platform_post_id") else str(row.get("state") or "Pending"),
            str(row.get("remote_upload_id") or "") or None,
            str(row.get("platform_post_id") or "") or None,
            str(row.get("result_url") or "") or None,
            False,
        )


def _youtube_result(body: dict[str, Any]) -> PublishResult:
    video_id = str(body.get("id") or "")
    return PublishResult(
        "youtube", "Published", platform_post_id=video_id,
        url=f"https://youtu.be/{video_id}",
    )


def _platform_key(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"youtube", "youtube shorts"}:
        return "youtube"
    if normalized in {"instagram", "instagram reels"}:
        return "instagram"
    if normalized == "tiktok":
        return "tiktok"
    return normalized


def _next_offset(range_value: str | None) -> int:
    if not range_value or "-" not in range_value:
        return 0
    try:
        return int(range_value.rsplit("-", 1)[1]) + 1
    except (TypeError, ValueError):
        return 0


def _json_body(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"raw": raw.decode("utf-8", errors="replace")[:1000]}
    return value if isinstance(value, dict) else {"data": value}


def _json_object(value: Any) -> dict[str, Any]:
    try:
        result = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _http_error(status: int, raw: bytes) -> str:
    body = _json_body(raw)
    detail = body.get("error") or body.get("message") or body.get("raw") or "request failed"
    return f"Provider request failed ({status}): {detail}"


def _form_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _raise_tiktok_error(body: dict[str, Any]) -> None:
    error = body.get("error") or {}
    code = str(error.get("code") or "ok").lower()
    if code not in {"ok", "0"}:
        raise RuntimeError(
            "TikTok request failed: " + str(error.get("message") or code)
        )


def _now() -> str:
    return datetime.now().isoformat()
