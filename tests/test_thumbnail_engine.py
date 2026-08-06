from pathlib import Path

import pandas as pd
import pytest

from creator_intelligence.services.thumbnail_engine import ThumbnailEngineService


class FakeProcessing:
    def __init__(self, source: Path):
        self.source = source
        self.queued = []
        self.db = self

    def assets(self):
        return pd.DataFrame([{'id': 1, 'display_name': source_name(self.source), 'source_path': str(self.source)}])

    def asset(self, asset_id):
        return {'id': asset_id, 'source_path': str(self.source)}

    def queue_job(self, asset_id, job_type, settings, priority=100):
        self.queued.append((asset_id, job_type, settings, priority))
        return len(self.queued)

    def frame(self, sql, params=()):
        return pd.DataFrame()

    def artifacts(self, asset_id=None):
        return pd.DataFrame()


def source_name(path: Path) -> str:
    return path.name


def test_queue_thumbnails_clamps_settings(tmp_path):
    source = tmp_path / 'video.mp4'
    source.write_bytes(b'x')
    processing = FakeProcessing(source)
    service = ThumbnailEngineService(processing)

    job_id = service.queue_thumbnails(1, interval_seconds=5, width=5000)

    assert job_id == 1
    _, job_type, settings, priority = processing.queued[0]
    assert job_type == 'Generate thumbnails'
    assert settings == {'interval_seconds': 30, 'width': 1920}
    assert priority == 50


def test_queue_thumbnails_requires_local_source(tmp_path):
    processing = FakeProcessing(tmp_path / 'missing.mp4')
    service = ThumbnailEngineService(processing)

    with pytest.raises(FileNotFoundError):
        service.queue_thumbnails(1)


def test_queue_missing_skips_nonlocal_assets(tmp_path):
    processing = FakeProcessing(tmp_path / 'missing.mp4')
    service = ThumbnailEngineService(processing)

    assert service.queue_missing() == {'queued': 0, 'skipped': 1}
