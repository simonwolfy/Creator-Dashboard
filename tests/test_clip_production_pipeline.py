from __future__ import annotations

import sqlite3

import pandas as pd

from creator_intelligence.services.local_whisper_production import (
    LocalWhisperProductionService,
)
from creator_intelligence.services.production_pipeline import ProductionPipelineService


class SQLiteDB:
    def __init__(self, path):
        self.connection = sqlite3.connect(str(path))

    def execute(self, sql, params=()):
        cursor = self.connection.execute(sql, tuple(params))
        self.connection.commit()
        return cursor.lastrowid

    def frame(self, sql, params=()):
        return pd.read_sql_query(sql, self.connection, params=tuple(params))


def make_services(tmp_path):
    db = SQLiteDB(tmp_path / "clip_pipeline.db")
    db.execute(
        """CREATE TABLE IF NOT EXISTS media_assets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT,
            source_path TEXT
        )"""
    )
    transcripts = LocalWhisperProductionService(db)
    production = ProductionPipelineService(db)
    transcript_id = transcripts.create_transcript("Test stream")
    transcripts.add_segments(
        transcript_id,
        [
            {"start": 10, "end": 20, "text": "A strong reaction", "confidence": 0.9},
            {"start": 20, "end": 30, "text": "The payoff", "confidence": 0.8},
        ],
    )
    return transcripts, production, transcript_id


def test_clip_review_and_idempotent_production_handoff(tmp_path):
    transcripts, production, transcript_id = make_services(tmp_path)
    clip_id = transcripts.add_clip_candidate(
        transcript_id, 10, 30, "Reaction and payoff", "Keep both beats", 85,
        "creator-selection",
    )

    transcripts.set_clip_review_status([clip_id], "Approved")
    first = transcripts.send_clips_to_production(
        [clip_id], export_preset="YouTube Shorts", priority="High"
    )
    second = transcripts.send_clips_to_production([clip_id])

    assert first == second
    candidate = transcripts.clip_candidates(transcript_id).iloc[0]
    assert candidate["review_status"] == "Approved"
    assert int(candidate["sent_to_production"]) == 1

    job = production.clip_jobs().iloc[0]
    assert job["title"] == "Reaction and payoff"
    assert job["priority"] == "High"
    assert job["export_preset"] == "YouTube Shorts"


def test_clip_queue_status_notes_dashboard_and_exports(tmp_path):
    transcripts, production, transcript_id = make_services(tmp_path)
    clip_id = transcripts.add_clip_candidate(
        transcript_id, 10, 20, "Reaction", "Zoom on reaction", 90,
        "creator-selection",
    )
    job_id = transcripts.send_clips_to_production([clip_id])[0]

    production.update_clip_job(job_id, status="Editing", destination="exports/shorts")
    production.add_clip_note(job_id, "Add subtitle emphasis", 14.5, "Creator")

    assert production.clip_job(job_id)["status"] == "Editing"
    assert production.clip_notes(job_id).iloc[0]["body"] == "Add subtitle emphasis"
    assert production.clip_dashboard()["editing"] == 1

    csv_path = tmp_path / "queue.csv"
    json_path = tmp_path / "queue.json"
    edl_path = tmp_path / "queue.edl"
    production.export_clip_jobs(str(csv_path), "CSV")
    production.export_clip_jobs(str(json_path), "JSON")
    production.export_clip_jobs(str(edl_path), "EDL")

    assert csv_path.exists()
    assert "Reaction" in json_path.read_text(encoding="utf-8")
    assert "FROM CLIP NAME: Reaction" in edl_path.read_text(encoding="utf-8")


def test_rejected_clip_cannot_enter_production(tmp_path):
    transcripts, _, transcript_id = make_services(tmp_path)
    clip_id = transcripts.add_clip_candidate(
        transcript_id, 10, 20, "Rejected", "Do not use", 10,
        "creator-selection",
    )
    transcripts.set_clip_review_status([clip_id], "Rejected")

    try:
        transcripts.send_clips_to_production([clip_id])
    except ValueError as exc:
        assert "Rejected clips" in str(exc)
    else:
        raise AssertionError("Rejected clip was sent to production")
