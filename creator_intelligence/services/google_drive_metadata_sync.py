from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from creator_intelligence.services.asset_management import AssetManagementService
from creator_intelligence.services.google_drive_sync import build_google_drive_sync_engine


@dataclass(frozen=True)
class MetadataSyncSummary:
    mapping_id: int
    scanned: int
    created: int
    updated: int
    missing: int
    folders: int
    retries: int
    cancelled: bool = False


class GoogleDriveMetadataSyncService:
    """Enumerates mapped Drive folders and reconciles files into managed assets."""

    def __init__(self, db, drive_service):
        self.db = db
        self.drive_service = drive_service
        self.assets = AssetManagementService(db)

    def sync_mapping(self, mapping_id: int) -> MetadataSyncSummary:
        mapping = self._mapping(mapping_id)
        started = _now()
        run_id = self.db.execute(
            "INSERT INTO google_drive_sync_runs(mapping_id,status,started_at) VALUES(?,?,?)",
            (mapping_id, "Running", started),
        )
        try:
            engine = build_google_drive_sync_engine(self.drive_service)
            result = engine.scan(
                str(mapping["drive_folder_id"]),
                recursive=bool(mapping["recursive"]),
            )
            seen: set[str] = set()
            created = updated = 0
            folder_names = {str(mapping["drive_folder_id"]): str(mapping["folder_name"])}
            for item in result.items:
                if item.is_folder:
                    folder_names[item.provider_id] = item.name
                    continue
                seen.add(item.provider_id)
                relative_path = self._relative_path(item, folder_names)
                if self._reconcile_file(mapping, item, relative_path):
                    created += 1
                else:
                    updated += 1
            missing = self._mark_missing(mapping_id, seen)
            finished = _now()
            self.db.execute(
                """UPDATE google_drive_sync_runs SET status=?,finished_at=?,files_scanned=?,
                folders_scanned=?,assets_created=?,assets_updated=?,assets_missing=?,retries=? WHERE id=?""",
                (
                    "Cancelled" if result.cancelled else "Completed",
                    finished,
                    len(seen),
                    result.scanned_folders,
                    created,
                    updated,
                    missing,
                    result.retries,
                    run_id,
                ),
            )
            self.db.execute(
                "UPDATE google_drive_folder_mappings SET last_validated_at=?,last_error=NULL,updated_at=? WHERE id=?",
                (finished, finished, mapping_id),
            )
            return MetadataSyncSummary(
                mapping_id, len(seen), created, updated, missing,
                result.scanned_folders, result.retries, result.cancelled,
            )
        except Exception as exc:
            finished = _now()
            self.db.execute(
                "UPDATE google_drive_sync_runs SET status='Failed',finished_at=?,error_message=? WHERE id=?",
                (finished, str(exc), run_id),
            )
            self.db.execute(
                "UPDATE google_drive_folder_mappings SET last_error=?,updated_at=? WHERE id=?",
                (str(exc), finished, mapping_id),
            )
            raise

    def sync_all(self) -> list[MetadataSyncSummary]:
        frame = self.db.frame(
            "SELECT id FROM google_drive_folder_mappings WHERE enabled=1 ORDER BY id"
        )
        return [self.sync_mapping(int(row["id"])) for _, row in frame.iterrows()]

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        frame = self.db.frame(
            """SELECT run.*, mapping.folder_name FROM google_drive_sync_runs run
            LEFT JOIN google_drive_folder_mappings mapping ON mapping.id=run.mapping_id
            ORDER BY run.started_at DESC LIMIT ?""",
            (max(1, min(limit, 100)),),
        )
        return frame.to_dict("records")

    def _mapping(self, mapping_id: int) -> dict[str, Any]:
        frame = self.db.frame(
            "SELECT * FROM google_drive_folder_mappings WHERE id=? AND enabled=1",
            (mapping_id,),
        )
        if frame.empty:
            raise ValueError("Enabled Drive folder mapping was not found.")
        return frame.iloc[0].to_dict()

    def _reconcile_file(self, mapping: dict[str, Any], item, relative_path: str) -> bool:
        raw = item.raw
        now = _now()
        existing = self.db.frame(
            "SELECT * FROM google_drive_files WHERE drive_file_id=?",
            (item.provider_id,),
        )
        owner = (raw.get("owners") or [{}])[0]
        size = _int_or_none(raw.get("size"))
        location = raw.get("webViewLink") or f"https://drive.google.com/open?id={item.provider_id}"
        asset_type = _asset_type(item.name, item.mime_type)
        asset_values = {
            "name": item.name,
            "asset_type": asset_type,
            "role": mapping.get("purpose"),
            "storage_provider": "Google Drive",
            "provider_key": item.provider_id,
            "location": location,
            "mime_type": item.mime_type,
            "extension": PurePosixPath(item.name).suffix.lower() or None,
            "size_bytes": size,
            "status": "Available",
            "last_verified_at": now,
            "notes": f"Drive path: {relative_path}",
        }
        created = existing.empty
        if created:
            asset_id = self.assets.create_asset(asset_values)
        else:
            row = existing.iloc[0].to_dict()
            asset_id = row.get("asset_id")
            if asset_id and self.assets.get_asset(str(asset_id)):
                self.assets.update_asset(str(asset_id), asset_values)
            else:
                asset_id = self.assets.create_asset(asset_values)
        params = (
            int(mapping["id"]), asset_id, item.parent_id, item.name, relative_path,
            item.mime_type, size, raw.get("md5Checksum"), raw.get("createdTime"),
            raw.get("modifiedTime"), location, owner.get("displayName"),
            owner.get("emailAddress"), 0, 1, now, now, json.dumps(raw, sort_keys=True),
            item.provider_id,
        )
        self.db.execute(
            """INSERT INTO google_drive_files(
                mapping_id,asset_id,parent_drive_id,name,relative_path,mime_type,size_bytes,
                md5_checksum,created_time,modified_time,web_view_link,owner_name,owner_email,
                trashed,available,first_seen_at,last_seen_at,raw_json,drive_file_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(drive_file_id) DO UPDATE SET
                mapping_id=excluded.mapping_id,asset_id=excluded.asset_id,
                parent_drive_id=excluded.parent_drive_id,name=excluded.name,
                relative_path=excluded.relative_path,mime_type=excluded.mime_type,
                size_bytes=excluded.size_bytes,md5_checksum=excluded.md5_checksum,
                created_time=excluded.created_time,modified_time=excluded.modified_time,
                web_view_link=excluded.web_view_link,owner_name=excluded.owner_name,
                owner_email=excluded.owner_email,trashed=0,available=1,
                last_seen_at=excluded.last_seen_at,raw_json=excluded.raw_json""",
            params,
        )
        return created

    def _mark_missing(self, mapping_id: int, seen: set[str]) -> int:
        rows = self.db.frame(
            "SELECT drive_file_id,asset_id FROM google_drive_files WHERE mapping_id=? AND available=1",
            (mapping_id,),
        ).to_dict("records")
        missing = [row for row in rows if row["drive_file_id"] not in seen]
        now = _now()
        for row in missing:
            self.db.execute(
                "UPDATE google_drive_files SET available=0,last_seen_at=? WHERE drive_file_id=?",
                (now, row["drive_file_id"]),
            )
            if row.get("asset_id"):
                self.assets.mark_verified(str(row["asset_id"]), available=False)
        return len(missing)

    @staticmethod
    def _relative_path(item, folder_names: dict[str, str]) -> str:
        parent = folder_names.get(str(item.parent_id), str(item.parent_id or ""))
        return f"{parent}/{item.name}" if parent else item.name


def _asset_type(name: str, mime_type: str | None) -> str:
    mime = (mime_type or "").lower()
    suffix = PurePosixPath(name).suffix.lower()
    if mime.startswith("video/") or suffix in {".mp4", ".mkv", ".mov", ".avi", ".webm"}:
        return "Video"
    if mime.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp", ".psd"}:
        return "Image"
    if mime.startswith("audio/") or suffix in {".mp3", ".wav", ".flac", ".aac"}:
        return "Audio"
    if suffix in {".srt", ".vtt", ".ass"}:
        return "Subtitle"
    if suffix in {".prproj", ".drp", ".aep"}:
        return "Project File"
    return "Other"


def _int_or_none(value: Any) -> int | None:
    return None if value in (None, "") else int(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
