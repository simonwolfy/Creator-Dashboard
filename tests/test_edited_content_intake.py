from __future__ import annotations

import json
from pathlib import Path

from creator_intelligence.data.database import Database
from creator_intelligence.services.edited_content_intake import EditedContentIntakeService
from creator_intelligence.services.production_management import ProductionManagementService
from creator_intelligence.services.publishing_planner import PublishingPlannerService
from creator_intelligence.services.local_whisper_production import LocalWhisperProductionService
from creator_intelligence.services.video_processing import VideoProcessingService


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


def test_finished_video_transcription_generates_reviewable_package_without_changing_file(
    tmp_path, monkeypatch
):
    db, publishing, _ = make_service(tmp_path)
    video_processing = VideoProcessingService(db)
    transcripts = LocalWhisperProductionService(db, video_processing)
    service = EditedContentIntakeService(
        db,
        publishing,
        transcript_service=transcripts,
        video_processing_service=video_processing,
    )
    ready = tmp_path / "ready"
    ready.mkdir()
    video = ready / "already-edited.mp4"
    original = b"finished export remains untouched"
    video.write_bytes(original)
    service.scan_folder(service.add_folder(str(ready)), probe_metadata=False)
    intake_id = int(service.items().iloc[0]["id"])

    def fake_run_job(job_id, progress_callback=None):
        job = db.frame("SELECT transcript_id FROM transcript_jobs WHERE id=?", (job_id,)).iloc[0]
        transcripts.add_segments(
            int(job["transcript_id"]),
            [
                {"start": 0, "end": 8, "text": "I found the hidden room and nobody expected it."},
                {"start": 8, "end": 17, "text": "Then the whole plan fell apart and we escaped."},
            ],
        )
        db.execute(
            "UPDATE transcript_jobs SET status='Completed',progress_percent=100 WHERE id=?",
            (job_id,),
        )

    monkeypatch.setattr(transcripts, "run_job", fake_run_job)
    result = service.generate_intelligence(intake_id)

    assert result["status"] == "Ready for review"
    assert result["transcript_id"]
    assert result["clip_candidate_id"]
    assert result["package"]["suggested_title"]
    assert result["package"]["platform_packages"]["youtube_shorts"]["description"]
    assert video.read_bytes() == original
    stored = service.item(intake_id)
    assert stored["intelligence_status"] == "Ready for review"
    assert int(stored["transcript_id"]) == result["transcript_id"]

    applied = service.apply_generated_package(intake_id, result["package"])
    assert applied["title"] == result["package"]["suggested_title"]
    assert applied["description"]


def test_finished_video_intelligence_failure_is_saved_for_retry(tmp_path):
    db, publishing, _ = make_service(tmp_path)

    class BrokenTranscripts:
        def queue_transcription(self, *args, **kwargs):
            raise RuntimeError("Whisper model unavailable")

    class FakeVideoProcessing:
        def import_video(self, *args, **kwargs):
            return 1

    service = EditedContentIntakeService(
        db,
        publishing,
        transcript_service=BrokenTranscripts(),
        video_processing_service=FakeVideoProcessing(),
    )
    ready = tmp_path / "ready"
    ready.mkdir()
    (ready / "retry-me.mp4").write_bytes(b"video")
    service.scan_folder(service.add_folder(str(ready)), probe_metadata=False)
    intake_id = int(service.items().iloc[0]["id"])

    try:
        service.generate_intelligence(intake_id)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected transcription failure")

    stored = service.item(intake_id)
    assert stored["intelligence_status"] == "Failed"
    assert "Whisper model unavailable" in stored["intelligence_error"]
