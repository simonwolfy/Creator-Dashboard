from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from creator_intelligence.data.database import Database
from creator_intelligence.services.asset_management import AssetManagementService
from creator_intelligence.services.video_metadata import VideoMetadataService


PROBE_PAYLOAD = {
    "format": {
        "duration": "3723.5",
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "bit_rate": "12000000",
    },
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "profile": "High",
            "pix_fmt": "yuv420p",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "60000/1001",
            "color_space": "bt709",
            "color_transfer": "bt709",
            "color_primaries": "bt709",
            "tags": {"rotate": "0"},
        },
        {
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
            "sample_rate": "48000",
        },
        {
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
            "sample_rate": "48000",
        },
    ],
}


def build_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "creator.db")
    db.migrate()
    return db


def fake_runner(command, **kwargs):
    return SimpleNamespace(returncode=0, stdout=json.dumps(PROBE_PAYLOAD), stderr="")


def test_migration_creates_video_metadata_table(tmp_path):
    db = build_db(tmp_path)
    assert db.table_exists("video_asset_metadata")
    assert any(record.version == 10 for record in db.migration_history())


def test_probe_local_managed_asset_persists_metadata(tmp_path):
    db = build_db(tmp_path)
    path = tmp_path / "recording.mp4"
    path.write_bytes(b"video")
    asset_id = AssetManagementService(db).create_asset(
        {
            "name": path.name,
            "asset_type": "Video",
            "storage_provider": "Local",
            "location": str(path),
        }
    )
    service = VideoMetadataService(db, ffprobe_path="ffprobe", runner=fake_runner)
    result = service.probe_asset(asset_id)
    assert result["probe_status"] == "Complete"
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert round(result["frame_rate"], 2) == 59.94
    assert result["audio_tracks"] == 2
    assert result["hdr_format"] == "SDR"


def test_cloud_only_asset_is_deferred_without_crashing(tmp_path):
    db = build_db(tmp_path)
    asset_id = AssetManagementService(db).create_asset(
        {
            "name": "cloud.mp4",
            "asset_type": "Video",
            "storage_provider": "Google Drive",
            "provider_key": "drive-file",
            "location": "https://drive.google.com/file/d/drive-file/view",
        }
    )
    service = VideoMetadataService(db, ffprobe_path="ffprobe", runner=fake_runner)
    result = service.probe_asset(asset_id)
    assert result["probe_status"] == "Needs local file"
    assert "cloud-only" in result["probe_error"]


def test_probe_pending_local_is_bounded_and_counts_results(tmp_path):
    db = build_db(tmp_path)
    assets = AssetManagementService(db)
    for index in range(3):
        path = tmp_path / f"video-{index}.mp4"
        path.write_bytes(b"video")
        assets.create_asset(
            {
                "name": path.name,
                "asset_type": "Video",
                "storage_provider": "Local",
                "location": str(path),
            }
        )
    service = VideoMetadataService(db, ffprobe_path="ffprobe", runner=fake_runner)
    result = service.probe_pending_local(limit=2)
    assert result == {"attempted": 2, "complete": 2, "failed": 0}
    assert len(service.assets(status="Complete")) == 2


def test_hdr_transfer_is_classified(tmp_path):
    payload = json.loads(json.dumps(PROBE_PAYLOAD))
    payload["streams"][0]["color_transfer"] = "smpte2084"

    def hdr_runner(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    db = build_db(tmp_path)
    path = tmp_path / "hdr.mp4"
    path.write_bytes(b"video")
    asset_id = AssetManagementService(db).create_asset(
        {
            "name": path.name,
            "asset_type": "Video",
            "storage_provider": "Local",
            "location": str(path),
        }
    )
    result = VideoMetadataService(db, ffprobe_path="ffprobe", runner=hdr_runner).probe_asset(asset_id)
    assert result["hdr_format"] == "HDR"
