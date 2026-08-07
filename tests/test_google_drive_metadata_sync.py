from pathlib import Path

from creator_intelligence.data.database import Database
from creator_intelligence.services.cloud_sync_engine import SyncItem, SyncResult
from creator_intelligence.services.google_drive_metadata_sync import GoogleDriveMetadataSyncService


class FakeDriveService:
    pass


class FakeEngine:
    def __init__(self, items):
        self.items = items

    def scan(self, root_folder_id, recursive=True):
        return SyncResult(root_folder_id, tuple(self.items), 1, 1, 0, False)


def setup_service(tmp_path: Path):
    db = Database(tmp_path / "creator.db")
    db.migrate()
    db.execute(
        """INSERT INTO google_drive_folder_mappings(
        drive_folder_id,folder_name,folder_path,purpose,recursive,metadata_only,
        enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
        ("folder-1", "Vids", "My Drive/Vids", "Raw Recordings", 1, 1, 1, "now", "now"),
    )
    return db, GoogleDriveMetadataSyncService(db, FakeDriveService())


def video_item(name="episode.mp4"):
    return SyncItem(
        provider_id="file-1",
        name=name,
        mime_type="video/mp4",
        parent_id="folder-1",
        raw={
            "id": "file-1",
            "name": name,
            "mimeType": "video/mp4",
            "size": "1234",
            "modifiedTime": "2026-08-01T00:00:00Z",
            "webViewLink": "https://drive.google.com/file-1",
        },
    )


def test_sync_creates_drive_asset(tmp_path, monkeypatch):
    db, service = setup_service(tmp_path)
    monkeypatch.setattr(
        "creator_intelligence.services.google_drive_metadata_sync.build_google_drive_sync_engine",
        lambda drive_service: FakeEngine([video_item()]),
    )
    result = service.sync_mapping(1)
    assert result.created == 1
    assert result.scanned == 1
    assets = db.frame("SELECT * FROM managed_assets")
    assert len(assets) == 1
    assert assets.iloc[0]["storage_provider"] == "Google Drive"
    assert assets.iloc[0]["asset_type"] == "Video"


def test_repeat_sync_updates_without_duplicate(tmp_path, monkeypatch):
    db, service = setup_service(tmp_path)
    engines = [FakeEngine([video_item()]), FakeEngine([video_item("renamed.mp4")])]
    monkeypatch.setattr(
        "creator_intelligence.services.google_drive_metadata_sync.build_google_drive_sync_engine",
        lambda drive_service: engines.pop(0),
    )
    service.sync_mapping(1)
    result = service.sync_mapping(1)
    assert result.created == 0
    assert result.updated == 1
    assert db.scalar("SELECT COUNT(*) FROM managed_assets") == 1
    assert db.scalar("SELECT name FROM managed_assets") == "renamed.mp4"


def test_missing_drive_file_marks_asset_missing(tmp_path, monkeypatch):
    db, service = setup_service(tmp_path)
    engines = [FakeEngine([video_item()]), FakeEngine([])]
    monkeypatch.setattr(
        "creator_intelligence.services.google_drive_metadata_sync.build_google_drive_sync_engine",
        lambda drive_service: engines.pop(0),
    )
    service.sync_mapping(1)
    result = service.sync_mapping(1)
    assert result.missing == 1
    assert db.scalar("SELECT status FROM managed_assets") == "Missing"
    assert db.scalar("SELECT available FROM google_drive_files") == 0


def test_sync_run_history_is_recorded(tmp_path, monkeypatch):
    db, service = setup_service(tmp_path)
    monkeypatch.setattr(
        "creator_intelligence.services.google_drive_metadata_sync.build_google_drive_sync_engine",
        lambda drive_service: FakeEngine([video_item()]),
    )
    service.sync_mapping(1)
    run = service.recent_runs()[0]
    assert run["status"] == "Completed"
    assert run["files_scanned"] == 1
