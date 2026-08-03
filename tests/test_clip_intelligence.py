from __future__ import annotations

import json
import sqlite3

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
    assert result["suggested_title"] != "Wait, what"
    assert len(result["title_alternatives"]) >= 5
    assert len(result["suggested_caption"]) < 180
    assert "?" in result["suggested_caption"]
    assert result["hook_line"]
    assert result["packaging_reasoning"]
    assert result["likely_audience"] == "RimWorld viewers"
    assert result["platform_packages"]["youtube_shorts"]["title"]
    assert "#RimWorld" in result["suggested_hashtags"]

    row = service.clip_packaging(clip_id)
    assert row["intelligence_version"] == "creator-packaging-v2"
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
    assert result["caption_style"] == "conversational-engagement"
    assert result["retention_estimate"] > 40
    assert result["performance_prediction"] in {"High", "Moderate", "Experimental"}


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
