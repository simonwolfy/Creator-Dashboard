from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class GoogleDriveFolderMappingService:
    PURPOSES = ("Raw Recordings", "Exports", "Thumbnails", "Project Files", "Subtitles", "Other")

    def __init__(self, db, drive_service):
        self.db = db
        self.drive_service = drive_service

    def browse_folders(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        """Return all visible folders directly beneath a Drive parent.

        ``None`` means My Drive root. Results are fully paginated and sorted
        locally so the live browser remains deterministic across API pages.
        """
        credentials = self.drive_service._load_credentials()
        drive = self.drive_service.drive_factory(credentials)
        effective_parent = parent_id or "root"
        query = (
            f"mimeType='{FOLDER_MIME_TYPE}' and trashed=false "
            f"and '{effective_parent}' in parents"
        )
        folders: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            response = (
                drive.files()
                .list(
                    q=query,
                    fields="nextPageToken,files(id,name,parents,modifiedTime,webViewLink)",
                    orderBy="name",
                    pageSize=1000,
                    pageToken=page_token,
                    spaces="drive",
                )
                .execute()
            )
            folders.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return sorted(folders, key=lambda item: str(item.get("name") or "").casefold())

    def folder_details(self, folder_id: str) -> dict[str, Any]:
        credentials = self.drive_service._load_credentials()
        drive = self.drive_service.drive_factory(credentials)
        return (
            drive.files()
            .get(
                fileId=folder_id,
                fields="id,name,parents,modifiedTime,webViewLink,trashed,mimeType",
            )
            .execute()
        )

    def add_mapping(
        self,
        folder_id: str,
        folder_name: str,
        *,
        purpose: str = "Other",
        folder_path: str | None = None,
        recursive: bool = True,
        metadata_only: bool = True,
    ) -> int:
        if not folder_id.strip():
            raise ValueError("A Google Drive folder ID is required.")
        if purpose not in self.PURPOSES:
            raise ValueError("Unknown folder purpose.")
        now = _now()
        return int(
            self.db.execute(
                """
                INSERT INTO google_drive_folder_mappings(
                    drive_folder_id,folder_name,folder_path,purpose,recursive,
                    metadata_only,enabled,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(drive_folder_id) DO UPDATE SET
                    folder_name=excluded.folder_name,
                    folder_path=excluded.folder_path,
                    purpose=excluded.purpose,
                    recursive=excluded.recursive,
                    metadata_only=excluded.metadata_only,
                    enabled=1,
                    updated_at=excluded.updated_at
                """,
                (
                    folder_id.strip(),
                    folder_name.strip() or "Untitled folder",
                    folder_path,
                    purpose,
                    int(recursive),
                    int(metadata_only),
                    1,
                    now,
                    now,
                ),
            )
        )

    def list_mappings(self) -> list[dict[str, Any]]:
        frame = self.db.frame(
            "SELECT * FROM google_drive_folder_mappings ORDER BY purpose,folder_name"
        )
        return frame.to_dict("records")

    def set_enabled(self, mapping_id: int, enabled: bool) -> None:
        self.db.execute(
            "UPDATE google_drive_folder_mappings SET enabled=?,updated_at=? WHERE id=?",
            (int(enabled), _now(), int(mapping_id)),
        )

    def remove_mapping(self, mapping_id: int) -> None:
        self.db.execute("DELETE FROM google_drive_folder_mappings WHERE id=?", (int(mapping_id),))

    def validate_mapping(self, mapping_id: int) -> dict[str, Any]:
        frame = self.db.frame(
            "SELECT * FROM google_drive_folder_mappings WHERE id=?", (int(mapping_id),)
        )
        if frame.empty:
            raise ValueError("Folder mapping was not found.")
        row = frame.iloc[0].to_dict()
        try:
            folder = self.folder_details(str(row["drive_folder_id"]))
            if folder.get("trashed"):
                raise RuntimeError("The mapped folder is in Google Drive trash.")
            if folder.get("mimeType") != FOLDER_MIME_TYPE:
                raise RuntimeError("The mapped item is no longer a folder.")
            now = _now()
            self.db.execute(
                """
                UPDATE google_drive_folder_mappings
                SET folder_name=?,last_validated_at=?,last_error=NULL,updated_at=?
                WHERE id=?
                """,
                (folder.get("name") or row["folder_name"], now, now, int(mapping_id)),
            )
        except Exception as exc:
            self.db.execute(
                "UPDATE google_drive_folder_mappings SET last_error=?,updated_at=? WHERE id=?",
                (str(exc), _now(), int(mapping_id)),
            )
            raise
        return folder


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
