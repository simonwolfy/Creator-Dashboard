from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from creator_intelligence.services.creator_dna import CreatorDNAService
from creator_intelligence.services.folder_watcher import FolderWatcherService
from creator_intelligence.services.video_metadata import VideoMetadataService

VIDEO_EXTENSIONS = "mp4,mov,m4v,webm,avi,mkv"
INTAKE_STATES = (
    "Needs review",
    "Ready",
    "Scheduled",
    "Published",
    "Rejected",
    "Missing",
)


class EditedContentIntakeService:
    """Turn safe watched-folder assets into reviewable publishing drafts."""

    def __init__(
        self,
        db,
        publishing_service,
        folder_watcher: FolderWatcherService | None = None,
        metadata_service: VideoMetadataService | None = None,
    ):
        self.db = db
        self.publishing = publishing_service
        self.folders = folder_watcher or FolderWatcherService(db)
        self.metadata = metadata_service or VideoMetadataService(db)
        self.dna = CreatorDNAService(db)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        for statement in (
            """CREATE TABLE IF NOT EXISTS edited_content_sources(
                folder_id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                FOREIGN KEY(folder_id) REFERENCES watched_folders(id) ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS edited_content_intake(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT NOT NULL UNIQUE,
                source_folder_id INTEGER,
                publishing_item_id INTEGER UNIQUE,
                title TEXT NOT NULL,
                description TEXT,
                platform TEXT NOT NULL DEFAULT 'Multi-platform',
                content_type TEXT NOT NULL DEFAULT 'Short',
                state TEXT NOT NULL DEFAULT 'Needs review',
                learning_status TEXT NOT NULL DEFAULT 'Neutral',
                planned_publish_at TEXT,
                source_platform TEXT,
                source_content_id TEXT,
                sidecar_path TEXT,
                sidecar_json TEXT NOT NULL DEFAULT '{}',
                approved_at TEXT,
                scheduled_at TEXT,
                published_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(asset_id) REFERENCES managed_assets(id) ON DELETE CASCADE,
                FOREIGN KEY(source_folder_id) REFERENCES watched_folders(id) ON DELETE SET NULL,
                FOREIGN KEY(publishing_item_id) REFERENCES publishing_items(id) ON DELETE SET NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_edited_content_state
               ON edited_content_intake(state,planned_publish_at)""",
            """CREATE INDEX IF NOT EXISTS idx_edited_content_source
               ON edited_content_intake(source_platform,source_content_id)""",
        ):
            self.db.execute(statement)

    def add_folder(self, path: str, *, recursive: bool = True) -> int:
        normalized = str(Path(path).expanduser().resolve())
        existing = self.db.frame(
            "SELECT id FROM watched_folders WHERE path=?", (normalized,)
        )
        if existing.empty:
            folder_id = self.folders.add_folder(
                normalized,
                name=f"Ready to publish - {Path(normalized).name}",
                recursive=recursive,
                include_extensions=VIDEO_EXTENSIONS,
                calculate_checksums=True,
                asset_role="Final export",
            )
        else:
            folder_id = int(existing.iloc[0]["id"])
            self.db.execute(
                """UPDATE watched_folders SET enabled=1,calculate_checksums=1,
                   asset_role='Final export',updated_at=? WHERE id=?""",
                (_now(), folder_id),
            )
        self.db.execute(
            "INSERT OR IGNORE INTO edited_content_sources(folder_id,created_at) VALUES(?,?)",
            (folder_id, _now()),
        )
        return folder_id

    def source_folders(self) -> list[dict[str, Any]]:
        return self.db.frame(
            """SELECT folder.* FROM edited_content_sources source
               JOIN watched_folders folder ON folder.id=source.folder_id
               ORDER BY folder.name"""
        ).to_dict("records")

    def scan_folder(self, folder_id: int, *, probe_metadata: bool = True) -> dict[str, Any]:
        summary = self.folders.scan_folder(int(folder_id))
        synced = self._sync_folder(int(folder_id), probe_metadata=probe_metadata)
        return {
            **self.folders.summary_dict(summary),
            **synced,
        }

    def scan_all(self, *, probe_metadata: bool = True) -> dict[str, int]:
        totals = {
            "folders": 0,
            "discovered": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "missing": 0,
            "errors": 0,
            "intake_created": 0,
            "duplicates": 0,
        }
        for folder in self.source_folders():
            if not int(folder.get("enabled") or 0):
                continue
            result = self.scan_folder(int(folder["id"]), probe_metadata=probe_metadata)
            totals["folders"] += 1
            for key in totals:
                if key != "folders":
                    totals[key] += int(result.get(key) or 0)
        return totals

    def _sync_folder(self, folder_id: int, *, probe_metadata: bool) -> dict[str, int]:
        assets = self.db.frame(
            """SELECT asset.* FROM watched_folder_assets tracked
               JOIN managed_assets asset ON asset.id=tracked.asset_id
               WHERE tracked.folder_id=? AND asset.asset_type='Video'
               ORDER BY asset.created_at""",
            (folder_id,),
        ).to_dict("records")
        created = duplicates = 0
        for asset in assets:
            asset_id = str(asset["id"])
            existing = self.db.frame(
                "SELECT id FROM edited_content_intake WHERE asset_id=?", (asset_id,)
            )
            if not existing.empty:
                continue
            checksum = str(asset.get("checksum_sha256") or "").strip()
            if checksum and self._checksum_is_queued(checksum, asset_id):
                duplicates += 1
                continue
            self._create_intake(asset, folder_id, probe_metadata=probe_metadata)
            created += 1
        return {"intake_created": created, "duplicates": duplicates}

    def _checksum_is_queued(self, checksum: str, asset_id: str) -> bool:
        matches = self.db.frame(
            """SELECT intake.id FROM edited_content_intake intake
               JOIN managed_assets asset ON asset.id=intake.asset_id
               WHERE asset.checksum_sha256=? AND intake.asset_id<>? LIMIT 1""",
            (checksum, asset_id),
        )
        return not matches.empty

    def _create_intake(
        self, asset: dict[str, Any], folder_id: int, *, probe_metadata: bool
    ) -> int:
        asset_id = str(asset["id"])
        path = Path(str(asset.get("location") or ""))
        sidecar, sidecar_path = self._sidecar(path)
        technical = self.metadata.metadata(asset_id) or {}
        if probe_metadata and self.metadata.tool_status()["available"]:
            probed = self.metadata.probe_asset(asset_id)
            if probed.get("probe_status") == "Complete":
                technical = probed
        title = str(sidecar.get("title") or self._title_from_path(path)).strip()
        description = _optional_text(sidecar.get("description"))
        platform = self._platform(sidecar.get("platform"))
        content_type = str(
            sidecar.get("content_type") or self._content_type(technical)
        ).strip()
        planned = _optional_text(sidecar.get("planned_publish_at"))
        publishing_id = int(
            self.publishing.create_item(
                {
                    "title": title,
                    "platform": platform,
                    "content_type": content_type,
                    "status": "Draft",
                    "planned_publish_at": None,
                    "score": 0,
                    "confidence": 0,
                    "rationale": "Detected in a Ready to Publish folder; creator review is required.",
                    "description_status": "Ready" if description else "Missing",
                    "thumbnail_status": "Missing",
                    "metadata_status": "Ready" if sidecar else "Missing",
                    "upload_status": "Local file ready",
                    "notes": f"Edited content asset: {asset_id}",
                }
            )
        )
        now = _now()
        intake_id = int(
            self.db.execute(
                """INSERT INTO edited_content_intake(
                    asset_id,source_folder_id,publishing_item_id,title,description,
                    platform,content_type,state,learning_status,planned_publish_at,
                    sidecar_path,sidecar_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    asset_id,
                    folder_id,
                    publishing_id,
                    title,
                    description,
                    platform,
                    content_type,
                    "Needs review",
                    "Neutral",
                    planned,
                    str(sidecar_path) if sidecar_path else None,
                    json.dumps(sidecar, sort_keys=True),
                    now,
                    now,
                ),
            )
        )
        self.dna.record_event(
            "edited_content_imported",
            subject_type="edited_content",
            subject_id=intake_id,
            platform=platform,
            evidence_polarity="neutral",
            evidence_weight=0,
            field_name="title",
            new_value=title,
            metadata={"asset_id": asset_id, "path": str(path)},
            source="edited_content_intake",
            event_key=f"edited-content:{intake_id}:imported",
        )
        return intake_id

    def items(self, state: str | None = None):
        self._reconcile_publishing_states()
        clauses: list[str] = []
        params: list[Any] = []
        if state and state != "All":
            clauses.append("intake.state=?")
            params.append(state)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        frame = self.db.frame(
            f"""SELECT intake.id,intake.title,intake.description,intake.platform,
                intake.content_type,intake.state,intake.learning_status,
                intake.planned_publish_at,publishing.status AS publishing_status,
                asset.name AS file_name,asset.location,asset.size_bytes,
                asset.status AS file_status,metadata.duration_seconds,
                metadata.width,metadata.height,metadata.video_codec,
                intake.source_platform,intake.source_content_id,
                intake.sidecar_path,intake.publishing_item_id,intake.asset_id,
                intake.updated_at
                FROM edited_content_intake intake
                JOIN managed_assets asset ON asset.id=intake.asset_id
                LEFT JOIN publishing_items publishing ON publishing.id=intake.publishing_item_id
                LEFT JOIN video_asset_metadata metadata ON metadata.managed_asset_id=intake.asset_id
                {where}
                ORDER BY CASE intake.state
                    WHEN 'Needs review' THEN 1 WHEN 'Ready' THEN 2
                    WHEN 'Scheduled' THEN 3 WHEN 'Missing' THEN 4 ELSE 5 END,
                    COALESCE(intake.planned_publish_at,'9999-12-31'),intake.created_at""",
            params,
        )
        return frame

    def item(self, intake_id: int) -> dict[str, Any]:
        frame = self.db.frame(
            "SELECT * FROM edited_content_intake WHERE id=?", (int(intake_id),)
        )
        if frame.empty:
            raise KeyError(intake_id)
        return frame.iloc[0].to_dict()

    def update_item(self, intake_id: int, **changes) -> dict[str, Any]:
        allowed = {"title", "description", "platform", "content_type", "planned_publish_at"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if not values:
            return self.item(intake_id)
        old = self.item(intake_id)
        values["updated_at"] = _now()
        columns = list(values)
        self.db.execute(
            "UPDATE edited_content_intake SET "
            + ",".join(f"{column}=?" for column in columns)
            + " WHERE id=?",
            [values[column] for column in columns] + [int(intake_id)],
        )
        publishing_changes = {
            key: values[key]
            for key in ("title", "platform", "content_type", "planned_publish_at")
            if key in values
        }
        if "description" in values:
            publishing_changes["description_status"] = (
                "Ready" if _optional_text(values["description"]) else "Missing"
            )
        if publishing_changes and old.get("publishing_item_id") is not None:
            self.publishing.update_item(int(old["publishing_item_id"]), **publishing_changes)
        for field, event_type in (("title", "title_edited"), ("description", "caption_edited")):
            if field in values and str(values[field] or "") != str(old.get(field) or ""):
                self.dna.record_event(
                    event_type,
                    subject_type="edited_content",
                    subject_id=intake_id,
                    platform=str(values.get("platform") or old.get("platform") or ""),
                    evidence_polarity="neutral",
                    evidence_weight=1,
                    field_name=field,
                    old_value=old.get(field),
                    new_value=values[field],
                    source="edited_content_intake",
                )
        return self.item(intake_id)

    def approve(self, intake_id: int) -> dict[str, Any]:
        item = self.item(intake_id)
        now = _now()
        self.db.execute(
            """UPDATE edited_content_intake SET state='Ready',learning_status='Approved',
               approved_at=COALESCE(approved_at,?),updated_at=? WHERE id=?""",
            (now, now, int(intake_id)),
        )
        if item.get("publishing_item_id") is not None:
            self.publishing.update_item(
                int(item["publishing_item_id"]),
                status="Ready",
                metadata_status="Ready",
                description_status="Ready" if _optional_text(item.get("description")) else "Missing",
            )
        self.dna.record_event(
            "edited_content_approved",
            subject_type="edited_content",
            subject_id=intake_id,
            platform=str(item.get("platform") or ""),
            evidence_polarity="positive",
            evidence_weight=1,
            field_name="title",
            new_value=item.get("title"),
            metadata={"content_type": item.get("content_type")},
            source="edited_content_intake",
            event_key=f"edited-content:{intake_id}:approved",
        )
        return self.item(intake_id)

    def schedule(self, intake_id: int, publish_at: str | None = None) -> dict[str, Any]:
        item = self.approve(intake_id)
        requested_at = publish_at or _optional_text(item.get("planned_publish_at"))
        if requested_at:
            scheduled = datetime.fromisoformat(str(requested_at))
        else:
            scheduled = self.publishing.suggest_next_slot(
                str(item.get("platform") or "Multi-platform"),
                str(item.get("content_type") or "Short"),
            )
            occupied = set(
                self.publishing.items()["planned_publish_at"]
                .dropna()
                .astype(str)
                .tolist()
            )
            while scheduled.isoformat() in occupied:
                scheduled = self.publishing.suggest_next_slot(
                    str(item.get("platform") or "Multi-platform"),
                    str(item.get("content_type") or "Short"),
                    scheduled.replace(microsecond=0),
                )
        scheduled_at = scheduled.isoformat()
        now = _now()
        self.db.execute(
            """UPDATE edited_content_intake SET state='Scheduled',planned_publish_at=?,
               scheduled_at=?,updated_at=? WHERE id=?""",
            (scheduled_at, now, now, int(intake_id)),
        )
        if item.get("publishing_item_id") is not None:
            self.publishing.update_item(
                int(item["publishing_item_id"]),
                status="Planned",
                planned_publish_at=scheduled_at,
            )
        self.dna.record_event(
            "edited_content_scheduled",
            subject_type="edited_content",
            subject_id=intake_id,
            platform=str(item.get("platform") or ""),
            evidence_polarity="neutral",
            evidence_weight=0,
            field_name="planned_publish_at",
            new_value=scheduled_at,
            source="edited_content_intake",
            event_key=f"edited-content:{intake_id}:scheduled:{scheduled_at}",
        )
        return self.item(intake_id)

    def reject(self, intake_id: int) -> dict[str, Any]:
        item = self.item(intake_id)
        self.db.execute(
            """UPDATE edited_content_intake SET state='Rejected',learning_status='Negative',
               updated_at=? WHERE id=?""",
            (_now(), int(intake_id)),
        )
        if item.get("publishing_item_id") is not None:
            self.publishing.update_item(int(item["publishing_item_id"]), status="Skipped")
        self.dna.record_event(
            "edited_content_rejected",
            subject_type="edited_content",
            subject_id=intake_id,
            platform=str(item.get("platform") or ""),
            evidence_polarity="negative",
            evidence_weight=2,
            field_name="title",
            new_value=item.get("title"),
            source="edited_content_intake",
            event_key=f"edited-content:{intake_id}:rejected",
        )
        return self.item(intake_id)

    def connect_published_content(self, intake_id: int, source_content_id: str) -> dict[str, Any]:
        if not self._table_exists("creator_published_titles"):
            raise ValueError("Sync the platform before connecting published content.")
        match = self.db.frame(
            """SELECT * FROM creator_published_titles
               WHERE source_video_id=? ORDER BY updated_at DESC LIMIT 1""",
            (str(source_content_id).strip(),),
        )
        if match.empty:
            raise ValueError("That published content ID was not found. Sync the platform and try again.")
        published = match.iloc[0].to_dict()
        item = self.item(intake_id)
        platform = str(published.get("platform") or item.get("platform") or "")
        published_at = _optional_text(published.get("published_at")) or _now()
        has_metrics = any(float(published.get(key) or 0) > 0 for key in ("views", "likes", "comments", "shares", "watch_time"))
        now = _now()
        self.db.execute(
            """UPDATE edited_content_intake SET state='Published',learning_status=?,
               source_platform=?,source_content_id=?,published_at=?,updated_at=? WHERE id=?""",
            (
                "Measured" if has_metrics else "Published",
                platform,
                str(source_content_id).strip(),
                published_at,
                now,
                int(intake_id),
            ),
        )
        if item.get("publishing_item_id") is not None:
            self.publishing.update_item(
                int(item["publishing_item_id"]),
                status="Published",
                actual_publish_at=published_at,
            )
        self.dna.record_event(
            "edited_content_published",
            subject_type="edited_content",
            subject_id=intake_id,
            platform=platform,
            evidence_polarity="positive",
            evidence_weight=2,
            field_name="title",
            new_value=published.get("title") or item.get("title"),
            source="edited_content_intake",
            event_key=f"edited-content:{intake_id}:published",
        )
        self.dna.record_event(
            "edited_content_outcome_connected",
            subject_type="edited_content",
            subject_id=intake_id,
            platform=platform,
            evidence_polarity="neutral",
            evidence_weight=1 if has_metrics else 0,
            new_value=published.get("title"),
            metadata={
                key: published.get(key)
                for key in ("views", "likes", "comments", "shares", "reach", "watch_time")
            },
            source="edited_content_intake",
            event_key=f"edited-content:{intake_id}:published:{source_content_id}",
        )
        return self.item(intake_id)

    def _reconcile_publishing_states(self) -> None:
        rows = self.db.frame(
            """SELECT intake.id,intake.state,intake.learning_status,intake.platform,
                      intake.title,intake.publishing_item_id,publishing.status,
                      publishing.planned_publish_at,publishing.actual_publish_at,
                      asset.status AS asset_status
               FROM edited_content_intake intake
               JOIN managed_assets asset ON asset.id=intake.asset_id
               LEFT JOIN publishing_items publishing ON publishing.id=intake.publishing_item_id"""
        ).to_dict("records")
        for row in rows:
            intake_id = int(row["id"])
            if str(row.get("asset_status")) == "Missing" and row.get("state") != "Published":
                self.db.execute(
                    "UPDATE edited_content_intake SET state='Missing',updated_at=? WHERE id=?",
                    (_now(), intake_id),
                )
                continue
            status = str(row.get("status") or "")
            if row.get("state") == "Missing" and str(row.get("asset_status")) == "Available":
                restored = {
                    "Published": "Published",
                    "Planned": "Scheduled",
                    "Scheduled": "Scheduled",
                    "Ready": "Ready",
                }.get(status, "Needs review")
                self.db.execute(
                    "UPDATE edited_content_intake SET state=?,updated_at=? WHERE id=?",
                    (restored, _now(), intake_id),
                )
                row["state"] = restored
            if status == "Published" and row.get("state") != "Published":
                published_at = _optional_text(row.get("actual_publish_at")) or _now()
                self.db.execute(
                    """UPDATE edited_content_intake SET state='Published',learning_status='Published',
                       published_at=?,updated_at=? WHERE id=?""",
                    (published_at, _now(), intake_id),
                )
                self.dna.record_event(
                    "edited_content_published",
                    subject_type="edited_content",
                    subject_id=intake_id,
                    platform=str(row.get("platform") or ""),
                    evidence_polarity="positive",
                    evidence_weight=2,
                    field_name="title",
                    new_value=row.get("title"),
                    source="edited_content_intake",
                    event_key=f"edited-content:{intake_id}:published",
                )
            elif status in {"Planned", "Scheduled"} and row.get("state") not in {"Published", "Rejected"}:
                self.db.execute(
                    """UPDATE edited_content_intake SET state='Scheduled',planned_publish_at=?,
                       updated_at=? WHERE id=?""",
                    (row.get("planned_publish_at"), _now(), intake_id),
                )

    def _table_exists(self, name: str) -> bool:
        frame = self.db.frame(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return not frame.empty

    @staticmethod
    def _sidecar(path: Path) -> tuple[dict[str, Any], Path | None]:
        json_path = path.with_suffix(".json")
        if json_path.is_file():
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
                if isinstance(payload, dict):
                    return payload, json_path
            except (OSError, ValueError):
                return {"sidecar_error": "The JSON sidecar could not be read."}, json_path
        text_path = path.with_suffix(".txt")
        if text_path.is_file():
            try:
                lines = [line.strip() for line in text_path.read_text(encoding="utf-8-sig").splitlines()]
                lines = [line for line in lines if line]
                if lines:
                    return {
                        "title": lines[0],
                        "description": "\n".join(lines[1:]) or None,
                    }, text_path
            except OSError:
                return {"sidecar_error": "The text sidecar could not be read."}, text_path
        return {}, None

    @staticmethod
    def _title_from_path(path: Path) -> str:
        title = re.sub(r"[_-]+", " ", path.stem).strip()
        title = re.sub(r"\s+", " ", title)
        return title or "Untitled edited video"

    @staticmethod
    def _platform(value: Any) -> str:
        text = str(value or "Multi-platform").strip().lower()
        aliases = {
            "youtube": "YouTube",
            "youtube shorts": "YouTube Shorts",
            "shorts": "YouTube Shorts",
            "tiktok": "TikTok",
            "twitch": "Twitch",
            "instagram": "Instagram",
            "multi-platform": "Multi-platform",
            "multiplatform": "Multi-platform",
        }
        return aliases.get(text, "Multi-platform")

    @staticmethod
    def _content_type(metadata: dict[str, Any]) -> str:
        width = int(metadata.get("width") or 0)
        height = int(metadata.get("height") or 0)
        duration = float(metadata.get("duration_seconds") or 0)
        if height > width and (not duration or duration <= 180):
            return "Short"
        return "Long-form"


def _now() -> str:
    return datetime.now().isoformat()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
