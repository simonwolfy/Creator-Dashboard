from __future__ import annotations

from typing import Any

from creator_intelligence.services.cloud_sync_engine import CloudSyncEngine


class GoogleDriveFolderProvider:
    """Adapts the Google Drive v3 files API to CloudSyncEngine."""

    FIELDS = (
        "nextPageToken,files("
        "id,name,mimeType,parents,size,createdTime,modifiedTime,"
        "md5Checksum,webViewLink,trashed,owners(displayName,emailAddress))"
    )

    def __init__(self, drive):
        self.drive = drive

    def list_folder_page(self, folder_id: str, page_token: str | None = None) -> dict[str, Any]:
        request = self.drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            spaces="drive",
            fields=self.FIELDS,
            pageSize=1000,
            pageToken=page_token,
            orderBy="folder,name_natural",
        )
        response = request.execute()
        items = []
        for entry in response.get("files", ()):
            normalized = dict(entry)
            normalized["mime_type"] = normalized.get("mimeType")
            normalized["parent_id"] = (normalized.get("parents") or [folder_id])[0]
            normalized["is_folder"] = normalized.get("mimeType") == "application/vnd.google-apps.folder"
            items.append(normalized)
        return {"items": items, "next_page_token": response.get("nextPageToken")}


def build_google_drive_sync_engine(google_drive_service, **engine_options) -> CloudSyncEngine:
    """Create an authenticated read-only sync engine from GoogleDriveService."""
    credentials = google_drive_service._load_credentials()
    drive = google_drive_service.drive_factory(credentials)
    return CloudSyncEngine(GoogleDriveFolderProvider(drive), **engine_options)
