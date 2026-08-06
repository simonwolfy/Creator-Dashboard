from __future__ import annotations

import csv
import json
import sqlite3

import pandas as pd

from creator_intelligence.core.credential_vault import MemoryCredentialBackend
from creator_intelligence.services.local_whisper_production import (
    LocalWhisperProductionService,
)


class SQLiteDB:
    def __init__(self, path):
        self.connection = sqlite3.connect(str(path))
        self.path = path
        self.credential_backend = MemoryCredentialBackend()

    def execute(self, sql, params=()):
        cursor = self.connection.execute(sql, tuple(params))
        self.connection.commit()
        return cursor.lastrowid

    def frame(self, sql, params=()):
        return pd.read_sql_query(sql, self.connection, params=tuple(params))


def make_service(tmp_path):
    db = SQLiteDB(tmp_path / "clip_intelligence.db")
    db.execute(
        """CREATE TABLE IF NOT EXISTS media_assets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT,
            source_path TEXT
        )"""
    )
    service = LocalWhisperProductionService(db)
    transcript_id = service.create_transcript("RimWorld stream")
    service.add_segments(
        transcript_id,
        [
            {
                "start": 10,
                "end": 22,
                "text": "Wait, what? No way! We found the secret tunnel and this is insane!",
                "confidence": 0.91,
            },
            {
                "start": 22,
                "end": 28,
                "text": "That was actually funny, bro.",
                "confidence": 0.88,
            },
        ],
    )
    clip_id = service.add_clip_candidate(
        transcript_id,
        10,
        28,
        "Secret tunnel",
        "Strong discovery reaction",
        80,
        "creator-selection",
    )
    return service, transcript_id, clip_id


def test_analyze_clip_candidate_builds_creator_package(tmp_path):
    service, transcript_id, clip_id = make_service(tmp_path)

    result = service.analyze_clip_candidate(clip_id)

    assert result["viral_score"] > 40
    assert result["hook_score"] > 40
    assert result["surprise_score"] > 40
    assert result["suggested_start_seconds"] < 10
    assert result["suggested_end_seconds"] > 28
    assert "Tunnel" in result["suggested_title"]
    assert len(result["title_alternatives"]) >= 5
    assert len(result["suggested_caption"]) < 180
    assert "tunnel" in result["suggested_caption"].lower()
    assert "?" in result["suggested_caption"]
    assert "tunnel" in result["hook_line"].lower()
    assert result["clip_type"] == "DISCOVERY"
    assert result["packaging_context"]["subject"] == "tunnel"
    assert result["packaging_reasoning"]
    assert result["likely_audience"] == "RimWorld viewers"
    assert result["platform_packages"]["youtube_shorts"]["title"]
    assert "#RimWorld" in result["suggested_hashtags"]

    row = service.clip_packaging(clip_id)
    assert row["intelligence_version"] == "creator-packaging-v6"
    assert row["clip_type"] == "DISCOVERY"
    assert json.loads(row["packaging_context_json"])["subject"] == "tunnel"
    assert json.loads(row["title_alternatives_json"])
    assert json.loads(row["platform_packages_json"])["tiktok"]["caption"]


def test_caption_is_packaging_copy_not_transcript_dump(tmp_path):
    service, _, clip_id = make_service(tmp_path)
    result = service.analyze_clip_candidate(clip_id)

    transcript_text = (
        "Wait, what? No way! We found the secret tunnel and this is insane! "
        "That was actually funny, bro."
    )
    assert result["suggested_caption"] != transcript_text
    assert result["caption_style"] == "clip-specific-engagement"
    assert result["retention_estimate"] > 40
    assert result["performance_prediction"] in {"High", "Moderate", "Experimental"}


def test_sheep_clip_generates_event_specific_package(tmp_path):
    service, transcript_id, _ = make_service(tmp_path)
    service.add_segments(
        transcript_id,
        [{
            "start": 40,
            "end": 48,
            "text": "Yeah, we can finally destroy the sheep. The sheep problem is over.",
            "confidence": 0.94,
        }],
    )
    clip_id = service.add_clip_candidate(
        transcript_id, 40, 48, "Sheep", "Colony sheep payoff", 90, "creator-selection"
    )

    result = service.analyze_clip_candidate(clip_id)

    assert result["clip_type"] == "CHAOS"
    assert result["packaging_context"]["subject"] == "sheep"
    assert "Sheep" in result["suggested_title"]
    assert "sheep" in result["hook_line"].lower()
    assert "sheep" in result["suggested_caption"].lower()
    assert "#RimWorld" in result["suggested_hashtags"]


def test_different_events_do_not_reuse_identical_primary_titles(tmp_path):
    service, transcript_id, first_id = make_service(tmp_path)
    first = service.analyze_clip_candidate(first_id)
    service.add_segments(
        transcript_id,
        [{
            "start": 50,
            "end": 58,
            "text": "We can finally destroy the sheep. They never saw this coming.",
            "confidence": 0.93,
        }],
    )
    second_id = service.add_clip_candidate(
        transcript_id, 50, 58, "Sheep war", "Sheep payoff", 88, "creator-selection"
    )
    second = service.analyze_clip_candidate(second_id)

    assert first["suggested_title"] != second["suggested_title"]
    history = service.db.frame("SELECT * FROM creator_package_history ORDER BY id")
    assert len(history) == 2


def test_batch_analysis_and_production_use_packaged_title_and_trim(tmp_path):
    service, transcript_id, clip_id = make_service(tmp_path)

    analyzed = service.analyze_clip_candidates([clip_id, clip_id])
    assert len(analyzed) == 1

    job_id = service.send_clips_to_production([clip_id])[0]
    job = service.db.frame(
        "SELECT * FROM production_clip_jobs WHERE id=?", (job_id,)
    ).iloc[0]
    clip = service.clip_candidates(transcript_id).iloc[0]

    assert job["title"] == clip["suggested_title"]
    assert float(job["start_seconds"]) == float(clip["suggested_start_seconds"])
    assert float(job["end_seconds"]) == float(clip["suggested_end_seconds"])


def test_historical_titles_persist_metadata_and_build_weighted_profile(tmp_path):
    service, _, _ = make_service(tmp_path)
    service.record_published_title(
        "Can We Actually Survive This?", platform="youtube", game="RimWorld",
        views=12000, likes=900, comments=45, watch_time=1234.5,
        published_at="2026-07-01T12:00:00", source_video_id="abc",
    )
    service.record_published_title("We Somehow Made This Worse", example_type="approved")
    service.record_published_title("EPIC GAMING MOMENT!!!", example_type="rejected")

    rows = service.published_titles()
    profile = service.title_style_profile()

    assert len(rows) == 3
    published = rows[rows["source_video_id"] == "abc"].iloc[0]
    assert int(published["views"]) == 12000
    assert float(published["watch_time"]) == 1234.5
    assert profile["positive_count"] == 2
    assert profile["negative_count"] == 1
    assert profile["first_person_rate"] >= .5
    assert "epic" in profile["avoided_words"]


def test_csv_import_records_titles_and_performance_metadata(tmp_path):
    service, _, _ = make_service(tmp_path)
    path = tmp_path / "titles.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "title", "platform", "game", "views", "likes", "comments",
            "watch_time", "example_type", "published_at", "source_video_id",
        ])
        writer.writeheader()
        writer.writerow({"title": "Did Chat Really Say That?", "platform": "twitch",
                         "game": "RimWorld", "views": "5000", "likes": "200",
                         "comments": "15", "watch_time": "812.5",
                         "example_type": "published", "published_at": "2026-06-01",
                         "source_video_id": "clip-1"})

    result = service.import_published_titles(str(path))
    row = service.published_titles().iloc[0]
    assert result == {"imported": 1, "skipped": 0}
    assert row["title"] == "Did Chat Really Say That?"
    assert int(row["views"]) == 5000
    assert row["game"] == "RimWorld"


def test_learned_style_ranks_candidates_and_penalizes_near_duplicates(tmp_path):
    service, transcript_id, clip_id = make_service(tmp_path)
    service.record_published_title("I Finally Found the Tunnel")
    service.record_published_title("Can We Actually Survive This?")
    service.record_published_title("Nobody Warned Me About This Tunnel", example_type="rejected")

    result = service.analyze_clip_candidate(clip_id)
    assert all(package.get("package_id") for package in result["platform_packages"].values())
    assert all(package.get("experiment_id") for package in result["platform_packages"].values())

    assert result["suggested_title"] != "I Finally Found the Tunnel"
    assert service._similarity(result["suggested_title"], "I Finally Found the Tunnel") < .92
    assert "Nobody Warned Me About This Tunnel" not in result["title_alternatives"][:2]


def test_semantic_event_uses_surrounding_segments_for_ambiguous_pants_clip(tmp_path):
    service, transcript_id, _ = make_service(tmp_path)
    service.add_segments(transcript_id, [
        {"start": 60, "end": 68, "text": "These colonists have clothing restrictions.", "confidence": .9},
        {"start": 68, "end": 76, "text": "Can they even wear pants?", "confidence": .94},
        {"start": 76, "end": 84, "text": "We somehow ended up debating what colonists can wear.", "confidence": .92},
    ])
    clip_id = service.add_clip_candidate(transcript_id, 68, 76, "Pants", "Ambiguous discussion", 75)

    result = service.analyze_clip_candidate(clip_id)
    event = result["packaging_context"]

    assert event["subject"] in {"colonist", "colonists"}
    assert event["subject"] != "pants"
    assert event["context_segment_count"] >= 3
    assert event["confidence"]["event"] >= .60
    assert event["fallback_mode"] == "event"


def test_low_confidence_event_uses_quote_driven_titles(tmp_path):
    service, transcript_id, _ = make_service(tmp_path)
    service.add_segments(transcript_id, [
        {"start": 100, "end": 108, "text": "Can they even do that?", "confidence": .9},
    ])
    clip_id = service.add_clip_candidate(transcript_id, 100, 108, "Question", "Ambiguous", 55)

    result = service.analyze_clip_candidate(clip_id)

    assert result["packaging_context"]["fallback_mode"] == "quote"
    assert result["packaging_context"]["confidence"]["event"] < .60
    assert result["suggested_title"] == "Can they even do that?"
    assert any("below 60%" in reason for reason in result["packaging_reasoning"])


def test_neighbor_context_uses_segment_order_not_arbitrary_seconds(tmp_path):
    service, transcript_id, _ = make_service(tmp_path)
    service.add_segments(transcript_id, [
        {"start": 0, "end": 5, "text": "The colonists have strict clothing rules.", "confidence": .9},
        {"start": 120, "end": 125, "text": "Can they wear pants?", "confidence": .9},
        {"start": 240, "end": 245, "text": "We are debating what colonists can wear.", "confidence": .9},
    ])
    clip_id = service.add_clip_candidate(transcript_id, 120, 125, "Question", "Context", 60)

    result = service.analyze_clip_candidate(clip_id)

    assert result["packaging_context"]["context_segment_count"] == 3
    assert result["packaging_context"]["subject"] == "colonist"
    assert result["packaging_context"]["validation"]["subject"] is True


def test_unreliable_event_and_quote_return_insufficient_context(tmp_path):
    service, transcript_id, _ = make_service(tmp_path)
    service.add_segments(transcript_id, [
        {"start": 300, "end": 304, "text": "Yeah, um, okay, you know.", "confidence": .7},
    ])
    clip_id = service.add_clip_candidate(transcript_id, 300, 304, "Filler", "No event", 20)

    result = service.analyze_clip_candidate(clip_id)

    assert result["packaging_status"] == "insufficient_context"
    assert result["packaging_context"]["fallback_mode"] == "insufficient_context"
    assert result["packaging_context"]["outcome"] == "Insufficient context"
    assert result["suggested_title"] == ""
    assert result["platform_packages"] == {}
    assert any("no package was invented" in reason for reason in result["packaging_reasoning"])


def test_title_ranking_explains_style_and_duplicate_penalties(tmp_path):
    service, _, clip_id = make_service(tmp_path)
    service.record_published_title("I Finally Found the Tunnel")

    result = service.analyze_clip_candidate(clip_id)
    ranking = result["packaging_context"]["title_ranking"]

    assert ranking
    assert {"style_score", "duplicate_similarity", "duplicate_risk"} <= set(ranking[0])
    duplicate = next(item for item in ranking if item["title"] == "I Finally Found the Tunnel")
    assert duplicate["duplicate_risk"] == "duplicate"
    assert result["suggested_title"] != duplicate["title"]


def test_twitch_title_sync_is_incremental_and_idempotent(tmp_path):
    service, _, _ = make_service(tmp_path)
    calls = []
    records = [{"title": "The Colony Finally Snapped", "content_type": "clip",
                "published_at": "2026-07-01T12:00:00Z", "views": 9000,
                "game": "RimWorld", "source_video_id": "tw-1"}]

    def fetcher(platform, since):
        calls.append((platform, since))
        return records

    first = service.sync_title_history("twitch", fetcher=fetcher)
    second = service.sync_title_history("twitch", fetcher=fetcher)

    assert first["changed"] == 1
    assert second["changed"] == 0
    assert calls == [("twitch", None), ("twitch", "2026-07-01T12:00:00Z")]
    assert len(service.published_titles()) == 1
    status = service.title_sync_status("twitch")
    assert status["status"] == "Completed"
    assert status["records_changed"] == 0


def test_youtube_title_sync_updates_profile_and_performance(tmp_path):
    service, _, _ = make_service(tmp_path)

    def fetcher(platform, since):
        assert platform == "youtube"
        assert since is None
        return [{"title": "Can We Survive One More Raid?", "content_type": "short",
                 "published_at": "2026-07-02T12:00:00Z", "views": "12000",
                 "likes": "800", "comments": "40", "source_video_id": "yt-1"}]

    result = service.sync_title_history("youtube", fetcher=fetcher)
    row = service.published_titles().iloc[0]

    assert result["changed"] == 1
    assert result["profile"]["example_count"] == 1
    assert int(row["views"]) == 12000
    assert int(row["likes"]) == 800
    assert row["content_type"] == "short"


def test_failed_title_sync_records_diagnostic_state(tmp_path):
    service, _, _ = make_service(tmp_path)

    def broken(platform, since):
        raise RuntimeError("expired token")

    try:
        service.sync_title_history("twitch", fetcher=broken)
    except RuntimeError:
        pass
    else:
        raise AssertionError("sync should fail")

    status = service.title_sync_status("twitch")
    assert status["status"] == "Failed"
    assert status["last_error"] == "expired token"


def test_youtube_api_pages_results_and_classifies_shorts(tmp_path, monkeypatch):
    service, _, _ = make_service(tmp_path)
    service.save_title_sync_configuration("youtube", {"api_key": "key", "channel_id": "channel"})
    responses = iter([
        {"items": [{"id": {"videoId": "one"}, "snippet": {"title": "One", "publishedAt": "2026-01-01"}}],
         "nextPageToken": "next"},
        {"items": [{"id": {"videoId": "two"}, "snippet": {"title": "Two", "publishedAt": "2026-01-02"}}]},
        {"items": [
            {"id": "one", "statistics": {"viewCount": "10"}, "contentDetails": {"duration": "PT45S"}},
            {"id": "two", "statistics": {"viewCount": "20"}, "contentDetails": {"duration": "PT12M"}},
        ]},
    ])
    monkeypatch.setattr(service, "_json_request", lambda request: next(responses))

    records = service._fetch_youtube_titles(None)

    assert [record["source_video_id"] for record in records] == ["one", "two"]
    assert [record["content_type"] for record in records] == ["short", "video"]


def test_youtube_content_performance_guides_title_and_description_packaging(tmp_path):
    service, _, clip_id = make_service(tmp_path)
    service.db.execute("""CREATE TABLE youtube_content(
        content_id TEXT PRIMARY KEY,title TEXT,description TEXT,duration_seconds REAL,
        views INTEGER,ctr REAL,avg_percentage_viewed REAL,likes INTEGER,comments INTEGER,shares INTEGER)""")
    service.db.execute("""INSERT INTO youtube_content VALUES
        ('best','I Finally Found the Hidden Tunnel','Subscribe and comment for more RimWorld.',45,50000,8.0,92,4000,300,200),
        ('weak','A Tunnel Appeared','Basic description',50,100,1.0,20,2,0,0)""")

    result = service.analyze_clip_candidate(clip_id)
    youtube = result["platform_packages"]["youtube_shorts"]
    evidence = result["packaging_context"]["youtube_evidence"]

    assert evidence["count"] == 2
    assert evidence["examples"][0]["content_id"] == "best"
    assert "Subscribe for more moments" in youtube["description"]
    assert youtube["historical_evidence"][0]["title"] == "I Finally Found the Hidden Tunnel"
    assert any("weighted by performance" in reason for reason in result["packaging_reasoning"])


def test_platform_profiles_generate_distinct_performance_grounded_packages(tmp_path):
    service, _, clip_id = make_service(tmp_path)
    for index, title in enumerate((
        "Would you enter this tunnel?", "Can this run get any stranger?", "What would you do here?"
    )):
        service.record_published_title(title, platform="tiktok", content_type="short",
                                       views=1000 + index * 500, likes=100, comments=20,
                                       published_at=f"2026-07-0{index + 1}T00:00:00Z",
                                       source_video_id=f"tt-{index}")
    for index, title in enumerate((
        "The tunnel changed everything. Follow for more.",
        "A hidden discovery from the stream. Follow for more.",
        "This RimWorld moment surprised us. Follow for more.",
    )):
        service.record_published_title(title, platform="instagram", content_type="reel",
                                       views=2000 + index * 500, likes=200, comments=30,
                                       published_at=f"2026-07-0{index + 1}T00:00:00Z",
                                       source_video_id=f"ig-{index}")

    result = service.analyze_clip_candidate(clip_id)
    packages = result["platform_packages"]
    profiles = result["packaging_context"]["platform_profiles"]

    assert profiles["tiktok"]["confidence"] == "Low"
    assert profiles["instagram"]["confidence"] == "Low"
    assert packages["tiktok"]["caption"] != packages["instagram_reels"]["caption"]
    assert packages["tiktok"]["historical_evidence"]
    assert packages["instagram_reels"]["historical_evidence"]
    assert "Follow for more moments" in packages["instagram_reels"]["caption"]
    assert packages["youtube_shorts"]["profile_confidence"] == "Insufficient"


def test_sparse_platform_history_falls_back_without_cross_platform_leakage(tmp_path):
    service, _, clip_id = make_service(tmp_path)
    service.record_published_title("One TikTok Example?", platform="tiktok", views=999999,
                                   source_video_id="only-one")

    result = service.analyze_clip_candidate(clip_id)
    profiles = result["packaging_context"]["platform_profiles"]

    assert profiles["tiktok"]["confidence"] == "Insufficient"
    assert profiles["instagram"]["count"] == 0
    assert result["platform_packages"]["tiktok"]["caption"] == result["suggested_caption"]
