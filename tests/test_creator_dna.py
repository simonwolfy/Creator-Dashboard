from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

from creator_intelligence.services.creator_dna import CreatorDNAService


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
    db = SQLiteDB(tmp_path / "creator_dna.db")
    db.execute(
        """CREATE TABLE transcript_clip_candidates(
            id INTEGER PRIMARY KEY,
            title TEXT,start_seconds REAL,end_seconds REAL,review_status TEXT,
            hook_score REAL,humor_score REAL,surprise_score REAL,emotion_score REAL,
            quote_score REAL,viral_score REAL,retention_estimate REAL,
            suggested_title TEXT,suggested_caption TEXT,caption_style TEXT,
            suggested_hashtags_json TEXT
        )"""
    )
    db.execute(
        """CREATE TABLE production_clip_jobs(
            id INTEGER PRIMARY KEY,clip_candidate_id INTEGER
        )"""
    )
    rows = [
        (1,"Secret",10,30,"Approved",80,20,75,60,82,78,76,
         "The Secret I Almost Missed","Did you know this was here?",
         "conversational-engagement",json.dumps(["#RimWorld","#GamingShorts"])),
        (2,"Fail",40,55,"Approved",70,68,55,72,75,74,73,
         "I Knew This Was a Bad Idea","Would you have done the same?",
         "conversational-engagement",json.dumps(["#RimWorld","#GamingFails"])),
        (3,"Pending",60,70,"Unreviewed",50,10,20,15,60,45,61,
         "Wait Until You See This","What happens next?",
         "question",json.dumps(["#GamingShorts"])),
    ]
    for row in rows:
        db.execute(
            "INSERT INTO transcript_clip_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
    return CreatorDNAService(db)


def test_rebuild_profile_learns_from_approved_clips(tmp_path):
    service = make_service(tmp_path)
    profile = service.rebuild_profile()

    assert profile["approved_clips"] == 2
    assert profile["average_clip_length"] == 17.5
    assert profile["average_hook"] == 75.0
    assert profile["preferred_caption_style"] == "conversational-engagement"
    assert "#RimWorld" in profile["favorite_hashtags"]
    assert profile["packaging_confidence"] == 25.0


def test_learning_events_persist(tmp_path):
    service = make_service(tmp_path)
    event_id = service.record_event(
        "approved", clip_id=2, old_value="Unreviewed", new_value="Approved"
    )

    events = service.learning_events()
    assert int(events.iloc[0]["id"]) == event_id
    assert events.iloc[0]["event_type"] == "approved"
    assert int(events.iloc[0]["clip_id"]) == 2


def test_recommendations_surface_backlog_and_production_actions(tmp_path):
    service = make_service(tmp_path)
    service.rebuild_profile()
    recommendations = service.recommendations()

    keys = set(recommendations["recommendation_key"])
    assert "review-backlog" in keys
    assert "approved-ready" in keys
    assert recommendations.iloc[0]["priority"] >= recommendations.iloc[-1]["priority"]


def test_learning_events_are_immutable_and_profile_replays_the_ledger(tmp_path):
    service = make_service(tmp_path)
    original = service.rebuild_profile()
    event_id = int(service.learning_events().iloc[0]["id"])

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        service.db.execute(
            "UPDATE creator_learning_events SET new_value='Changed' WHERE id=?",
            (event_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        service.db.execute("DELETE FROM creator_learning_events WHERE id=?", (event_id,))

    service.db.execute(
        """UPDATE transcript_clip_candidates
           SET review_status='Rejected',suggested_title='Mutable table changed' WHERE id=1"""
    )
    replayed = service.rebuild_profile()
    assert replayed["approved_clips"] == original["approved_clips"] == 2
    assert replayed["average_hook"] == original["average_hook"] == 75.0
    assert replayed["preferred_title_style"] == original["preferred_title_style"]
    service.db.execute("DELETE FROM creator_profiles")
    restored = service.creator_dna()
    for key in (
        "approved_clips", "rejected_clips", "average_hook",
        "preferred_title_style", "favorite_hashtags", "source_event_count",
    ):
        assert restored[key] == replayed[key]


def test_title_profile_separates_positive_negative_and_neutral_evidence(tmp_path):
    service = CreatorDNAService(SQLiteDB(tmp_path / "feedback.db"))
    service.record_event(
        "package_approved", package_id="approved", field_name="decision",
        metadata={"copy": {"title": "We Found the Hidden Tunnel"}},
    )
    service.record_event(
        "package_rejected", package_id="rejected", field_name="decision",
        metadata={"copy": {"title": "EPIC GAMING MOMENT"}},
    )
    service.record_event(
        "title_alternative_selected", package_id="selected", field_name="title",
        new_value="Could This Be the Tunnel?",
    )
    service.record_event(
        "title_edited", package_id="edited", field_name="title",
        old_value="Bad Original", new_value="My Better Tunnel Title",
    )

    profile = service.title_style_profile()
    assert profile["positive_count"] == 2
    assert profile["negative_count"] == 2
    assert profile["neutral_count"] == 1
    assert "epic" in profile["avoided_words"]
    assert "better" in profile["preferred_words"]

    rebuilt = service.creator_dna()
    assert rebuilt["positive_examples"] == 1
    assert rebuilt["negative_examples"] == 1
    assert rebuilt["neutral_examples"] == 2
    assert rebuilt["source_event_count"] == 4


def test_existing_v1_learning_event_table_upgrades_without_losing_rows(tmp_path):
    db = SQLiteDB(tmp_path / "legacy-feedback.db")
    db.execute(
        """CREATE TABLE creator_learning_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_id INTEGER,event_type TEXT NOT NULL,old_value TEXT,new_value TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL
        )"""
    )
    db.execute(
        """INSERT INTO creator_learning_events(
            clip_id,event_type,old_value,new_value,metadata_json,created_at
        ) VALUES(1,'approved','Unreviewed','Approved','{}','2026-01-01T00:00:00')"""
    )

    service = CreatorDNAService(db)
    service.record_event(
        "package_approved", clip_id=1, package_id="new-package",
        metadata={"copy": {"title": "A New Approved Title"}},
    )

    events = service.learning_events()
    assert len(events) == 2
    assert set(events["event_type"]) == {"approved", "package_approved"}
    assert set(events["schema_version"]) == {"creator-feedback-v1"}
