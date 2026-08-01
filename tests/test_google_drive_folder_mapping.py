from pathlib import Path

import pytest

from creator_intelligence.data.database import Database
from creator_intelligence.services.google_drive_folders import GoogleDriveFolderMappingService


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeFiles:
    def list(self, **kwargs):
        return FakeRequest({"files": [{"id": "folder-1", "name": "OBS Recordings"}]})

    def get(self, **kwargs):
        return FakeRequest(
            {
                "id": kwargs["fileId"],
                "name": "OBS Recordings",
                "trashed": False,
                "mimeType": "application/vnd.google-apps.folder",
            }
        )


class FakeDrive:
    def files(self):
        return FakeFiles()


class FakeDriveConnection:
    def _load_credentials(self):
        return object()

    def drive_factory(self, credentials):
        return FakeDrive()


def service(tmp_path: Path) -> GoogleDriveFolderMappingService:
    db = Database(tmp_path / "creator.db")
    db.migrate()
    return GoogleDriveFolderMappingService(db, FakeDriveConnection())


def test_browse_folders_uses_provider(tmp_path):
    folders = service(tmp_path).browse_folders()
    assert folders == [{"id": "folder-1", "name": "OBS Recordings"}]


def test_mapping_is_duplicate_safe(tmp_path):
    mapping = service(tmp_path)
    mapping.add_mapping("folder-1", "OBS", purpose="Raw Recordings")
    mapping.add_mapping("folder-1", "OBS Recordings", purpose="Raw Recordings")
    rows = mapping.list_mappings()
    assert len(rows) == 1
    assert rows[0]["folder_name"] == "OBS Recordings"


def test_validate_mapping_updates_timestamp(tmp_path):
    mapping = service(tmp_path)
    mapping.add_mapping("folder-1", "OBS")
    mapping_id = mapping.list_mappings()[0]["id"]
    mapping.validate_mapping(mapping_id)
    assert mapping.list_mappings()[0]["last_validated_at"]


def test_unknown_purpose_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        service(tmp_path).add_mapping("folder-1", "OBS", purpose="Unknown")


def test_remove_mapping(tmp_path):
    mapping = service(tmp_path)
    mapping.add_mapping("folder-1", "OBS")
    mapping.remove_mapping(mapping.list_mappings()[0]["id"])
    assert mapping.list_mappings() == []
