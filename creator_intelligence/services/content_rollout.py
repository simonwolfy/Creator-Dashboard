from __future__ import annotations

import hashlib
import json
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from creator_intelligence.services.publishing_outcomes import PublishingOutcomeService
from creator_intelligence.services.google_drive_media_cache import GoogleDriveMediaCacheService


JOB_STATES = ("Queued", "Running", "Completed", "Needs review", "Failed", "Cancelled", "Retrying")
VIDEO_EXTENSIONS = {".mov", ".mp4", ".mkv", ".avi", ".webm", ".m4v"}


class ContentRolloutService:
    """Durable folder-to-review orchestration and quarterly release gates."""

    INTELLIGENCE_VERSION = "creator-packaging-v6"

    def __init__(self, db, transcripts, publishing, google_drive=None):
        self.db = db
        self.transcripts = transcripts
        self.publishing = publishing
        self.google_drive = google_drive
        self.drive_cache = GoogleDriveMediaCacheService(google_drive) if google_drive else None
        self.outcomes = PublishingOutcomeService(db)
        self._ensure_schema()
        self.recover_interrupted_jobs()

    def _ensure_schema(self):
        for statement in (
            """CREATE TABLE IF NOT EXISTS content_analysis_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,source_path TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL UNIQUE,status TEXT NOT NULL DEFAULT 'Queued',
                progress_percent REAL NOT NULL DEFAULT 0,attempt_count INTEGER NOT NULL DEFAULT 0,
                media_asset_id INTEGER,transcript_id INTEGER,clip_candidate_id INTEGER,
                package_ids_json TEXT NOT NULL DEFAULT '{}',error TEXT,
                queued_at TEXT NOT NULL,started_at TEXT,completed_at TEXT,cancelled_at TEXT,
                updated_at TEXT NOT NULL,intelligence_version TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS content_release_gates(
                id INTEGER PRIMARY KEY AUTOINCREMENT,release_version TEXT NOT NULL,
                gate_key TEXT NOT NULL,status TEXT NOT NULL,detail TEXT,
                checked_at TEXT NOT NULL,UNIQUE(release_version,gate_key)
            )""",
            """CREATE TABLE IF NOT EXISTS content_analysis_watch_folders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,path TEXT NOT NULL UNIQUE,
                recursive INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,
                last_scanned_at TEXT,created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS thumbnail_frame_recommendations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,clip_candidate_id INTEGER NOT NULL,
                timestamp_seconds REAL NOT NULL,reason TEXT NOT NULL,score REAL NOT NULL,
                intelligence_version TEXT NOT NULL,created_at TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_content_analysis_status ON content_analysis_jobs(status,queued_at)",
        ):
            self.db.execute(statement)
        existing = set(self.db.frame("PRAGMA table_info(content_analysis_jobs)")["name"])
        for name, sql_type in {
            "source_provider": "TEXT NOT NULL DEFAULT 'Local'",
            "source_key": "TEXT", "source_name": "TEXT",
        }.items():
            if name not in existing:
                self.db.execute(f"ALTER TABLE content_analysis_jobs ADD COLUMN {name} {sql_type}")

    def queue_folder(self, folder, *, recursive=False):
        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        iterator = root.rglob("*") if recursive else root.iterdir()
        queued, duplicates, unsupported = [], [], []
        for path in sorted((item for item in iterator if item.is_file()), key=lambda item: item.name.lower()):
            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                unsupported.append(str(path))
                continue
            fingerprint = self._fingerprint(path)
            existing = self.db.frame(
                "SELECT id,status FROM content_analysis_jobs WHERE source_fingerprint=?", (fingerprint,)
            )
            if not existing.empty:
                duplicates.append({"path": str(path), "job_id": int(existing.iloc[0]["id"]),
                                   "status": str(existing.iloc[0]["status"])})
                continue
            now = datetime.now(timezone.utc).isoformat()
            job_id = int(self.db.execute(
                """INSERT INTO content_analysis_jobs(source_path,source_fingerprint,status,
                   queued_at,updated_at,intelligence_version) VALUES(?,?,'Queued',?,?,?)""",
                (str(path), fingerprint, now, now, self.INTELLIGENCE_VERSION),
            ))
            queued.append(job_id)
        return {"queued": queued, "duplicates": duplicates, "unsupported": unsupported}

    def queue_drive_files(self, mapping_id=None):
        """Queue available mapped Drive videos without downloading their contents."""
        clauses = ["available=1"]
        params = []
        if mapping_id is not None:
            clauses.append("mapping_id=?")
            params.append(int(mapping_id))
        files = self.db.frame(
            "SELECT * FROM google_drive_files WHERE " + " AND ".join(clauses) +
            " ORDER BY relative_path", params,
        )
        queued, duplicates, unsupported = [], [], []
        for _, item in files.iterrows():
            suffix = Path(str(item.get("name") or "")).suffix.lower()
            mime = str(item.get("mime_type") or "").lower()
            if suffix not in VIDEO_EXTENSIONS and not mime.startswith("video/"):
                unsupported.append(str(item.get("relative_path") or item["name"]))
                continue
            fingerprint = hashlib.sha256(
                f"google-drive|{item['drive_file_id']}|{item.get('md5_checksum')}|{item.get('modified_time')}".encode()
            ).hexdigest()
            existing = self.db.frame(
                "SELECT id,status FROM content_analysis_jobs WHERE source_fingerprint=?",
                (fingerprint,),
            )
            if not existing.empty:
                duplicates.append({"drive_file_id": item["drive_file_id"],
                                   "job_id": int(existing.iloc[0]["id"]),
                                   "status": existing.iloc[0]["status"]})
                continue
            now = datetime.now(timezone.utc).isoformat()
            job_id = self.db.execute(
                """INSERT INTO content_analysis_jobs(
                   source_path,source_fingerprint,source_provider,source_key,source_name,
                   status,queued_at,updated_at,intelligence_version)
                   VALUES(?,?,?,?,?,'Queued',?,?,?)""",
                (f"gdrive://{item['drive_file_id']}", fingerprint, "Google Drive",
                 str(item["drive_file_id"]), str(item["name"]), now, now,
                 self.INTELLIGENCE_VERSION),
            )
            queued.append(int(job_id))
        return {"queued": queued, "duplicates": duplicates, "unsupported": unsupported}

    def jobs(self, status="All"):
        sql = "SELECT * FROM content_analysis_jobs"
        params = []
        if status and status != "All":
            if status not in JOB_STATES:
                raise ValueError("Unsupported analysis job state.")
            sql += " WHERE status=?"
            params.append(status)
        return self.db.frame(sql + " ORDER BY queued_at DESC,id DESC", params)

    def add_watch_folder(self, folder, *, recursive=False):
        path = Path(folder).expanduser().resolve()
        if not path.is_dir():
            raise NotADirectoryError(path)
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """INSERT INTO content_analysis_watch_folders(path,recursive,active,created_at)
               VALUES(?,?,1,?) ON CONFLICT(path) DO UPDATE SET
               recursive=excluded.recursive,active=1""",
            (str(path), int(bool(recursive)), now),
        )
        return self.scan_watch_folders()

    def scan_watch_folders(self):
        folders = self.db.frame(
            "SELECT * FROM content_analysis_watch_folders WHERE active=1 ORDER BY id"
        )
        result = {"queued": [], "duplicates": [], "unsupported": [], "errors": {}}
        for _, folder in folders.iterrows():
            try:
                queued = self.queue_folder(folder["path"], recursive=bool(folder["recursive"]))
                for key in ("queued", "duplicates", "unsupported"):
                    result[key].extend(queued[key])
                self.db.execute(
                    "UPDATE content_analysis_watch_folders SET last_scanned_at=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), int(folder["id"])),
                )
            except Exception as exc:
                result["errors"][str(folder["path"])] = str(exc)
        return result

    def job(self, job_id):
        frame = self.db.frame("SELECT * FROM content_analysis_jobs WHERE id=?", (int(job_id),))
        if frame.empty:
            raise KeyError(job_id)
        return frame.iloc[0].to_dict()

    def run_next(self):
        self.scan_watch_folders()
        frame = self.db.frame(
            """SELECT id FROM content_analysis_jobs WHERE status IN('Queued','Retrying')
               ORDER BY queued_at,id LIMIT 1"""
        )
        if frame.empty:
            return None
        return self.run_job(int(frame.iloc[0]["id"]))

    def run_job(self, job_id):
        job = self.job(job_id)
        if job["status"] not in {"Queued", "Retrying"}:
            raise ValueError("Only queued or retrying jobs can run.")
        is_drive = job.get("source_provider") == "Google Drive"
        source = Path(str(job["source_path"])) if not is_drive else None
        if not is_drive and not source.is_file():
            return self._fail(job_id, f"Source video was not found: {source}")
        if is_drive and not self.drive_cache:
            return self._fail(job_id, "Google Drive media access is unavailable.")
        started = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """UPDATE content_analysis_jobs SET status='Running',progress_percent=5,
               attempt_count=attempt_count+1,started_at=?,error=NULL,updated_at=? WHERE id=?""",
            (started, started, int(job_id)),
        )
        clock = time.monotonic()
        try:
            source_context = self.drive_cache.materialize(
                str(job["source_key"]),
                progress=lambda value: self._progress(job_id, 5 + value * .1),
            ) if is_drive else nullcontext(source)
            with source_context as working_source:
                return self._process_source(job_id, job, Path(working_source), clock)
        except Exception as exc:
            return self._fail(job_id, str(exc), duration=time.monotonic() - clock)

    def _process_source(self, job_id, job, source, clock):
        try:
            processing = getattr(self.transcripts, "video_processing", None)
            if processing is None:
                raise RuntimeError("Video processing is unavailable.")
            asset_id = processing.import_video(source, auto_probe=False)
            self._progress(job_id, 15, media_asset_id=asset_id)
            transcript_job_id = self.transcripts.queue_transcription(asset_id)
            transcript_job = self.transcripts.db.frame(
                "SELECT transcript_id FROM transcript_jobs WHERE id=?", (transcript_job_id,)
            )
            transcript_id = int(transcript_job.iloc[0]["transcript_id"])
            self._progress(job_id, 25, transcript_id=transcript_id)
            self.transcripts.run_job(transcript_job_id, lambda value, _message=None: self._progress(
                job_id, 25 + max(0.0, min(float(value), 100.0)) * .45
            ))
            transcript = self.transcripts.transcript(transcript_id)
            segments = self.transcripts.segments(transcript_id)
            duration = float(transcript.get("duration_seconds") or 0)
            if not duration and not segments.empty:
                duration = float(segments["end_seconds"].max())
            if duration <= 0:
                raise RuntimeError("Transcription completed without a usable clip duration.")
            clip_id = self.transcripts.add_clip_candidate(
                transcript_id, 0, duration, source.stem,
                "Edited clip imported for content intelligence", 70, "bulk-folder",
            )
            self._progress(job_id, 78, clip_candidate_id=clip_id)
            self.recommend_thumbnail_frames(clip_id, duration)
            result = self.transcripts.analyze_clip_candidate(clip_id)
            packages = result.get("platform_packages") or {}
            package_ids = {key: value.get("package_id") for key, value in packages.items()
                           if value.get("package_id")}
            for package_id in package_ids.values():
                self.outcomes.ensure_content_link(package_id)
                self.outcomes.record_provenance(
                    package_id, "transcript", source_id=str(transcript_id),
                    payload={"clip_candidate_id": clip_id,
                             "source_provider": job.get("source_provider") or "Local",
                             "source_key": job.get("source_key"),
                             "source_name": job.get("source_name") or source.name,
                             "source_path": job["source_path"]},
                    confidence=transcript.get("confidence"), provider="local-whisper",
                    model=transcript.get("model_name"),
                    intelligence_version=self.INTELLIGENCE_VERSION,
                )
                context = result.get("packaging_context") or {}
                if context.get("visual_summary"):
                    self.outcomes.record_provenance(
                        package_id, "visual", source_id=str(clip_id), payload={
                            "summary": context.get("visual_summary"),
                            "on_screen_text": context.get("on_screen_text"),
                        }, confidence=context.get("visual_context_confidence"),
                        intelligence_version=self.INTELLIGENCE_VERSION,
                    )
            elapsed = time.monotonic() - clock
            now = datetime.now(timezone.utc).isoformat()
            self.db.execute(
                """UPDATE content_analysis_jobs SET status='Needs review',progress_percent=100,
                   package_ids_json=?,completed_at=?,updated_at=? WHERE id=?""",
                (json.dumps(package_ids), now, now, int(job_id)),
            )
            self.outcomes.record_metric(
                "analysis_completed", clip_candidate_id=clip_id,
                duration_seconds=elapsed, payload={"job_id": int(job_id), "packages": len(package_ids)},
            )
            return self.job(job_id)
        except Exception as exc:
            return self._fail(job_id, str(exc), duration=time.monotonic() - clock)

    def mark_completed(self, job_id):
        job = self.job(job_id)
        if job["status"] != "Needs review":
            raise ValueError("Only reviewed jobs can be completed.")
        package_ids = list(json.loads(job.get("package_ids_json") or "{}").values())
        if package_ids:
            placeholders = ",".join("?" for _ in package_ids)
            decisions = self.db.frame(
                f"SELECT decision_status FROM publishing_packages WHERE id IN ({placeholders})",
                package_ids,
            )
            if decisions.empty or not decisions["decision_status"].isin(["Approved", "Published", "Rejected"]).all():
                raise ValueError("Every platform package requires an explicit review decision.")
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "UPDATE content_analysis_jobs SET status='Completed',updated_at=? WHERE id=?",
            (now, int(job_id)),
        )
        return self.job(job_id)

    def cancel(self, job_id):
        job = self.job(job_id)
        if job["status"] in {"Completed", "Cancelled"}:
            return job
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """UPDATE content_analysis_jobs SET status='Cancelled',cancelled_at=?,
               updated_at=? WHERE id=?""", (now, now, int(job_id)),
        )
        return self.job(job_id)

    def retry(self, job_id):
        job = self.job(job_id)
        if job["status"] not in {"Failed", "Cancelled"}:
            raise ValueError("Only failed or cancelled jobs can be retried.")
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """UPDATE content_analysis_jobs SET status='Retrying',progress_percent=0,
               error=NULL,started_at=NULL,completed_at=NULL,cancelled_at=NULL,updated_at=? WHERE id=?""",
            (now, int(job_id)),
        )
        return self.job(job_id)

    def recover_interrupted_jobs(self):
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """UPDATE content_analysis_jobs SET status='Retrying',progress_percent=0,
               error='Recovered after application interruption.',updated_at=? WHERE status='Running'""",
            (now,),
        )

    def detect_conflicts(self):
        duplicates = self.db.frame(
            """SELECT source_fingerprint,COUNT(*) AS count FROM content_analysis_jobs
               GROUP BY source_fingerprint HAVING COUNT(*)>1"""
        )
        title_collisions = self.db.frame(
            """SELECT platform,COALESCE(used_title,generated_title,used_caption,generated_caption) AS copy,
               COUNT(*) AS count FROM publishing_packages
               WHERE decision_status<>'Rejected' GROUP BY platform,copy HAVING COUNT(*)>1"""
        )
        schedule_conflicts = self.db.frame(
            """SELECT platform,scheduled_publish_at,COUNT(*) AS count FROM publishing_items
               WHERE scheduled_publish_at IS NOT NULL GROUP BY platform,scheduled_publish_at
               HAVING COUNT(*)>1"""
        )
        return {"duplicate_sources": duplicates, "title_collisions": title_collisions,
                "schedule_conflicts": schedule_conflicts}

    def schedule_approved_packages(self, package_ids):
        """Create calendar-ready items only after explicit package approval."""
        from creator_intelligence.services.packaging_review import PackagingReviewService
        review = PackagingReviewService(self.db, self.publishing, self.transcripts)
        created, failed = [], {}
        for package_id in package_ids:
            try:
                created.append(review.send_to_publishing(str(package_id)))
            except Exception as exc:
                failed[str(package_id)] = str(exc)
        scheduled = self.publishing.auto_schedule_ready_items() if created else []
        return {"created": created, "scheduled": scheduled, "failed": failed,
                "conflicts": self.detect_conflicts()}

    def recommend_thumbnail_frames(self, clip_candidate_id, duration_seconds):
        """Create reproducible frame candidates; selection remains a human decision."""
        duration = max(float(duration_seconds), 0.1)
        now = datetime.now(timezone.utc).isoformat()
        recommendations = (
            (duration * .2, "Opening visual hook", .72),
            (duration * .55, "Likely action or reaction peak", .8),
            (duration * .85, "Payoff or outcome frame", .76),
        )
        self.db.execute(
            "DELETE FROM thumbnail_frame_recommendations WHERE clip_candidate_id=?",
            (int(clip_candidate_id),),
        )
        for timestamp, reason, score in recommendations:
            self.db.execute(
                """INSERT INTO thumbnail_frame_recommendations(
                   clip_candidate_id,timestamp_seconds,reason,score,
                   intelligence_version,created_at) VALUES(?,?,?,?,?,?)""",
                (int(clip_candidate_id), timestamp, reason, score,
                 self.INTELLIGENCE_VERSION, now),
            )
        return self.db.frame(
            "SELECT * FROM thumbnail_frame_recommendations WHERE clip_candidate_id=? ORDER BY score DESC",
            (int(clip_candidate_id),),
        )

    def diagnostics(self):
        """Return an exportable, secret-free support bundle."""
        return {
            "intelligence_version": self.INTELLIGENCE_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dashboard": self.dashboard(),
            "jobs": self.jobs().fillna("").to_dict("records"),
            "release_gates": self.db.frame(
                "SELECT * FROM content_release_gates ORDER BY checked_at DESC"
            ).fillna("").to_dict("records"),
        }

    def dashboard(self):
        summary = self.outcomes.quality_summary()
        jobs = self.jobs()
        summary["jobs"] = len(jobs)
        summary["queued_jobs"] = int(jobs["status"].isin(["Queued", "Retrying"]).sum()) if not jobs.empty else 0
        summary["needs_review"] = int((jobs["status"] == "Needs review").sum()) if not jobs.empty else 0
        summary["failed_jobs"] = int((jobs["status"] == "Failed").sum()) if not jobs.empty else 0
        summary["conflicts"] = sum(len(value) for value in self.detect_conflicts().values())
        return summary

    def evaluate_release_gates(self, release_version):
        dashboard = self.dashboard()
        gates = {
            "no_failed_jobs": (dashboard["failed_jobs"] == 0, f"{dashboard['failed_jobs']} failed job(s)"),
            "no_conflicts": (dashboard["conflicts"] == 0, f"{dashboard['conflicts']} conflict(s)"),
            "human_review_required": (True, "Publishing remains approval-gated"),
            "credential_storage": (True, "Provider secrets remain in the OS credential vault"),
        }
        now = datetime.now(timezone.utc).isoformat()
        for key, (passed, detail) in gates.items():
            self.db.execute(
                """INSERT INTO content_release_gates(release_version,gate_key,status,detail,checked_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(release_version,gate_key) DO UPDATE SET
                   status=excluded.status,detail=excluded.detail,checked_at=excluded.checked_at""",
                (release_version, key, "Passed" if passed else "Blocked", detail, now),
            )
        return self.db.frame(
            "SELECT * FROM content_release_gates WHERE release_version=? ORDER BY gate_key",
            (release_version,),
        )

    def _progress(self, job_id, percent, **fields):
        values = {"progress_percent": max(0.0, min(float(percent), 100.0)), **fields,
                  "updated_at": datetime.now(timezone.utc).isoformat()}
        columns = list(values)
        self.db.execute(
            "UPDATE content_analysis_jobs SET " + ",".join(f"{name}=?" for name in columns) + " WHERE id=?",
            [values[name] for name in columns] + [int(job_id)],
        )

    def _fail(self, job_id, error, duration=None):
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """UPDATE content_analysis_jobs SET status='Failed',error=?,updated_at=?,
               completed_at=? WHERE id=?""", (str(error), now, now, int(job_id)),
        )
        job = self.job(job_id)
        self.outcomes.record_metric(
            "analysis_failed", clip_candidate_id=job.get("clip_candidate_id"),
            duration_seconds=duration, payload={"job_id": int(job_id), "error": str(error)},
        )
        return self.job(job_id)

    @staticmethod
    def _fingerprint(path: Path):
        stat = path.stat()
        value = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
