from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pandas as pd

from creator_intelligence.services.publishing_outcomes import PublishingOutcomeService
from creator_intelligence.services.social_platforms import SocialPlatformService


class DB:
    def __init__(self, path):
        self.connection = sqlite3.connect(str(path))

    def execute(self, sql, params=()):
        cursor = self.connection.execute(sql, tuple(params))
        self.connection.commit()
        return cursor.lastrowid

    def frame(self, sql, params=()):
        return pd.read_sql_query(sql, self.connection, params=tuple(params))


def setup(tmp_path):
    db = DB(tmp_path / "outcomes.db")
    SocialPlatformService(db)
    return db, PublishingOutcomeService(db)


def test_generated_snapshot_stays_immutable_when_creator_edits_copy(tmp_path):
    _, service = setup(tmp_path)
    package_id = service.snapshot_packages(7, {
        "youtube_shorts": {"title": "Can They Wear Pants?", "description": "Original", "hashtags": ["#RimWorld"]}
    }, {"topic": "RimWorld", "clip_type": "Funny discussion"}, "High", 82)["youtube_shorts"]

    updated = service.record_decision(package_id, "Approved", {
        "title": "We Somehow Debated Pants", "description": "Published copy"
    })

    assert updated["generated_title"] == "Can They Wear Pants?"
    assert updated["used_title"] == "We Somehow Debated Pants"
    assert updated["edit_status"] == "Edited"
    assert updated["decision_status"] == "Approved"


def test_auto_match_and_milestone_snapshots_use_synced_post(tmp_path):
    db, service = setup(tmp_path)
    package_id = service.snapshot_packages(9, {
        "tiktok": {"caption": "We somehow started debating pants", "hook": "Wait, what?"}
    }, {}, "Moderate", 61)["tiktok"]
    created = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    db.execute("UPDATE publishing_packages SET created_at=? WHERE id=?", (created, package_id))
    db.execute("""INSERT INTO creator_published_titles(
        platform,content_type,title,published_at,views,likes,comments,shares,reach,
        watch_time,example_type,source_video_id,created_at,updated_at)
        VALUES('tiktok','short',?,?,?,?,?,?,?,?,'published','post-1',?,?)""",
        ("We somehow started debating pants", created, 10000, 900, 70, 40, 12000, 800, created, created))

    assert service.auto_match("tiktok") == [package_id]
    captured = service.capture_due_snapshots(datetime.now(timezone.utc))

    assert (package_id, 1) in captured
    assert (package_id, 24) in captured
    assert (package_id, 168) in captured
    assert service.package(package_id)["decision_status"] == "Published"
    dashboard = service.dashboard()
    assert dashboard.iloc[0]["source_video_id"] == "post-1"
    assert dashboard.iloc[0]["actual_score"] > 0


def test_only_measured_published_outcomes_affect_learning(tmp_path):
    db, service = setup(tmp_path)
    good = service.snapshot_packages(1, {"twitch": {"title": "Rareword Victory"}}, {}, "High", 90)["twitch"]
    rejected = service.snapshot_packages(2, {"twitch": {"title": "Ignoreword Loss"}}, {}, "Low", 20)["twitch"]
    service.record_decision(rejected, "Rejected")
    published = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    for source_id, title in (("good", "Rareword Victory"), ("bad", "Ignoreword Loss")):
        db.execute("""INSERT INTO creator_published_titles(
            platform,content_type,title,published_at,views,likes,comments,shares,
            example_type,source_video_id,created_at,updated_at)
            VALUES('twitch','clip',?,?,5000,500,50,20,'published',?,?,?)""",
            (title, published, source_id, published, published))
    service.link(good, "good")
    service.capture_due_snapshots(datetime.now(timezone.utc))

    weights = service.learning_adjustments("twitch")
    assert weights["rareword"] > 0
    assert "ignoreword" not in weights


def test_social_sync_runs_outcome_matching(tmp_path):
    db, outcomes = setup(tmp_path)
    social = SocialPlatformService(db)
    social.save_configuration("youtube", {"api_key": "key", "channel_id": "channel"})
    package_id = outcomes.snapshot_packages(3, {
        "youtube_shorts": {"title": "The Secret Tunnel Changed Everything"}
    }, {}, "High", 80)["youtube_shorts"]
    result = social.sync("youtube", fetcher=lambda *_: [{
        "source_video_id": "yt-1", "title": "The Secret Tunnel Changed Everything",
        "published_at": datetime.now(timezone.utc).isoformat(), "views": 100,
    }])

    assert result["outcomes_matched"] == 1
    assert outcomes.package(package_id)["decision_status"] == "Published"
