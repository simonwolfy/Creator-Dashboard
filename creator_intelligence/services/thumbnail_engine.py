from __future__ import annotations

from pathlib import Path
from typing import Any


class ThumbnailEngineService:
    """Queues interval thumbnail extraction for locally available videos."""

    def __init__(self, processing_service):
        self.processing = processing_service

    def assets(self) -> list[dict[str, Any]]:
        frame = self.processing.assets().copy()
        if frame.empty:
            return []
        counts = self.processing.db.frame(
            """
            SELECT media_asset_id, COUNT(*) AS thumbnail_count,
                   MAX(created_at) AS latest_thumbnail_at,
                   MAX(file_path) AS latest_thumbnail_path
            FROM media_artifacts
            WHERE artifact_type='Thumbnail'
            GROUP BY media_asset_id
            """
        )
        if not counts.empty:
            frame = frame.merge(counts, how='left', left_on='id', right_on='media_asset_id')
        for column, default in (
            ('thumbnail_count', 0),
            ('latest_thumbnail_at', None),
            ('latest_thumbnail_path', None),
        ):
            if column not in frame:
                frame[column] = default
        frame['thumbnail_count'] = frame['thumbnail_count'].fillna(0).astype(int)
        return frame.to_dict('records')

    def queue_thumbnails(self, media_asset_id: int, interval_seconds: int = 300, width: int = 640) -> int:
        asset = self.processing.asset(media_asset_id)
        source = Path(str(asset.get('source_path') or ''))
        if not source.is_file():
            raise FileNotFoundError(f'Source video is not available locally: {source}')
        interval = max(30, min(int(interval_seconds), 3600))
        width = max(160, min(int(width), 1920))
        return self.processing.queue_job(
            media_asset_id,
            'Generate thumbnails',
            {'interval_seconds': interval, 'width': width},
            priority=50,
        )

    def queue_missing(self, interval_seconds: int = 300, width: int = 640, limit: int = 25) -> dict[str, int]:
        queued = skipped = 0
        for asset in self.assets():
            if queued >= max(1, min(int(limit), 250)):
                break
            if int(asset.get('thumbnail_count') or 0) > 0:
                skipped += 1
                continue
            source = Path(str(asset.get('source_path') or ''))
            if not source.is_file():
                skipped += 1
                continue
            self.queue_thumbnails(int(asset['id']), interval_seconds, width)
            queued += 1
        return {'queued': queued, 'skipped': skipped}

    def thumbnails(self, media_asset_id: int | None = None) -> list[dict[str, Any]]:
        frame = self.processing.artifacts(media_asset_id)
        if frame.empty:
            return []
        return frame[frame['artifact_type'] == 'Thumbnail'].to_dict('records')
