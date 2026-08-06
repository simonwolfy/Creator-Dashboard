from __future__ import annotations

import json
import sqlite3
import csv

import pandas as pd

from creator_intelligence.services.local_whisper_production import (
    LocalWhisperProductionService,
)


class SQLiteDB:
    def __init__(self, path):
        self.connection = sqlite3.connect(str(path))

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
    assert row["intelligence_version"] == "creator-packaging-v4"
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

    assert result["suggested_title"] != "I Finally Found the Tunnel"
    assert service._similarity(result["suggested_title"], "I Finally Found the Tunnel") < .92
    assert "Nobody Warned Me About This Tunnel" not in result["title_alternatives"][:2]
