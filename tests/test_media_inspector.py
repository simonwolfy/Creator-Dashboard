from pathlib import Path

from creator_intelligence.data.database import Database
from creator_intelligence.services.asset_management import AssetManagementService
from creator_intelligence.ui.pages.asset_library import AssetLibraryPage


def make_service(tmp_path: Path):
    db = Database(tmp_path / "inspector.db")
    db.migrate()
    return db, AssetManagementService(db)


def test_asset_search_includes_video_metadata(tmp_path):
    db, assets = make_service(tmp_path)
    asset_id = assets.create_asset({"name": "vod.mp4", "asset_type": "Video"})
    db.execute(
        """
        INSERT INTO video_asset_metadata(
            managed_asset_id,duration_seconds,width,height,frame_rate,video_codec,
            audio_codec,audio_tracks,audio_channels,audio_sample_rate,container_format,
            bit_rate,hdr_format,probe_status,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (asset_id, 3661.2, 1920, 1080, 59.94, "h264", "aac", 2, 2, 48000,
         "mov,mp4,m4a,3gp,3g2,mj2", 12_500_000, "SDR", "Complete", "2026-08-01"),
    )

    row = assets.search("vod")[0]
    assert row["duration_seconds"] == 3661.2
    assert row["width"] == 1920
    assert row["height"] == 1080
    assert row["video_codec"] == "h264"
    assert row["probe_status"] == "Complete"


def test_media_inspector_formatters():
    assert AssetLibraryPage._format_duration(3661) == "1:01:01"
    assert AssetLibraryPage._format_duration(125) == "2:05"
    assert AssetLibraryPage._resolution({"width": 1920, "height": 1080}) == "1920 × 1080"
    assert AssetLibraryPage._aspect_ratio(1920, 1080) == "16:9"
    assert AssetLibraryPage._format_fps(59.94) == "59.94 fps"
    assert AssetLibraryPage._format_bitrate(12_500_000) == "12.50 Mbps"
