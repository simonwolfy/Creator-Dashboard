from pathlib import Path

from creator_intelligence.data.database import Database
from creator_intelligence.services.folder_watcher import FolderWatcherService


def make_service(tmp_path: Path) -> FolderWatcherService:
    db = Database(tmp_path / "watcher.db")
    db.migrate()
    return FolderWatcherService(db)


def test_new_files_are_imported_without_duplicates(tmp_path):
    service = make_service(tmp_path)
    watched = tmp_path / "obs"
    watched.mkdir()
    recording = watched / "stream.mp4"
    recording.write_bytes(b"video")
    folder_id = service.add_folder(str(watched))

    first = service.scan_folder(folder_id)
    second = service.scan_folder(folder_id)

    assert first.created == 1
    assert second.created == 0
    assert second.unchanged == 1
    assert len(service.assets.search()) == 1


def test_changed_files_are_refreshed(tmp_path):
    service = make_service(tmp_path)
    watched = tmp_path / "exports"
    watched.mkdir()
    export = watched / "episode.mp4"
    export.write_bytes(b"one")
    folder_id = service.add_folder(str(watched))
    service.scan_folder(folder_id)

    export.write_bytes(b"a larger replacement")
    summary = service.scan_folder(folder_id)
    asset = service.assets.search()[0]

    assert summary.updated == 1
    assert asset["size_bytes"] == len(b"a larger replacement")


def test_removed_files_are_marked_missing(tmp_path):
    service = make_service(tmp_path)
    watched = tmp_path / "thumbnails"
    watched.mkdir()
    image = watched / "thumb.png"
    image.write_bytes(b"png")
    folder_id = service.add_folder(str(watched))
    service.scan_folder(folder_id)

    image.unlink()
    summary = service.scan_folder(folder_id)

    assert summary.missing == 1
    assert service.assets.search()[0]["status"] == "Missing"


def test_extension_filters_and_disabled_folders(tmp_path):
    service = make_service(tmp_path)
    watched = tmp_path / "mixed"
    watched.mkdir()
    (watched / "keep.mp4").write_bytes(b"video")
    (watched / "skip.txt").write_text("notes")
    folder_id = service.add_folder(str(watched), include_extensions="mp4")

    assert service.scan_folder(folder_id).created == 1
    service.set_enabled(folder_id, False)
    assert service.scan_all() == []


def test_missing_folder_is_recorded_as_scan_error(tmp_path):
    service = make_service(tmp_path)
    folder_id = service.add_folder(str(tmp_path / "not-created"))

    summary = service.scan_folder(folder_id)
    folder = service.list_folders()[0]

    assert summary.errors == 1
    assert "does not exist" in summary.error_message
    assert "does not exist" in folder["last_error"]


def test_checksum_is_calculated_when_enabled(tmp_path):
    service = make_service(tmp_path)
    watched = tmp_path / "audio"
    watched.mkdir()
    (watched / "music.wav").write_bytes(b"same-content")
    folder_id = service.add_folder(str(watched), calculate_checksums=True)

    service.scan_folder(folder_id)

    assert service.assets.search()[0]["checksum_sha256"]
