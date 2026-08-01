from pathlib import Path

import pytest

from creator_intelligence.data.database import Database
from creator_intelligence.services.content_library import ContentLibraryService


def make_service(tmp_path: Path) -> ContentLibraryService:
    db = Database(tmp_path / "content.db")
    db.migrate()
    return ContentLibraryService(db)


def test_create_update_and_search_content(tmp_path):
    service = make_service(tmp_path)
    item_id = service.create_item(
        {
            "platform": "YouTube",
            "external_id": "video-1",
            "content_type": "Short",
            "title": "Minecraft cave disaster",
            "game_topic": "Minecraft",
            "series_name": "Pokemon Survival",
            "status": "Published",
            "editor": "Editor A",
            "tags": ["minecraft", "short"],
            "collaborators": ["Sakura"],
            "views": 125000,
        }
    )

    service.update_item(item_id, {"title": "Minecraft cave disaster!", "views": 130000})
    item = service.get_item(item_id)

    assert item is not None
    assert item["title"] == "Minecraft cave disaster!"
    assert item["views"] == 130000
    assert item["tags"] == ["minecraft", "short"]
    assert item["collaborators"] == ["Sakura"]

    results = service.search(
        "cave",
        platform="YouTube",
        content_type="Short",
        game_topic="Minecraft",
        min_views=100000,
    )
    assert [row["id"] for row in results] == [item_id]


def test_source_vod_can_have_multiple_outputs(tmp_path):
    service = make_service(tmp_path)
    vod_id = service.create_item(
        {
            "platform": "Twitch",
            "external_id": "vod-123",
            "content_type": "VOD",
            "title": "Eight hour Minecraft stream",
        }
    )
    episode_id = service.create_item(
        {
            "platform": "YouTube",
            "external_id": "episode-4",
            "content_type": "Long-form",
            "title": "Pokemon Survival Episode 4",
        }
    )
    short_id = service.create_item(
        {
            "platform": "YouTube",
            "external_id": "short-4a",
            "content_type": "Short",
            "title": "We died in the cave",
        }
    )

    service.relate(vod_id, episode_id, start_seconds=400, end_seconds=4200)
    service.relate(vod_id, short_id, start_seconds=2400, end_seconds=2445)

    children = service.children(vod_id)
    assert {row["id"] for row in children} == {episode_id, short_id}
    assert service.parents(short_id)[0]["id"] == vod_id


def test_duplicate_external_id_is_rejected_per_platform(tmp_path):
    service = make_service(tmp_path)
    values = {
        "platform": "YouTube",
        "external_id": "same-id",
        "content_type": "Video",
        "title": "First",
    }
    service.create_item(values)

    with pytest.raises(Exception):
        service.create_item({**values, "title": "Duplicate"})

    other_platform_id = service.create_item({**values, "platform": "Twitch"})
    assert service.get_item(other_platform_id) is not None


def test_self_relationship_is_rejected(tmp_path):
    service = make_service(tmp_path)
    item_id = service.create_item(
        {"platform": "Local", "content_type": "Clip", "title": "Test"}
    )

    with pytest.raises(ValueError):
        service.relate(item_id, item_id)
