from __future__ import annotations

from pathlib import Path

import pytest

from creator_intelligence.services.google_drive_media_cache import GoogleDriveMediaCacheService


class Request:
    def __init__(self, payload=None):
        self.payload = payload

    def execute(self):
        return self.payload


class Files:
    def __init__(self, metadata):
        self.metadata = metadata

    def get(self, **_kwargs):
        return Request(self.metadata)

    def get_media(self, **_kwargs):
        return Request()


class API:
    def __init__(self, metadata):
        self._files = Files(metadata)

    def files(self):
        return self._files


class DriveService:
    def __init__(self, metadata):
        self.api = API(metadata)
        self.drive_factory = lambda _credentials: self.api

    def _load_credentials(self):
        return object()


class Status:
    def __init__(self, value):
        self.value = value

    def progress(self):
        return self.value


class Downloader:
    def __init__(self, stream, _request):
        self.stream = stream

    def next_chunk(self, num_retries=0):
        assert num_retries == 3
        self.stream.write(b"video")
        return Status(1), True


def test_drive_video_is_available_only_inside_cache_context():
    drive = DriveService({
        "id": "file-1", "name": "clip.mov", "size": "5",
        "capabilities": {"canDownload": True},
    })
    cache = GoogleDriveMediaCacheService(drive, downloader_factory=Downloader)

    with cache.materialize("file-1") as path:
        cached = Path(path)
        assert cached.read_bytes() == b"video"
    assert not cached.exists()
    assert not cached.parent.exists()


def test_drive_download_rejects_permission_and_cache_limit():
    denied = DriveService({
        "id": "file-2", "name": "clip.mp4", "size": "5",
        "capabilities": {"canDownload": False},
    })
    with pytest.raises(PermissionError):
        with GoogleDriveMediaCacheService(denied).materialize("file-2"):
            pass

    large = DriveService({
        "id": "file-3", "name": "clip.mp4", "size": "6",
        "capabilities": {"canDownload": True},
    })
    with pytest.raises(ValueError):
        with GoogleDriveMediaCacheService(large, max_bytes=5).materialize("file-3"):
            pass
