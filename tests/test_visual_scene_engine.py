from __future__ import annotations

from pathlib import Path

from creator_intelligence.data.database import Database
from creator_intelligence.services.video_processing import VideoProcessingService
from creator_intelligence.services.visual_scene_engine import VisualSceneEngineService


def build_service(tmp_path: Path):
    db = Database(tmp_path / "creator.db")
    db.migrate()
    processing = VideoProcessingService(
        db,
        output_root=tmp_path / "processing",
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
    )
    service = VisualSceneEngineService(db, processing)
    return db, processing, service


def test_visual_scene_schema_is_created(tmp_path):
    db, _processing, service = build_service(tmp_path)
    assert db.table_exists("visual_scene_changes")
    assert service.changes().empty


def test_local_original_is_preferred_over_proxy(tmp_path):
    _db, processing, service = build_service(tmp_path)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    asset_id = processing.import_video(source, auto_probe=False)

    selected, kind = service.source_for(asset_id)
    assert selected == source.resolve()
    assert kind == "original"


def test_completed_proxy_is_used_when_original_is_missing(tmp_path):
    db, processing, service = build_service(tmp_path)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    asset_id = processing.import_video(source, auto_probe=False)
    source.unlink()

    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"proxy")
    now = "2026-08-01T00:00:00"
    db.execute(
        """INSERT INTO media_artifacts(
               media_asset_id,job_id,artifact_type,file_path,file_size_bytes,
               metadata_json,created_at
           ) VALUES(?,?,?,?,?,?,?)""",
        (asset_id, None, "Proxy", str(proxy), proxy.stat().st_size, "{}", now),
    )

    selected, kind = service.source_for(asset_id)
    assert selected == proxy
    assert kind == "proxy"


def test_cloud_or_missing_asset_is_deferred(tmp_path):
    _db, processing, service = build_service(tmp_path)
    missing = tmp_path / "missing.mp4"
    now = "2026-08-01T00:00:00"
    asset_id = int(processing.db.execute(
        """INSERT INTO media_assets(
               display_name,source_path,status,created_at,updated_at
           ) VALUES(?,?,?,?,?)""",
        ("missing.mp4", str(missing), "Imported", now, now),
    ))

    try:
        service.source_for(asset_id)
    except FileNotFoundError as exc:
        assert "local video or completed proxy" in str(exc)
    else:
        raise AssertionError("Expected missing media to be deferred")
