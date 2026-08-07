from datetime import datetime, timedelta
from pathlib import Path

from creator_intelligence.data.database import Database
from creator_intelligence.services.content_library import ContentLibraryService
from creator_intelligence.services.creator_dashboard import CreatorDashboardService


def make_services(tmp_path: Path):
    db = Database(tmp_path / "dashboard.db")
    db.migrate()
    return ContentLibraryService(db), CreatorDashboardService(db)


def test_empty_dashboard_is_safe(tmp_path):
    _, dashboard = make_services(tmp_path)

    snapshot = dashboard.snapshot()

    assert snapshot.total_content == 0
    assert snapshot.counts_by_type == {}
    assert snapshot.work_queue == []
    assert snapshot.upcoming == []


def test_dashboard_summarizes_content_and_work(tmp_path):
    library, dashboard = make_services(tmp_path)
    future = (datetime.now() + timedelta(days=2)).isoformat()

    library.create_item(
        {
            "platform": "Twitch",
            "content_type": "VOD",
            "title": "Minecraft stream",
            "status": "Published",
        }
    )
    library.create_item(
        {
            "platform": "YouTube",
            "content_type": "Long-form Video",
            "title": "Episode 12",
            "status": "Needs review",
            "editor": "Editor A",
        }
    )
    library.create_item(
        {
            "platform": "YouTube",
            "content_type": "Short",
            "title": "Cave disaster short",
            "status": "Ready to publish",
            "published_at": future,
        }
    )

    snapshot = dashboard.snapshot()

    assert snapshot.total_content == 3
    assert snapshot.counts_by_type["VOD"] == 1
    assert snapshot.counts_by_type["Long-form Video"] == 1
    assert snapshot.counts_by_type["Short"] == 1
    assert [row["title"] for row in snapshot.work_queue][:2] == [
        "Episode 12",
        "Cave disaster short",
    ]
    assert snapshot.upcoming[0]["title"] == "Cave disaster short"
    assert len(snapshot.recent_activity) == 3
