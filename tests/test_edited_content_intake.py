from __future__ import annotations

import json
from pathlib import Path

from creator_intelligence.data.database import Database
from creator_intelligence.services.edited_content_intake import EditedContentIntakeService
from creator_intelligence.services.production_management import ProductionManagementService
from creator_intelligence.services.publishing_planner import PublishingPlannerService


def make_service(tmp_path: Path) -> tuple[Database, PublishingPlannerService, EditedContentIntakeService]:
    db = Database(tmp_path / "edited-content.db")
    db.migrate()
    production = ProductionManagementService(db)
    publishing = PublishingPlannerService(db, production)
    return db, publishing, EditedContentIntakeService(db, publishing)


def test_ready_folder_creates_neutral_draft_without_touching_original(tmp_path):
    db, publishing, service = make_service(tmp_path)
    ready = tmp_path / "ready"
    ready.mkdir()
    video = ready / "my-finished-video.mp4"
    original = b"finished video bytes"
    video.write_bytes(original)

    folder_id = service.add_folder(str(ready))
    first = service.scan_folder(folder_id, probe_metadata=False)
    second = service.scan_folder(folder_id, probe_metadata=False)

    assert first["intake_created"] == 1
    assert second["intake_created"] == 0
    assert len(service.items()) == 1
    assert video.read_bytes() == original
    intake = service.items().iloc[0]
    assert intake["title"] == "my finished video"
    assert intake["state"] == "Needs review"
    assert intake["learning_status"] == "Neutral"
    assert intake["publishing_status"] == "Draft"
    assert publishing.item(int(intake["publishing_item_id"]))["planned_publish_at"] is None
    events = db.frame(
        "SELECT event_type,evidence_polarity,evidence_weight FROM creator_learning_events"
    )
    assert events.to_dict("records") == [
        {
            "event_type": "edited_content_imported",
            "evidence_polarity": "neutral",
            "evidence_weight": 0.0,
        }
    ]


def test_sidecar_edit_approval_and_schedule_feed_creator_dna(tmp_path):
    db, publishing, service = make_service(tmp_path)
    ready = tmp_path / "ready"
    ready.mkdir()
    (ready / "export.mp4").write_bytes(b"video")
    (ready / "export.json").write_text(
        json.dumps(
            {
                "title": "The Original Approved Title",
                "description": "A prepared description.",
                "platform": "TikTok",
                "content_type": "Short",
                "planned_publish_at": "2026-09-01T18:00:00",
            }
        ),
        encoding="utf-8",
    )
    folder_id = service.add_folder(str(ready))
    service.scan_folder(folder_id, probe_metadata=False)
    intake_id = int(service.items().iloc[0]["id"])

    service.update_item(intake_id, title="The Creator Edited This Title")
    service.schedule(intake_id)

    intake = service.item(intake_id)
    publishing_item = publishing.item(int(intake["publishing_item_id"]))
    assert intake["state"] == "Scheduled"
    assert intake["learning_status"] == "Approved"
    assert publishing_item["title"] == "The Creator Edited This Title"
    assert publishing_item["status"] == "Planned"
    assert publishing_item["planned_publish_at"] == "2026-09-01T18:00:00"
    events = db.frame(
        """SELECT event_type,evidence_polarity FROM creator_learning_events
           ORDER BY id"""
    ).to_dict("records")
    assert events == [
        {"event_type": "edited_content_imported", "evidence_polarity": "neutral"},
        {"event_type": "title_edited", "evidence_polarity": "neutral"},
        {"event_type": "edited_content_approved", "evidence_polarity": "positive"},
        {"event_type": "edited_content_scheduled", "evidence_polarity": "neutral"},
    ]


def test_same_video_in_two_ready_folders_is_not_queued_twice(tmp_path):
    _, _, service = make_service(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "copy-one.mp4").write_bytes(b"identical final export")
    (second / "copy-two.mp4").write_bytes(b"identical final export")

    service.scan_folder(service.add_folder(str(first)), probe_metadata=False)
    result = service.scan_folder(service.add_folder(str(second)), probe_metadata=False)

    assert result["duplicates"] == 1
    assert len(service.items()) == 1


def test_removed_original_is_marked_missing_not_deleted_from_history(tmp_path):
    _, _, service = make_service(tmp_path)
    ready = tmp_path / "ready"
    ready.mkdir()
    video = ready / "finished.mp4"
    video.write_bytes(b"video")
    folder_id = service.add_folder(str(ready))
    service.scan_folder(folder_id, probe_metadata=False)

    video.unlink()
    result = service.scan_folder(folder_id, probe_metadata=False)

    assert result["missing"] == 1
    assert service.items().iloc[0]["state"] == "Missing"


def test_connected_published_statistics_mark_intake_measured(tmp_path):
    db, publishing, service = make_service(tmp_path)
    db.execute(
        """CREATE TABLE creator_published_titles(
            id INTEGER PRIMARY KEY AUTOINCREMENT,platform TEXT,content_type TEXT,
            title TEXT,published_at TEXT,views INTEGER,likes INTEGER,comments INTEGER,
            shares INTEGER,reach INTEGER,watch_time REAL,source_video_id TEXT,
            updated_at TEXT
        )"""
    )
    ready = tmp_path / "ready"
    ready.mkdir()
    (ready / "published.mp4").write_bytes(b"video")
    service.scan_folder(service.add_folder(str(ready)), probe_metadata=False)
    intake_id = int(service.items().iloc[0]["id"])
    db.execute(
        """INSERT INTO creator_published_titles(
            platform,content_type,title,published_at,views,likes,comments,shares,
            reach,watch_time,source_video_id,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "tiktok", "short", "Published title", "2026-09-02T12:00:00",
            1000, 100, 12, 4, 1200, 300, "post-123", "2026-09-03T12:00:00",
        ),
    )

    connected = service.connect_published_content(intake_id, "post-123")

    assert connected["state"] == "Published"
    assert connected["learning_status"] == "Measured"
    assert connected["source_content_id"] == "post-123"
    assert publishing.item(int(connected["publishing_item_id"]))["status"] == "Published"
    outcome = db.frame(
        """SELECT evidence_polarity,evidence_weight,metadata_json
           FROM creator_learning_events
           WHERE event_type='edited_content_outcome_connected'"""
    ).iloc[0]
    assert outcome["evidence_polarity"] == "neutral"
    assert outcome["evidence_weight"] == 1
    assert json.loads(outcome["metadata_json"])["views"] == 1000


def test_rejecting_intake_is_explicit_negative_evidence(tmp_path):
    db, publishing, service = make_service(tmp_path)
    ready = tmp_path / "ready"
    ready.mkdir()
    (ready / "not-this-one.mp4").write_bytes(b"video")
    service.scan_folder(service.add_folder(str(ready)), probe_metadata=False)
    intake_id = int(service.items().iloc[0]["id"])

    rejected = service.reject(intake_id)

    assert rejected["state"] == "Rejected"
    assert rejected["learning_status"] == "Negative"
    assert publishing.item(int(rejected["publishing_item_id"]))["status"] == "Skipped"
    event = db.frame(
        """SELECT evidence_polarity,evidence_weight FROM creator_learning_events
           WHERE event_type='edited_content_rejected'"""
    ).iloc[0]
    assert event["evidence_polarity"] == "negative"
    assert event["evidence_weight"] == 2
