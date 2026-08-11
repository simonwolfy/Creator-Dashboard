from __future__ import annotations

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
    db = SQLiteDB(tmp_path / "transcript_discovery.db")
    db.execute(
        """CREATE TABLE IF NOT EXISTS media_assets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT,
            source_path TEXT
        )"""
    )
    service = LocalWhisperProductionService(db)
    transcript_id = service.create_transcript("Discovery stream")
    service.add_segments(
        transcript_id,
        [
            {"start": 0, "end": 7, "text": "We are walking back to the base.", "confidence": .9},
            {"start": 7, "end": 14, "text": "Wait, what? There is a secret tunnel here!", "confidence": .9},
            {"start": 14, "end": 22, "text": "No way, we actually found it. This is insane!", "confidence": .9},
            {"start": 22, "end": 30, "text": "That was funny, bro. Nobody expected this.", "confidence": .9},
            {"start": 95, "end": 103, "text": "Listen, the boss just attacked us!", "confidence": .9},
            {"start": 103, "end": 112, "text": "What? We survived the boss fight! Amazing!", "confidence": .9},
        ],
    )
    return service, transcript_id


def test_full_transcript_discovery_stages_ranked_review_candidates(tmp_path):
    service, transcript_id = make_service(tmp_path)

    result = service.discover_clip_candidates(
        transcript_id, min_score=40, max_candidates=10
    )

    assert result["segments_scanned"] == 6
    assert result["candidates_created"] >= 2
    assert result["duplicates_removed"] >= 1
    candidates = service.clip_candidates(transcript_id)
    assert set(candidates["source"]) == {"automatic-transcript-discovery-v2"}
    assert set(candidates["review_status"]) == {"Unreviewed"}
    assert not candidates["sent_to_production"].any()
    assert candidates["discovery_rank"].notna().all()
    assert candidates["creator_dna_score"].notna().all()
    assert candidates["discovery_chapter_id"].notna().all()
    assert candidates["reason"].str.contains("Creator approval is required").all()
    assert candidates.iloc[0]["discovery_rank"] >= candidates.iloc[-1]["discovery_rank"]
    run = service.db.frame(
        "SELECT * FROM transcript_discovery_runs WHERE id=?", (result["run_id"],)
    ).iloc[0]
    assert run["status"] == "Completed"
    assert int(run["candidates_created"]) == result["candidates_created"]


def test_rescan_preserves_reviewed_and_manual_clips_without_overlap(tmp_path):
    service, transcript_id = make_service(tmp_path)
    first = service.discover_clip_candidates(
        transcript_id, min_score=40, max_candidates=10
    )
    approved_id = first["candidate_ids"][0]
    service.set_clip_review_status([approved_id], "Approved")
    manual_id = service.add_clip_candidate(
        transcript_id, 94, 113, "Creator pick", "Keep this exact moment", 99,
        "creator-selection",
    )

    second = service.discover_clip_candidates(
        transcript_id, min_score=40, max_candidates=10
    )

    rows = service.clip_candidates(transcript_id)
    assert approved_id in set(rows["id"])
    assert manual_id in set(rows["id"])
    assert rows.loc[rows["id"] == approved_id, "review_status"].iloc[0] == "Approved"
    new_auto = rows[
        (rows["source"] == "automatic-transcript-discovery-v2")
        & (rows["id"] != approved_id)
    ]
    approved = rows[rows["id"] == approved_id].iloc[0]
    for _, row in new_auto.iterrows():
        overlap = service._interval_overlap_ratio(
            (float(row["start_seconds"]), float(row["end_seconds"])),
            (float(approved["start_seconds"]), float(approved["end_seconds"])),
        )
        assert overlap < .55
    assert second["duplicates_removed"] >= 1


def test_empty_transcript_discovery_records_completed_run(tmp_path):
    service, _ = make_service(tmp_path)
    transcript_id = service.create_transcript("Empty stream")

    result = service.discover_clip_candidates(transcript_id)

    assert result["segments_scanned"] == 0
    assert result["candidates_created"] == 0
    assert service.clip_candidates(transcript_id).empty


def test_discovery_windows_stay_inside_semantic_chapters(tmp_path):
    service, transcript_id = make_service(tmp_path)
    first = service.create_manual_chapter(transcript_id, 0, 30, "Tunnel discovery")
    second = service.create_manual_chapter(transcript_id, 95, 112, "Boss fight")

    service.discover_clip_candidates(transcript_id, min_score=40, max_candidates=10)

    candidates = service.clip_candidates(transcript_id)
    assert {first, second}.issubset(set(candidates["discovery_chapter_id"].dropna()))
    chapter_ranges = {
        first: (0.0, 30.0),
        second: (95.0, 112.0),
    }
    for _, candidate in candidates.iterrows():
        chapter_id = int(candidate["discovery_chapter_id"])
        chapter_start, chapter_end = chapter_ranges[chapter_id]
        assert float(candidate["start_seconds"]) >= chapter_start
        assert float(candidate["end_seconds"]) <= chapter_end
        assert float(candidate["suggested_start_seconds"]) >= chapter_start
        assert float(candidate["suggested_end_seconds"]) <= chapter_end
