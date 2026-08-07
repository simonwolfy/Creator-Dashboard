from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from creator_intelligence.services.production_management import ProductionManagementService


CLIP_JOB_STATUSES = (
    "New", "Ready", "Editing", "Review", "Approved",
    "Rendering", "Finished", "Archived",
)
CLIP_EXPORT_PRESETS = (
    "YouTube Shorts", "TikTok", "Instagram Reels",
    "YouTube Longform", "Podcast", "Custom",
)


class ProductionPipelineService(ProductionManagementService):
    """Production management plus transcript-driven clip jobs."""

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

    def clip_jobs(self, status: str | None = None):
        sql = """SELECT j.id,j.clip_candidate_id,j.transcript_id,
                        t.title AS transcript_title,j.title,j.start_seconds,
                        j.end_seconds,printf('%02d:%02d:%02d',
                        CAST(j.start_seconds AS INTEGER)/3600,
                        (CAST(j.start_seconds AS INTEGER)%3600)/60,
                        CAST(j.start_seconds AS INTEGER)%60) || '–' ||
                        printf('%02d:%02d:%02d',
                        CAST(j.end_seconds AS INTEGER)/3600,
                        (CAST(j.end_seconds AS INTEGER)%3600)/60,
                        CAST(j.end_seconds AS INTEGER)%60) AS time_range,
                        j.status,j.priority,e.name AS editor,j.export_preset,
                        j.destination,j.source_reason,
                        (SELECT COUNT(*) FROM production_clip_notes n
                         WHERE n.clip_job_id=j.id AND n.status='Open') AS open_notes,
                        j.updated_at
                 FROM production_clip_jobs j
                 LEFT JOIN transcripts t ON t.id=j.transcript_id
                 LEFT JOIN editors e ON e.id=j.editor_id"""
        params: list[object] = []
        if status and status != "All":
            sql += " WHERE j.status=?"
            params.append(status)
        sql += """ ORDER BY
            CASE j.priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2
                 WHEN 'Normal' THEN 3 ELSE 4 END,
            CASE j.status WHEN 'Review' THEN 1 WHEN 'Ready' THEN 2
                 WHEN 'Editing' THEN 3 WHEN 'New' THEN 4 ELSE 5 END,
            j.updated_at DESC"""
        return self.db.frame(sql, params)

    def clip_job(self, job_id: int):
        frame = self.db.frame(
            "SELECT * FROM production_clip_jobs WHERE id=?", (int(job_id),)
        )
        if frame.empty:
            raise KeyError(job_id)
        return frame.iloc[0].to_dict()

    def update_clip_job(self, job_id: int, **changes):
        allowed = {
            "title", "status", "priority", "editor_id",
            "export_preset", "destination", "source_reason",
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        if values.get("status") and values["status"] not in CLIP_JOB_STATUSES:
            raise ValueError(values["status"])
        if values.get("export_preset") and values["export_preset"] not in CLIP_EXPORT_PRESETS:
            raise ValueError(values["export_preset"])
        if not values:
            return self.clip_job(job_id)
        values["updated_at"] = datetime.now().isoformat()
        columns = list(values)
        self.db.execute(
            "UPDATE production_clip_jobs SET "
            + ",".join(f"{column}=?" for column in columns)
            + " WHERE id=?",
            [values[column] for column in columns] + [int(job_id)],
        )
        return self.clip_job(job_id)

    def add_clip_note(
        self,
        job_id: int,
        body: str,
        timestamp_seconds: float | None = None,
        author_role: str = "Creator",
    ) -> int:
        if not str(body).strip():
            raise ValueError("Note cannot be empty.")
        self.clip_job(job_id)
        return int(self.db.execute(
            """INSERT INTO production_clip_notes(
                clip_job_id,timestamp_seconds,body,author_role,status,created_at
            ) VALUES(?,?,?,?,?,?)""",
            (
                int(job_id), timestamp_seconds, str(body).strip(),
                author_role, "Open", datetime.now().isoformat(),
            ),
        ))

    def clip_notes(self, job_id: int):
        return self.db.frame(
            """SELECT * FROM production_clip_notes
               WHERE clip_job_id=? ORDER BY status,COALESCE(timestamp_seconds,999999),created_at""",
            (int(job_id),),
        )

    def resolve_clip_note(self, note_id: int) -> None:
        self.db.execute(
            """UPDATE production_clip_notes SET status='Resolved',resolved_at=?
               WHERE id=?""",
            (datetime.now().isoformat(), int(note_id)),
        )

    def clip_dashboard(self) -> dict[str, int | float]:
        frame = self.clip_jobs()
        counts = frame["status"].value_counts().to_dict() if not frame.empty else {}
        duration = (
            float((frame["end_seconds"] - frame["start_seconds"]).sum())
            if not frame.empty else 0.0
        )
        return {
            "new": int(counts.get("New", 0)),
            "ready": int(counts.get("Ready", 0)),
            "editing": int(counts.get("Editing", 0)),
            "review": int(counts.get("Review", 0)),
            "rendering": int(counts.get("Rendering", 0)),
            "finished": int(counts.get("Finished", 0)),
            "queued_duration_seconds": round(duration, 2),
        }

    def export_clip_jobs(self, path: str, format_name: str = "CSV") -> str:
        frame = self.clip_jobs()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        normalized = format_name.strip().lower()
        rows = frame.to_dict("records")
        if normalized == "json":
            target.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        elif normalized in {"premiere markers", "resolve markers"}:
            with target.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Name", "Start", "Duration", "Comment", "Color"])
                for row in rows:
                    writer.writerow([
                        row["title"], row["start_seconds"],
                        float(row["end_seconds"]) - float(row["start_seconds"]),
                        row.get("source_reason") or "", "Purple",
                    ])
        elif normalized == "edl":
            lines = ["TITLE: Creator Intelligence Clip Queue", "FCM: NON-DROP FRAME"]
            for index, row in enumerate(rows, start=1):
                lines.extend([
                    f"{index:03d}  AX       V     C        {self._edl_time(row['start_seconds'])} {self._edl_time(row['end_seconds'])} {self._edl_time(0)} {self._edl_time(float(row['end_seconds'])-float(row['start_seconds']))}",
                    f"* FROM CLIP NAME: {row['title']}",
                ])
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            frame.to_csv(target, index=False)
        return str(target)

    @staticmethod
    def _edl_time(seconds: float) -> str:
        frames = int(round(float(seconds) * 30))
        hours, frames = divmod(frames, 108000)
        minutes, frames = divmod(frames, 1800)
        secs, frames = divmod(frames, 30)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"
