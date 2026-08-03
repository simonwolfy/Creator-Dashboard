from __future__ import annotations

from datetime import datetime
from typing import Iterable


CLIP_REVIEW_STATUSES = ("Unreviewed", "Approved", "Rejected", "Needs work")


class TranscriptProductionMixin:
    """Creator review and production handoff operations for transcript clips."""

    def _ensure_schema(self):
        super()._ensure_schema()
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS production_clip_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clip_candidate_id INTEGER NOT NULL UNIQUE,
                transcript_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'New',
                priority TEXT NOT NULL DEFAULT 'Normal',
                editor_id INTEGER,
                export_preset TEXT NOT NULL DEFAULT 'YouTube Shorts',
                destination TEXT,
                source_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS production_clip_notes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clip_job_id INTEGER NOT NULL,
                timestamp_seconds REAL,
                body TEXT NOT NULL,
                author_role TEXT NOT NULL DEFAULT 'Creator',
                status TEXT NOT NULL DEFAULT 'Open',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )"""
        )
        self.db.execute(
            """CREATE INDEX IF NOT EXISTS idx_clip_jobs_status
               ON production_clip_jobs(status,priority,updated_at)"""
        )

    def clip_candidates(self, transcript_id: int, review_status: str | None = None):
        sql = """SELECT c.id,c.transcript_id,c.start_seconds,c.end_seconds,
                        c.title,c.reason,c.score,c.source,c.review_status,c.created_at,
                        CASE WHEN j.id IS NULL THEN 0 ELSE 1 END AS sent_to_production,
                        j.id AS production_job_id,j.status AS production_status
                 FROM transcript_clip_candidates c
                 LEFT JOIN production_clip_jobs j ON j.clip_candidate_id=c.id
                 WHERE c.transcript_id=?"""
        params: list[object] = [int(transcript_id)]
        if review_status and review_status != "All":
            sql += " AND c.review_status=?"
            params.append(review_status)
        sql += " ORDER BY c.start_seconds,c.id"
        return self.db.frame(sql, params)

    def set_clip_review_status(self, clip_ids: Iterable[int], status: str) -> int:
        if status not in CLIP_REVIEW_STATUSES:
            raise ValueError(status)
        now = datetime.now().isoformat()
        count = 0
        for clip_id in {int(value) for value in clip_ids}:
            cursor = self.db.execute(
                """UPDATE transcript_clip_candidates
                   SET review_status=?,updated_at=? WHERE id=?""",
                (status, now, clip_id),
            )
            count += int(getattr(cursor, "rowcount", 1) or 0)
        return count

    def send_clips_to_production(
        self,
        clip_ids: Iterable[int],
        *,
        export_preset: str = "YouTube Shorts",
        priority: str = "Normal",
        destination: str | None = None,
    ) -> list[int]:
        now = datetime.now().isoformat()
        created: list[int] = []
        for clip_id in {int(value) for value in clip_ids}:
            frame = self.db.frame(
                "SELECT * FROM transcript_clip_candidates WHERE id=?",
                (clip_id,),
            )
            if frame.empty:
                raise KeyError(clip_id)
            row = frame.iloc[0].to_dict()
            if row.get("review_status") == "Rejected":
                raise ValueError("Rejected clips cannot be sent to production.")
            existing = self.db.frame(
                "SELECT id FROM production_clip_jobs WHERE clip_candidate_id=?",
                (clip_id,),
            )
            if not existing.empty:
                created.append(int(existing.iloc[0]["id"]))
                continue
            job_id = int(self.db.execute(
                """INSERT INTO production_clip_jobs(
                    clip_candidate_id,transcript_id,title,start_seconds,end_seconds,
                    status,priority,export_preset,destination,source_reason,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,'New',?,?,?,?,?,?)""",
                (
                    clip_id,
                    int(row["transcript_id"]),
                    str(row.get("title") or f"Clip {clip_id}"),
                    float(row["start_seconds"]),
                    float(row["end_seconds"]),
                    priority,
                    export_preset,
                    destination,
                    row.get("reason"),
                    now,
                    now,
                ),
            ))
            created.append(job_id)
            self.db.execute(
                """UPDATE transcript_clip_candidates
                   SET review_status='Approved',updated_at=? WHERE id=?""",
                (now, clip_id),
            )
        return created
