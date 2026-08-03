from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Callable


JOB_TYPES = (
    "Probe metadata",
    "Extract audio",
    "Generate thumbnails",
    "Generate proxy",
)


@dataclass(frozen=True)
class ToolStatus:
    ffmpeg_path: str | None
    ffprobe_path: str | None
    available: bool
    message: str


class VideoProcessingService:
    def __init__(
        self,
        db,
        creator_planner=None,
        notifications=None,
        output_root=None,
        ffmpeg_path=None,
        ffprobe_path=None,
    ):
        self.db = db
        self.creator_planner = creator_planner
        self.notifications = notifications
        self.output_root = Path(
            output_root or (Path(db.path).parent / "media_processing")
        )
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_path = (
            ffmpeg_path
            or os.getenv("CREATOR_INTELLIGENCE_FFMPEG")
            or shutil.which("ffmpeg")
        )
        self.ffprobe_path = (
            ffprobe_path
            or os.getenv("CREATOR_INTELLIGENCE_FFPROBE")
            or shutil.which("ffprobe")
        )
        self._cancel = {}
        self._processes = {}
        self._lock = threading.RLock()
        self._ensure_schema()
        self.recover_interrupted_jobs()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS media_assets(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_source_id INTEGER,
                asset_type TEXT DEFAULT 'Video',
                display_name TEXT NOT NULL,
                source_path TEXT NOT NULL UNIQUE,
                file_size_bytes INTEGER,
                duration_seconds REAL,
                width INTEGER,
                height INTEGER,
                frame_rate REAL,
                video_codec TEXT,
                audio_codec TEXT,
                sample_rate INTEGER,
                channels INTEGER,
                container_format TEXT,
                bit_rate INTEGER,
                status TEXT DEFAULT 'Imported',
                probe_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS media_processing_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER NOT NULL,
                job_type TEXT NOT NULL,
                status TEXT DEFAULT 'Queued',
                priority INTEGER DEFAULT 100,
                progress_percent REAL DEFAULT 0,
                progress_seconds REAL DEFAULT 0,
                expected_duration_seconds REAL,
                command_json TEXT,
                settings_json TEXT,
                output_directory TEXT,
                error_message TEXT,
                attempt_count INTEGER DEFAULT 0,
                queued_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                cancelled_at TEXT,
                worker_id TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(media_asset_id) REFERENCES media_assets(id)
            )""",
            """CREATE TABLE IF NOT EXISTS media_artifacts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER NOT NULL,
                job_id INTEGER,
                artifact_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                timestamp_seconds REAL,
                file_size_bytes INTEGER,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(job_id,file_path)
            )""",
            """CREATE TABLE IF NOT EXISTS media_processing_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER,
                event_type TEXT NOT NULL,
                message TEXT,
                detail_json TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_media_jobs_queue
               ON media_processing_jobs(status,priority,queued_at)""",
            """CREATE INDEX IF NOT EXISTS idx_media_artifacts_asset
               ON media_artifacts(media_asset_id,artifact_type,timestamp_seconds)""",
        ]
        for statement in statements:
            self.db.execute(statement)

    def tool_status(self):
        available = bool(self.ffmpeg_path and self.ffprobe_path)
        message = (
            "FFmpeg and FFprobe are available."
            if available
            else (
                "FFmpeg/FFprobe were not found. Install FFmpeg or configure "
                "CREATOR_INTELLIGENCE_FFMPEG and CREATOR_INTELLIGENCE_FFPROBE."
            )
        )
        return ToolStatus(
            self.ffmpeg_path,
            self.ffprobe_path,
            available,
            message,
        )

    def import_video(
        self,
        source_path,
        content_source_id=None,
        display_name=None,
        auto_probe=True,
    ):
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        frame = self.db.frame(
            "SELECT id FROM media_assets WHERE source_path=?",
            (str(path),),
        )
        if not frame.empty:
            return int(frame.iloc[0]["id"])
        now = datetime.now().isoformat()
        asset_id = int(
            self.db.execute(
                """INSERT INTO media_assets(
                    content_source_id,display_name,source_path,file_size_bytes,
                    status,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    content_source_id,
                    display_name or path.name,
                    str(path),
                    path.stat().st_size,
                    "Imported",
                    now,
                    now,
                ),
            )
        )
        self._event(None, "asset_imported", path.name, {"asset_id": asset_id})
        if auto_probe:
            self.queue_job(asset_id, "Probe metadata", priority=10)
        return asset_id

    def assets(self):
        return self.db.frame(
            """SELECT a.*,
                      (SELECT COUNT(*) FROM media_processing_jobs j
                       WHERE j.media_asset_id=a.id) job_count,
                      (SELECT COUNT(*) FROM media_artifacts r
                       WHERE r.media_asset_id=a.id) artifact_count
               FROM media_assets a
               ORDER BY created_at DESC"""
        )

    def asset(self, asset_id):
        frame = self.db.frame(
            "SELECT * FROM media_assets WHERE id=?",
            (int(asset_id),),
        )
        if frame.empty:
            raise KeyError(asset_id)
        return frame.iloc[0].to_dict()

    def jobs(self, status=None):
        sql = """SELECT j.id,j.media_asset_id,a.display_name,j.job_type,j.status,
                        j.priority,ROUND(j.progress_percent,1) progress_percent,
                        j.progress_seconds,j.expected_duration_seconds,
                        j.attempt_count,j.error_message,j.queued_at,j.started_at,
                        j.completed_at,j.output_directory
                 FROM media_processing_jobs j
                 JOIN media_assets a ON a.id=j.media_asset_id"""
        params = []
        if status and status != "All":
            sql += " WHERE j.status=?"
            params.append(status)
        sql += """ ORDER BY CASE j.status
                       WHEN 'Running' THEN 1
                       WHEN 'Queued' THEN 2
                       ELSE 3
                     END,j.priority,j.queued_at"""
        return self.db.frame(sql, params)

    def job(self, job_id):
        frame = self.db.frame(
            "SELECT * FROM media_processing_jobs WHERE id=?",
            (int(job_id),),
        )
        if frame.empty:
            raise KeyError(job_id)
        return frame.iloc[0].to_dict()

    def artifacts(self, asset_id=None):
        sql = """SELECT r.*,a.display_name
                 FROM media_artifacts r
                 JOIN media_assets a ON a.id=r.media_asset_id"""
        params = []
        if asset_id:
            sql += " WHERE r.media_asset_id=?"
            params.append(int(asset_id))
        return self.db.frame(
            sql + " ORDER BY r.created_at DESC,r.timestamp_seconds",
            params,
        )

    def queue_job(self, asset_id, job_type, settings=None, priority=100):
        if job_type not in JOB_TYPES:
            raise ValueError(job_type)
        self.asset(asset_id)
        now = datetime.now().isoformat()
        output_directory = self.output_root / f"asset_{int(asset_id)}"
        output_directory.mkdir(parents=True, exist_ok=True)
        job_id = int(
            self.db.execute(
                """INSERT INTO media_processing_jobs(
                    media_asset_id,job_type,status,priority,settings_json,
                    output_directory,queued_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    int(asset_id),
                    job_type,
                    "Queued",
                    int(priority),
                    json.dumps(settings or {}),
                    str(output_directory),
                    now,
                    now,
                ),
            )
        )
        self._event(job_id, "queued", job_type, settings or {})
        return job_id

    def retry_job(self, job_id):
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE media_processing_jobs
               SET status='Queued',progress_percent=0,progress_seconds=0,
                   error_message=NULL,started_at=NULL,completed_at=NULL,
                   cancelled_at=NULL,worker_id=NULL,updated_at=?
               WHERE id=?""",
            (now, int(job_id)),
        )
        return job_id

    def recover_interrupted_jobs(self):
        return self.db.execute(
            """UPDATE media_processing_jobs
               SET status='Queued',
                   error_message='Recovered after application interruption.',
                   worker_id=NULL,updated_at=?
               WHERE status='Running'""",
            (datetime.now().isoformat(),),
        )

    def cancel_job(self, job_id):
        with self._lock:
            self._cancel.setdefault(int(job_id), threading.Event()).set()
            process = self._processes.get(int(job_id))
            if process and process.poll() is None:
                process.terminate()
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE media_processing_jobs
               SET status='Cancelled',cancelled_at=?,updated_at=?
               WHERE id=? AND status IN ('Queued','Running')""",
            (now, now, int(job_id)),
        )

    def run_next(self, progress_callback=None):
        frame = self.db.frame(
            """SELECT id FROM media_processing_jobs
               WHERE status='Queued'
               ORDER BY priority,queued_at LIMIT 1"""
        )
        if frame.empty:
            return None
        job_id = int(frame.iloc[0]["id"])
        self.run_job(job_id, progress_callback)
        return job_id

    def run_job(
        self,
        job_id,
        progress_callback: Callable[[int, float, str], None] | None = None,
    ):
        job = self.job(job_id)
        if job["status"] not in ("Queued", "Failed", "Cancelled"):
            raise ValueError(f"Job is {job['status']}")
        status = self.tool_status()
        if not status.available:
            self._fail(job_id, status.message)
            raise RuntimeError(status.message)

        asset = self.asset(job["media_asset_id"])
        settings = json.loads(job.get("settings_json") or "{}")
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE media_processing_jobs
               SET status='Running',started_at=?,attempt_count=attempt_count+1,
                   worker_id=?,error_message=NULL,updated_at=?
               WHERE id=?""",
            (
                now,
                f"{os.getpid()}:{threading.get_ident()}",
                now,
                int(job_id),
            ),
        )
        cancel = threading.Event()
        self._cancel[int(job_id)] = cancel
        try:
            if job["job_type"] == "Probe metadata":
                self._probe(job_id, asset)
            else:
                self._ffmpeg(
                    job_id,
                    asset,
                    job["job_type"],
                    settings,
                    cancel,
                    progress_callback,
                )
            if cancel.is_set() or self.job(job_id)["status"] == "Cancelled":
                return
            now = datetime.now().isoformat()
            self.db.execute(
                """UPDATE media_processing_jobs
                   SET status='Completed',progress_percent=100,completed_at=?,
                       worker_id=NULL,updated_at=? WHERE id=?""",
                (now, now, int(job_id)),
            )
            if self.notifications:
                self.notifications.create(
                    "System",
                    "Success",
                    "Video processing complete",
                    f"{asset['display_name']}: {job['job_type']} completed.",
                    "media_job",
                    job_id,
                )
        except Exception as exc:
            if cancel.is_set():
                self.cancel_job(job_id)
            else:
                self._fail(job_id, str(exc))
            raise
        finally:
            self._cancel.pop(int(job_id), None)
            self._processes.pop(int(job_id), None)

    def _probe(self, job_id, asset):
        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            asset["source_path"],
        ]
        self._command(job_id, command)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "FFprobe failed")
        data = json.loads(result.stdout or "{}")
        format_data = data.get("format", {})
        streams = data.get("streams", [])
        video = next(
            (item for item in streams if item.get("codec_type") == "video"),
            {},
        )
        audio = next(
            (item for item in streams if item.get("codec_type") == "audio"),
            {},
        )
        try:
            numerator, denominator = str(
                video.get("avg_frame_rate", "0/1")
            ).split("/")
            frame_rate = float(numerator) / float(denominator)
        except Exception:
            frame_rate = None
        duration = float(
            format_data.get("duration") or video.get("duration") or 0
        )
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE media_assets
               SET duration_seconds=?,width=?,height=?,frame_rate=?,
                   video_codec=?,audio_codec=?,sample_rate=?,channels=?,
                   container_format=?,bit_rate=?,probe_json=?,status='Ready',
                   updated_at=?
               WHERE id=?""",
            (
                duration,
                video.get("width"),
                video.get("height"),
                frame_rate,
                video.get("codec_name"),
                audio.get("codec_name"),
                int(audio.get("sample_rate") or 0) or None,
                audio.get("channels"),
                format_data.get("format_name"),
                int(format_data.get("bit_rate") or 0) or None,
                json.dumps(data),
                now,
                int(asset["id"]),
            ),
        )
        self.db.execute(
            """UPDATE media_processing_jobs
               SET expected_duration_seconds=?,progress_seconds=?,
                   progress_percent=100,updated_at=?
               WHERE id=?""",
            (duration, duration, now, int(job_id)),
        )

    def _build(self, asset, kind, settings, output_directory):
        source = asset["source_path"]
        output = Path(output_directory)
        if kind == "Extract audio":
            target = output / "audio.wav"
            return (
                [
                    self.ffmpeg_path,
                    "-y",
                    "-i",
                    source,
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    str(settings.get("sample_rate", 16000)),
                    "-c:a",
                    "pcm_s16le",
                    "-progress",
                    "pipe:1",
                    "-nostats",
                    str(target),
                ],
                [("Audio", target, None)],
            )
        if kind == "Generate thumbnails":
            interval = max(10, int(settings.get("interval_seconds", 300)))
            target = output / "thumbnail_%06d.jpg"
            return (
                [
                    self.ffmpeg_path,
                    "-y",
                    "-i",
                    source,
                    "-vf",
                    f"fps=1/{interval},scale={int(settings.get('width', 640))}:-2",
                    "-q:v",
                    "3",
                    "-progress",
                    "pipe:1",
                    "-nostats",
                    str(target),
                ],
                [("ThumbnailPattern", target, interval)],
            )
        target = output / "proxy_720p.mp4"
        return (
            [
                self.ffmpeg_path,
                "-y",
                "-i",
                source,
                "-vf",
                "scale=-2:720",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                "-progress",
                "pipe:1",
                "-nostats",
                str(target),
            ],
            [("Proxy", target, None)],
        )

    def _ffmpeg(self, job_id, asset, kind, settings, cancel, callback):
        job = self.job(job_id)
        command, outputs = self._build(
            asset,
            kind,
            settings,
            job["output_directory"],
        )
        self._command(job_id, command)
        duration = float(asset.get("duration_seconds") or 0)

        # FFmpeg writes diagnostic output to stderr while progress is written to
        # stdout. Merging both streams ensures neither OS pipe can fill and block
        # the child process near completion.
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._processes[int(job_id)] = process
        last_update = 0.0
        output_tail: list[str] = []

        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            if line:
                output_tail.append(line)
                if len(output_tail) > 100:
                    output_tail.pop(0)

            if cancel.is_set():
                process.terminate()
                break

            if not line.startswith("out_time_ms="):
                continue

            try:
                seconds = float(line.split("=", 1)[1]) / 1_000_000
            except (ValueError, IndexError):
                continue

            if time.monotonic() - last_update <= 0.15:
                continue

            percent = min(
                99.0,
                (seconds / duration * 100.0) if duration else 0.0,
            )
            now = datetime.now().isoformat()
            self.db.execute(
                """UPDATE media_processing_jobs
                   SET progress_seconds=?,progress_percent=?,
                       expected_duration_seconds=?,updated_at=?
                   WHERE id=?""",
                (
                    seconds,
                    percent,
                    duration or None,
                    now,
                    int(job_id),
                ),
            )
            last_update = time.monotonic()
            if callback:
                callback(
                    int(job_id),
                    percent,
                    f"{seconds / 3600:.2f}h processed",
                )

        return_code = process.wait()
        if cancel.is_set():
            return
        if return_code:
            error_message = "\n".join(output_tail[-50:])
            raise RuntimeError(
                error_message or f"FFmpeg exited with {return_code}"
            )
        self._register(job_id, asset["id"], outputs)

    def _register(self, job_id, asset_id, outputs):
        now = datetime.now().isoformat()
        for kind, path, interval in outputs:
            paths = (
                sorted(path.parent.glob(path.name.replace("%06d", "*")))
                if kind == "ThumbnailPattern"
                else [path]
            )
            for index, artifact_path in enumerate(paths):
                if not artifact_path.exists():
                    continue
                self.db.execute(
                    """INSERT OR IGNORE INTO media_artifacts(
                        media_asset_id,job_id,artifact_type,file_path,
                        timestamp_seconds,file_size_bytes,metadata_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        int(asset_id),
                        int(job_id),
                        "Thumbnail" if kind == "ThumbnailPattern" else kind,
                        str(artifact_path),
                        index * interval if interval else None,
                        artifact_path.stat().st_size,
                        json.dumps(
                            {"interval_seconds": interval} if interval else {}
                        ),
                        now,
                    ),
                )

    def _command(self, job_id, command):
        self.db.execute(
            """UPDATE media_processing_jobs
               SET command_json=?,updated_at=? WHERE id=?""",
            (
                json.dumps(command),
                datetime.now().isoformat(),
                int(job_id),
            ),
        )

    def _fail(self, job_id, message):
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE media_processing_jobs
               SET status='Failed',error_message=?,worker_id=NULL,updated_at=?
               WHERE id=?""",
            (message, now, int(job_id)),
        )
        if self.notifications:
            self.notifications.create(
                "System",
                "Error",
                "Video processing failed",
                message,
                "media_job",
                job_id,
            )

    def _event(self, job_id, kind, message, detail):
        self.db.execute(
            """INSERT INTO media_processing_events(
                job_id,event_type,message,detail_json,created_at
            ) VALUES(?,?,?,?,?)""",
            (
                job_id,
                kind,
                message,
                json.dumps(detail),
                datetime.now().isoformat(),
            ),
        )
