from __future__ import annotations

from contextlib import contextmanager
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterator


class GoogleDriveMediaCacheService:
    """Materialize a Drive video only for the lifetime of a local processing task."""

    DEFAULT_MAX_BYTES = 20 * 1024 * 1024 * 1024

    def __init__(self, drive_service, *, max_bytes=DEFAULT_MAX_BYTES,
                 downloader_factory: Callable[..., Any] | None = None):
        self.drive_service = drive_service
        self.max_bytes = int(max_bytes)
        self.downloader_factory = downloader_factory or self._default_downloader

    @contextmanager
    def materialize(self, file_id: str, *, progress=None) -> Iterator[Path]:
        credentials = self.drive_service._load_credentials()
        drive = self.drive_service.drive_factory(credentials)
        metadata = drive.files().get(
            fileId=str(file_id),
            fields="id,name,size,md5Checksum,mimeType,capabilities(canDownload)",
            supportsAllDrives=True,
        ).execute()
        if not (metadata.get("capabilities") or {}).get("canDownload", False):
            raise PermissionError("Google Drive does not permit downloading this video.")
        size = int(metadata.get("size") or 0)
        if size and size > self.max_bytes:
            raise ValueError(
                f"The Drive video is {size / 1024**3:.1f} GB, above the "
                f"{self.max_bytes / 1024**3:.1f} GB temporary-cache limit."
            )
        with tempfile.TemporaryDirectory(prefix="creator-intel-drive-") as folder:
            root = Path(folder)
            free = shutil.disk_usage(root).free
            if size and free < size * 1.1:
                raise OSError("There is not enough free disk space for the temporary Drive video.")
            name = self._safe_name(metadata.get("name") or f"{file_id}.mp4")
            partial = root / f"{name}.part"
            final = root / name
            request = drive.files().get_media(fileId=str(file_id), supportsAllDrives=True)
            with partial.open("wb") as stream:
                downloader = self.downloader_factory(stream, request)
                complete = False
                while not complete:
                    status, complete = downloader.next_chunk(num_retries=3)
                    if progress and status:
                        progress(float(status.progress()) * 100)
            partial.replace(final)
            if size and final.stat().st_size != size:
                raise IOError("The temporary Drive download did not match its expected size.")
            try:
                yield final
            finally:
                final.unlink(missing_ok=True)
                partial.unlink(missing_ok=True)

    @staticmethod
    def _safe_name(value):
        invalid = '<>:"/\\|?*'
        clean = "".join("_" if char in invalid else char for char in Path(str(value)).name)
        return clean.strip(" .") or "drive-video.mp4"

    @staticmethod
    def _default_downloader(stream, request):
        try:
            from googleapiclient.http import MediaIoBaseDownload
        except ImportError as exc:
            raise RuntimeError("Install Google Drive dependencies before downloading videos.") from exc
        return MediaIoBaseDownload(stream, request, chunksize=8 * 1024 * 1024)
