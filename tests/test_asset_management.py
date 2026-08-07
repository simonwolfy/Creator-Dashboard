from pathlib import Path

import pytest

from creator_intelligence.data.database import Database
from creator_intelligence.services.asset_management import AssetManagementService
from creator_intelligence.services.content_library import ContentLibraryService


def make_services(tmp_path: Path):
    db = Database(tmp_path / "assets.db")
    db.migrate()
    return AssetManagementService(db), ContentLibraryService(db)


def test_create_update_and_search_asset(tmp_path):
    assets, _ = make_services(tmp_path)
    asset_id = assets.create_asset(
        {
            "name": "Minecraft VOD.mp4",
            "asset_type": "Video",
            "role": "Raw recording",
            "storage_provider": "Local",
            "location": "D:/Recordings/Minecraft VOD.mp4",
            "size_bytes": 12_000_000,
            "checksum_sha256": "ABC123",
        }
    )

    assets.update_asset(asset_id, {"status": "Archived", "notes": "Moved after edit"})
    asset = assets.get_asset(asset_id)

    assert asset is not None
    assert asset["status"] == "Archived"
    assert asset["checksum_sha256"] == "abc123"
    assert assets.search("Minecraft", asset_type="Video")[0]["id"] == asset_id


def test_content_can_have_multiple_assets(tmp_path):
    assets, content = make_services(tmp_path)
    content_id = content.create_item(
        {"platform": "YouTube", "content_type": "Long-form", "title": "Episode 4"}
    )
    recording_id = assets.create_asset(
        {"name": "raw.mp4", "asset_type": "Video", "role": "Raw recording"}
    )
    thumbnail_id = assets.create_asset(
        {"name": "thumb.png", "asset_type": "Image", "role": "Thumbnail"}
    )

    assets.link_content(content_id, recording_id, role="source", is_primary=True)
    assets.link_content(content_id, thumbnail_id, role="thumbnail")

    linked = assets.assets_for_content(content_id)
    assert {row["id"] for row in linked} == {recording_id, thumbnail_id}
    assert linked[0]["id"] == recording_id
    assert assets.content_for_asset(thumbnail_id)[0]["id"] == content_id


def test_derived_assets_link_to_source(tmp_path):
    assets, _ = make_services(tmp_path)
    source_id = assets.create_asset(
        {"name": "stream.mkv", "asset_type": "Video", "role": "Raw recording"}
    )
    project_id = assets.create_asset(
        {"name": "episode.prproj", "asset_type": "Project", "role": "Editor project"}
    )
    export_id = assets.create_asset(
        {"name": "episode.mp4", "asset_type": "Video", "role": "Final export"}
    )

    assets.relate_assets(source_id, project_id, "used_by")
    assets.relate_assets(project_id, export_id)

    assert assets.derived_assets(source_id)[0]["id"] == project_id
    assert assets.source_assets(export_id)[0]["id"] == project_id


def test_duplicate_provider_location_is_rejected(tmp_path):
    assets, _ = make_services(tmp_path)
    values = {
        "name": "vod.mp4",
        "asset_type": "Video",
        "storage_provider": "Google Drive",
        "location": "drive://file-123",
    }
    assets.create_asset(values)

    with pytest.raises(Exception):
        assets.create_asset({**values, "name": "duplicate.mp4"})


def test_checksum_duplicate_lookup_and_missing_status(tmp_path):
    assets, _ = make_services(tmp_path)
    checksum = "f" * 64
    first = assets.create_asset(
        {"name": "copy-a.mp4", "asset_type": "Video", "checksum_sha256": checksum}
    )
    second = assets.create_asset(
        {
            "name": "copy-b.mp4",
            "asset_type": "Video",
            "storage_provider": "Backup",
            "checksum_sha256": checksum.upper(),
        }
    )

    assert {row["id"] for row in assets.duplicates_for_checksum(checksum)} == {first, second}

    assets.mark_verified(first, available=False)
    missing = assets.get_asset(first)
    assert missing is not None
    assert missing["status"] == "Missing"
    assert missing["last_verified_at"] is not None


def test_self_asset_relationship_is_rejected(tmp_path):
    assets, _ = make_services(tmp_path)
    asset_id = assets.create_asset({"name": "test", "asset_type": "Other"})

    with pytest.raises(ValueError):
        assets.relate_assets(asset_id, asset_id)
