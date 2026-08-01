from pathlib import Path

from creator_intelligence.data.database import Database
from creator_intelligence.services.google_drive_folders import GoogleDriveFolderMappingService


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class PaginatedFiles:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("pageToken") is None:
            return FakeRequest(
                {
                    "files": [{"id": "b", "name": "Zulu"}],
                    "nextPageToken": "page-2",
                }
            )
        return FakeRequest({"files": [{"id": "a", "name": "Alpha"}]})


class FakeDrive:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


class FakeConnection:
    def __init__(self, files):
        self.files = files

    def _load_credentials(self):
        return object()

    def drive_factory(self, credentials):
        return FakeDrive(self.files)


def make_service(tmp_path: Path, files: PaginatedFiles):
    db = Database(tmp_path / "creator.db")
    db.migrate()
    return GoogleDriveFolderMappingService(db, FakeConnection(files))


def test_live_browser_reads_all_pages_and_sorts(tmp_path):
    files = PaginatedFiles()
    folders = make_service(tmp_path, files).browse_folders()
    assert [folder["name"] for folder in folders] == ["Alpha", "Zulu"]
    assert len(files.calls) == 2
    assert files.calls[1]["pageToken"] == "page-2"


def test_live_browser_scopes_root_and_child_queries(tmp_path):
    root_files = PaginatedFiles()
    make_service(tmp_path, root_files).browse_folders()
    assert "'root' in parents" in root_files.calls[0]["q"]

    child_files = PaginatedFiles()
    make_service(tmp_path, child_files).browse_folders("folder-123")
    assert "'folder-123' in parents" in child_files.calls[0]["q"]
