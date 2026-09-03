from __future__ import annotations

import sqlite3

import pandas as pd

from creator_intelligence.core.credential_vault import MemoryCredentialBackend
from creator_intelligence.services.content_rollout import ContentRolloutService


class DB:
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


class Stub:
    pass


def service(tmp_path):
    return ContentRolloutService(DB(tmp_path / "rollout.db"), Stub(), Stub())


def test_folder_intake_deduplicates_and_records_supported_clips(tmp_path):
    rollout = service(tmp_path)
    folder = tmp_path / "August"
    folder.mkdir()
    (folder / "aug short 1.mov").write_bytes(b"video")
    (folder / "notes.txt").write_text("ignore", encoding="utf-8")

    first = rollout.queue_folder(folder)
    second = rollout.queue_folder(folder)

    assert len(first["queued"]) == 1
    assert first["unsupported"] == [str(folder / "notes.txt")]
    assert len(second["duplicates"]) == 1
    assert rollout.job(first["queued"][0])["status"] == "Queued"


def test_watch_folder_restart_recovery_and_retry_states(tmp_path):
    rollout = service(tmp_path)
    folder = tmp_path / "June"
    folder.mkdir()
    clip = folder / "june short 2.mp4"
    clip.write_bytes(b"video")
    watched = rollout.add_watch_folder(folder)
    job_id = watched["queued"][0]
    rollout.db.execute(
        "UPDATE content_analysis_jobs SET status='Running' WHERE id=?", (job_id,)
    )

    rollout.recover_interrupted_jobs()
    assert rollout.job(job_id)["status"] == "Retrying"
    rollout.cancel(job_id)
    assert rollout.job(job_id)["status"] == "Cancelled"
    rollout.retry(job_id)
    assert rollout.job(job_id)["status"] == "Retrying"


def test_thumbnail_recommendations_are_versioned_and_reproducible(tmp_path):
    rollout = service(tmp_path)
    frames = rollout.recommend_thumbnail_frames(12, 40)

    assert len(frames) == 3
    assert set(frames["intelligence_version"]) == {"creator-packaging-v6"}
    assert frames.iloc[0]["reason"] == "Likely action or reaction peak"


def test_drive_queue_uses_metadata_without_downloading(tmp_path):
    rollout = service(tmp_path)
    rollout.db.execute(
        """CREATE TABLE google_drive_files(
           drive_file_id TEXT PRIMARY KEY,mapping_id INTEGER,name TEXT,relative_path TEXT,
           mime_type TEXT,available INTEGER,md5_checksum TEXT,modified_time TEXT)"""
    )
    rollout.db.execute(
        """INSERT INTO google_drive_files VALUES(
           'drive-1',8,'aug short 1.mov','August/aug short 1.mov','video/quicktime',
           1,'checksum','2026-08-01')"""
    )

    result = rollout.queue_drive_files(8)

    assert len(result["queued"]) == 1
    job = rollout.job(result["queued"][0])
    assert job["source_provider"] == "Google Drive"
    assert job["source_key"] == "drive-1"
    assert job["source_path"] == "gdrive://drive-1"
