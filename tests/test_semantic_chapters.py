from __future__ import annotations

import json
import sqlite3

import pandas as pd

from creator_intelligence.services.local_whisper_transcripts import (
    LocalWhisperTranscriptService,
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
    db = SQLiteDB(tmp_path / "semantic_chapters.db")
    db.execute(
        """CREATE TABLE IF NOT EXISTS media_assets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT,
            source_path TEXT
        )"""
    )
    service = LocalWhisperTranscriptService(db)
    transcript_id = service.create_transcript("Long stream")
    service.add_segments(
        transcript_id,
        [
            {
                "start": 0, "end": 45,
                "text": "Hey hey hey, you guys, um, okay yeah.",
                "confidence": .86,
            },
            {
                "start": 45, "end": 90,
                "text": "We found a hidden tunnel beneath hydroponics.",
                "confidence": .91,
            },
            {
                "start": 90, "end": 135,
                "text": "The colonists discovered ancient machinery in the tunnel.",
                "confidence": .90,
            },
            {
                "start": 135, "end": 180,
                "text": "The hydroponics tunnel leads into a sealed laboratory.",
                "confidence": .89,
            },
            {
                "start": 180, "end": 225,
                "text": "We found experimental drones inside the laboratory.",
                "confidence": .88,
            },
            {
                "start": 300, "end": 345,
                "text": "Now we need to defend the northern base from raiders.",
                "confidence": .87,
            },
            {
                "start": 345, "end": 390,
                "text": "The raiders attacked the northern gate during the storm.",
                "confidence": .90,
            },
            {
                "start": 390, "end": 435,
                "text": "Run run run! We are out of ammo near the gate!",
                "confidence": .92,
            },
            {
                "start": 435, "end": 480,
                "text": "The armor squad survived the raider assault.",
                "confidence": .91,
            },
        ],
    )
    return service, transcript_id


def test_semantic_chapters_reject_repeated_filler_titles(tmp_path):
    service, transcript_id = make_service(tmp_path)

    chapters = service.build_chapters(
        transcript_id,
        target_minutes=4,
        minimum_minutes=2,
        maximum_minutes=8,
    )

    assert len(chapters) == 2
    assert set(chapters["source"]) == {"semantic-v2"}
    rejected = {
        "Hey Hey Hey", "You Guys", "It's The", "I'm Not Sure",
        "Wait Wait Wait", "Run Run Run", "Said The Stream", "It's Not Bad",
    }
    assert not (set(chapters["title"]) & rejected)
    assert any(
        token in " ".join(chapters["title"]).lower()
        for token in ("tunnel", "hydroponics", "laboratory", "drones")
    )
    assert any(
        token in " ".join(chapters["title"]).lower()
        for token in ("ammo", "raider", "attack", "base")
    )
    blocked_keywords = {"the", "you", "your", "yeah", "okay", "hey", "guys"}
    for _, chapter in chapters.iterrows():
        assert not (set(json.loads(chapter["keywords_json"])) & blocked_keywords)
        assert not str(chapter["summary"]).lower().startswith("hey hey")
        assert 0.0 < float(chapter["confidence"]) <= .95


def test_rebuild_preserves_manual_chapter_and_excludes_its_range(tmp_path):
    service, transcript_id = make_service(tmp_path)
    manual_id = service.create_manual_chapter(
        transcript_id, 0, 90, "Creator Approved Opening"
    )
    service.db.execute(
        "UPDATE transcript_chapters SET review_status='Reviewed' WHERE id=?",
        (manual_id,),
    )

    first = service.build_chapters(
        transcript_id,
        target_minutes=3,
        minimum_minutes=1,
        maximum_minutes=6,
    )
    second = service.build_chapters(
        transcript_id,
        target_minutes=3,
        minimum_minutes=1,
        maximum_minutes=6,
    )

    manual = second[second["id"] == manual_id].iloc[0]
    assert manual["title"] == "Creator Approved Opening"
    assert manual["source"] == "manual"
    assert manual["review_status"] == "Reviewed"
    automatic = second[second["source"] == "semantic-v2"]
    assert not automatic.empty
    assert all(
        not (
            float(row["start_seconds"]) < 90
            and float(row["end_seconds"]) > 0
        )
        for _, row in automatic.iterrows()
    )
    assert list(second["chapter_index"]) == list(range(len(second)))
    assert len(first) == len(second)


def test_filler_only_chapter_requests_review_instead_of_inventing_title(tmp_path):
    service, _ = make_service(tmp_path)
    transcript_id = service.create_transcript("Filler only")
    service.add_segments(
        transcript_id,
        [
            {"start": 0, "end": 30, "text": "Hey hey hey."},
            {"start": 30, "end": 60, "text": "You guys, uh, okay."},
            {"start": 60, "end": 90, "text": "Wait wait wait."},
        ],
    )

    chapter = service.build_chapters(
        transcript_id,
        target_minutes=1,
        minimum_minutes=.5,
        maximum_minutes=2,
    ).iloc[0]

    assert chapter["title"].endswith("Needs Review")
    assert json.loads(chapter["keywords_json"]) == []
    assert "Insufficient semantic context" in chapter["summary"]
