from pathlib import Path

import pandas as pd
import pytest

from creator_intelligence.services.proxy_engine import ProxyEngineService


class FakeDb:
    def frame(self, query, params=()):
        if "FROM media_artifacts" in query:
            return pd.DataFrame()
        return pd.DataFrame()

    def execute(self, query, params=()):
        return 1


class FakeProcessing:
    def __init__(self, source_path: Path):
        self.db = FakeDb()
        self.source_path = source_path
        self.queued = []

    def assets(self):
        return pd.DataFrame(
            [
                {
                    "id": 1,
                    "display_name": "vod.mp4",
                    "source_path": str(self.source_path),
                    "duration_seconds": 3600,
                    "width": 1920,
                    "height": 1080,
                    "file_size_bytes": 10_000_000_000,
                }
            ]
        )

    def asset(self, asset_id):
        return self.assets().iloc[0].to_dict()

    def queue_job(self, asset_id, job_type, settings, priority=100):
        self.queued.append((asset_id, job_type, settings, priority))
        return 42

    def artifacts(self, asset_id=None):
        return pd.DataFrame()


def test_balanced_proxy_estimate_is_reasonable():
    estimate = ProxyEngineService.estimated_size_bytes(3600, "balanced")
    assert estimate is not None
    assert 700_000_000 < estimate < 900_000_000


def test_queue_proxy_uses_selected_preset(tmp_path):
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"video")
    processing = FakeProcessing(source)
    service = ProxyEngineService(processing)

    job_id = service.queue_proxy(1, "quality")

    assert job_id == 42
    asset_id, job_type, settings, priority = processing.queued[0]
    assert asset_id == 1
    assert job_type == "Generate proxy"
    assert settings["height"] == 1080
    assert settings["crf"] == 25
    assert settings["disposable"] is True
    assert priority == 40


def test_cloud_or_missing_source_is_not_queued(tmp_path):
    processing = FakeProcessing(tmp_path / "missing.mp4")
    service = ProxyEngineService(processing)

    with pytest.raises(FileNotFoundError):
        service.queue_proxy(1, "balanced")


def test_unknown_preset_is_rejected(tmp_path):
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"video")
    service = ProxyEngineService(FakeProcessing(source))

    with pytest.raises(ValueError):
        service.queue_proxy(1, "ultra")
