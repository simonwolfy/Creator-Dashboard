from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from creator_intelligence.services.local_whisper_transcripts import LocalWhisperTranscriptService


class SQLiteDB:
    def __init__(self, path):
        self.path = str(path)
        self.connection = sqlite3.connect(self.path)

    def execute(self, sql, params=()):
        cursor = self.connection.execute(sql, tuple(params))
        self.connection.commit()
        return cursor.lastrowid

    def frame(self, sql, params=()):
        return pd.read_sql_query(sql, self.connection, params=tuple(params))


def make_service(tmp_path):
    db = SQLiteDB(tmp_path / "transcripts.db")
    db.execute(
        """CREATE TABLE IF NOT EXISTS media_assets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT,
            source_path TEXT
        )"""
    )
    service = LocalWhisperTranscriptService(db)
    transcript_id = service.create_transcript("Test stream")
    service.add_segments(
        transcript_id,
        [
            {"start": 0, "end": 10, "text": "Hello from the first segment", "confidence": 0.8},
            {"start": 15, "end": 25, "text": "Second segment has more words", "confidence": 0.6},
            {"start": 40, "end": 50, "text": "Final segment", "confidence": 0.9},
        ],
    )
    return service, transcript_id


def test_statistics_measure_speech_silence_and_confidence(tmp_path):
    service, transcript_id = make_service(tmp_path)
    stats = service.transcript_statistics(transcript_id)

    assert stats["segment_count"] == 3
    assert stats["speaking_seconds"] == 30.0
    assert stats["silence_seconds"] == 20.0
    assert stats["silence_percent"] == 40.0
    assert stats["longest_pause_seconds"] == 15.0
    assert stats["average_confidence"] == pytest.approx(0.7667, abs=0.0001)


def test_edit_review_and_speaker_foundation(tmp_path):
    service, transcript_id = make_service(tmp_path)
    segment_id = int(service.segments(transcript_id).iloc[0]["id"])

    updated = service.update_segment(
        segment_id,
        text="Corrected transcript text",
        speaker="Streamer",
        review_status="Reviewed",
    )

    assert updated["text"] == "Corrected transcript text"
    assert updated["speaker"] == "Streamer"
    assert service.speakers(transcript_id).iloc[0]["display_name"] == "Streamer"
    review = service.db.frame(
        "SELECT review_status FROM transcript_segment_reviews WHERE segment_id=?",
        (segment_id,),
    )
    assert review.iloc[0]["review_status"] == "Reviewed"


def test_split_merge_and_delete_segments(tmp_path):
    service, transcript_id = make_service(tmp_path)
    first_id = int(service.segments(transcript_id).iloc[0]["id"])

    left, right = service.split_segment(first_id, 5, "Hello from", "the first segment")
    assert left["end_seconds"] == 5
    assert right["start_seconds"] == 5

    merged = service.merge_segments(int(left["id"]), int(right["id"]))
    assert merged["text"] == "Hello from the first segment"
    assert len(service.segments(transcript_id)) == 3

    service.delete_segment(int(service.segments(transcript_id).iloc[-1]["id"]))
    assert service.segments(transcript_id)["segment_index"].tolist() == [0, 1]


def test_manual_chapter_editing(tmp_path):
    service, transcript_id = make_service(tmp_path)
    first = service.create_manual_chapter(transcript_id, 0, 25, "Opening")
    second = service.split_chapter(first, 12.5, "Opening Part Two")
    service.rename_chapter(first, "New Opening")

    chapters = service.chapters(transcript_id)
    assert chapters["title"].tolist() == ["New Opening", "Opening Part Two"]

    service.merge_chapters(first, second, "Merged Opening")
    chapters = service.chapters(transcript_id)
    assert chapters["title"].tolist() == ["Merged Opening"]
    assert float(chapters.iloc[0]["end_seconds"]) == 25.0


def test_semantic_and_clip_foundation_tables_exist(tmp_path):
    service, transcript_id = make_service(tmp_path)
    clip_id = service.add_clip_candidate(
        transcript_id, 2, 8, "Funny moment", "Strong reaction", 0.82, "transcript"
    )
    assert clip_id > 0
    tables = service.db.frame(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('transcript_embeddings','transcript_clip_candidates','transcript_speakers')"
    )
    assert set(tables["name"]) == {
        "transcript_embeddings",
        "transcript_clip_candidates",
        "transcript_speakers",
    }
