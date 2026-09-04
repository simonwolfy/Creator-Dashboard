from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from creator_intelligence.core.credential_vault import CredentialVault, MASK
from creator_intelligence.services.google_drive_media_cache import GoogleDriveMediaCacheService
from creator_intelligence.utils.subprocesses import hidden_process_kwargs


class ClipVisualIntelligenceService:
    """Sample clip frames and turn them into structured packaging evidence."""

    PROVIDER = "openai-vision"
    DEFAULT_MODEL = "gpt-5.4-mini"
    ENDPOINT = "https://api.openai.com/v1/responses"

    def __init__(self, db, transcripts, *, opener: Callable[..., Any] | None = None,
                 runner: Callable[..., Any] | None = None, google_drive=None):
        self.db = db
        self.transcripts = transcripts
        self.opener = opener or urlopen
        self.runner = runner or subprocess.run
        self.vault = CredentialVault.for_database(db)
        self.drive_cache = GoogleDriveMediaCacheService(google_drive) if google_drive else None
        self.last_usage: dict[str, Any] = {}
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS integration_settings(
                integration_id TEXT PRIMARY KEY, enabled INTEGER DEFAULT 0,
                config_json TEXT NOT NULL DEFAULT '{}', last_connected_at TEXT,
                last_error TEXT, updated_at TEXT NOT NULL)"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS clip_visual_analysis_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clip_candidate_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                frame_count INTEGER NOT NULL,
                visual_summary TEXT,
                on_screen_text TEXT,
                detected_game TEXT,
                confidence REAL,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS package_provenance(
                id INTEGER PRIMARY KEY AUTOINCREMENT,package_id TEXT NOT NULL,
                source_type TEXT NOT NULL,source_id TEXT,payload_json TEXT NOT NULL DEFAULT '{}',
                confidence REAL,provider TEXT,model TEXT,intelligence_version TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS intelligence_provider_usage(
                id INTEGER PRIMARY KEY AUTOINCREMENT,provider TEXT NOT NULL,model TEXT,
                operation TEXT NOT NULL,package_id TEXT,input_units REAL,output_units REAL,
                estimated_cost REAL,status TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL
            )"""
        )

    def configuration(self, *, masked: bool = True) -> dict[str, str]:
        frame = self.db.frame(
            "SELECT config_json FROM integration_settings WHERE integration_id='openai_visual_packaging'"
        )
        public = json.loads(frame.iloc[0]["config_json"] or "{}") if not frame.empty else {}
        public.setdefault("model", self.DEFAULT_MODEL)
        return self.vault.masked(self.PROVIDER, public) if masked else self.vault.reveal(self.PROVIDER, public)

    def save_configuration(self, *, api_key: str = "", model: str = "") -> dict[str, str]:
        clean_model = str(model or self.DEFAULT_MODEL).strip() or self.DEFAULT_MODEL
        public = {"model": clean_model}
        if api_key and api_key != MASK:
            self.vault.save(self.PROVIDER, {"api_key": api_key.strip()})
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS integration_settings(
                integration_id TEXT PRIMARY KEY, enabled INTEGER DEFAULT 0,
                config_json TEXT NOT NULL DEFAULT '{}', last_connected_at TEXT,
                last_error TEXT, updated_at TEXT NOT NULL)"""
        )
        self.db.execute(
            """INSERT INTO integration_settings(integration_id,enabled,config_json,updated_at)
               VALUES('openai_visual_packaging',1,?,CURRENT_TIMESTAMP)
               ON CONFLICT(integration_id) DO UPDATE SET enabled=1,
               config_json=excluded.config_json,updated_at=CURRENT_TIMESTAMP""",
            (json.dumps(public),),
        )
        return self.configuration(masked=True)

    def analyze_package(self, package_id: str) -> dict[str, Any]:
        package = self.db.frame("SELECT * FROM publishing_packages WHERE id=?", (str(package_id),))
        if package.empty:
            raise KeyError(package_id)
        clip_id = int(package.iloc[0]["clip_candidate_id"])
        clip = self._clip(clip_id)
        config = self.configuration(masked=False)
        api_key = str(config.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("Add an OpenAI API key before running automatic video analysis.")
        model = str(config.get("model") or self.DEFAULT_MODEL)

        try:
            with self._source(clip_id, clip) as source:
                with tempfile.TemporaryDirectory(prefix="creator-intel-frames-") as folder:
                    frames = self._extract_frames(source, clip, Path(folder))
                    evidence = self._analyze_frames(frames, api_key=api_key, model=model)
            summary = str(evidence["visual_summary"]).strip()
            detected_game = str(evidence.get("detected_game") or "").strip()
            if detected_game:
                summary = f"{summary} Detected game: {detected_game}."
            self.transcripts.save_clip_visual_context(
                clip_id,
                visual_summary=summary,
                on_screen_text=evidence.get("on_screen_text") or "",
                confidence=float(evidence.get("confidence") or 0),
            )
            self._record(clip_id, model, len(frames), evidence, "Completed", None)
            self._record_provenance(str(package_id), clip_id, evidence, model)
            self._record_usage(str(package_id), model, "Completed")
            return {"clip_id": clip_id, "frame_count": len(frames), **evidence}
        except Exception as exc:
            safe_error = self.vault.redact(exc)
            self._record(clip_id, model, 0, {}, "Failed", safe_error)
            self._record_usage(str(package_id), model, "Failed", safe_error)
            raise

    def _clip(self, clip_id: int) -> dict[str, Any]:
        frame = self.db.frame("SELECT * FROM transcript_clip_candidates WHERE id=?", (clip_id,))
        if frame.empty:
            raise KeyError(clip_id)
        return frame.iloc[0].to_dict()

    @contextmanager
    def _source(self, clip_id: int, clip: dict[str, Any]):
        transcript = self.transcripts.transcript(int(clip["transcript_id"]))
        source = Path(str(transcript.get("source_path") or ""))
        if source.is_file():
            yield source
            return
        job = self.db.frame(
            """SELECT source_provider,source_key FROM content_analysis_jobs
               WHERE clip_candidate_id=? ORDER BY id DESC LIMIT 1""", (clip_id,),
        ) if self._table_exists("content_analysis_jobs") else None
        if job is not None and not job.empty and job.iloc[0]["source_provider"] == "Google Drive":
            if not self.drive_cache:
                raise RuntimeError("Reconnect Google Drive before analyzing this cloud video.")
            with self.drive_cache.materialize(str(job.iloc[0]["source_key"])) as downloaded:
                yield downloaded
            return
        raise FileNotFoundError("The clip needs an accessible local or Google Drive source video.")

    def _table_exists(self, table):
        return not self.db.frame(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).empty

    def _ffmpeg_path(self) -> str:
        processing = getattr(self.transcripts, "video_processing", None)
        path = getattr(processing, "ffmpeg_path", None)
        if not path:
            raise RuntimeError("FFmpeg is unavailable. Configure it in FFmpeg Manager first.")
        return str(path)

    def _extract_frames(self, source: Path, clip: dict[str, Any], folder: Path) -> list[Path]:
        start = float(clip["start_seconds"])
        end = float(clip["end_seconds"])
        duration = max(0.1, end - start)
        times = [start + duration * fraction for fraction in (0.15, 0.5, 0.85)]
        frames: list[Path] = []
        for index, timestamp in enumerate(times, 1):
            destination = folder / f"frame-{index}.jpg"
            command = [
                self._ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{timestamp:.3f}", "-i", str(source), "-frames:v", "1",
                "-vf", "scale='min(768,iw)':-2", "-q:v", "3", str(destination),
            ]
            result = self.runner(
                command, capture_output=True, text=True, timeout=60,
                **hidden_process_kwargs(),
            )
            if int(getattr(result, "returncode", 0)) != 0 or not destination.is_file():
                error = str(getattr(result, "stderr", "") or "FFmpeg did not create a frame.").strip()
                raise RuntimeError(error)
            frames.append(destination)
        return frames

    def _analyze_frames(self, frames: list[Path], *, api_key: str, model: str) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{
            "type": "input_text",
            "text": (
                "Analyze these chronological frames from one short gaming clip. Describe only visible "
                "evidence useful for an accurate title and social caption: the main subject, action, "
                "creator reaction, payoff, readable on-screen text, and game if confidently identifiable. "
                "Do not invent dialogue or events between frames."
            ),
        }]
        for frame in frames:
            encoded = base64.b64encode(frame.read_bytes()).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}",
                            "detail": "low"})
        schema = {
            "type": "object",
            "properties": {
                "visual_summary": {"type": "string"},
                "on_screen_text": {"type": "string"},
                "detected_game": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["visual_summary", "on_screen_text", "detected_game", "confidence"],
            "additionalProperties": False,
        }
        payload = {
            "model": model,
            "store": False,
            "input": [{"role": "user", "content": content}],
            "text": {"format": {"type": "json_schema", "name": "clip_visual_evidence",
                                  "strict": True, "schema": schema}},
            "max_output_tokens": 500,
        }
        request = Request(
            self.ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=90) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Visual analysis request failed ({exc.code}): {detail[:300]}") from exc
        except URLError as exc:
            raise RuntimeError(f"Could not reach the visual analysis service: {exc.reason}") from exc
        output_text = response_payload.get("output_text") or self._output_text(response_payload)
        self.last_usage = dict(response_payload.get("usage") or {})
        if not output_text:
            raise RuntimeError("Visual analysis returned no structured result.")
        result = json.loads(output_text)
        if not str(result.get("visual_summary") or "").strip():
            raise RuntimeError("Visual analysis returned an empty summary.")
        return result

    @staticmethod
    def _output_text(payload: dict[str, Any]) -> str:
        for item in payload.get("output") or []:
            for content in item.get("content") or []:
                if content.get("type") == "output_text":
                    return str(content.get("text") or "")
        return ""

    def _record(self, clip_id: int, model: str, frame_count: int,
                evidence: dict[str, Any], status: str, error: str | None) -> None:
        self.db.execute(
            """INSERT INTO clip_visual_analysis_runs(
               clip_candidate_id,model,frame_count,visual_summary,on_screen_text,
               detected_game,confidence,status,error) VALUES(?,?,?,?,?,?,?,?,?)""",
            (clip_id, model, frame_count, evidence.get("visual_summary"),
             evidence.get("on_screen_text"), evidence.get("detected_game"),
             evidence.get("confidence"), status, error),
        )

    def _record_provenance(self, package_id, clip_id, evidence, model):
        self.db.execute(
            """INSERT INTO package_provenance(package_id,source_type,source_id,payload_json,
               confidence,provider,model,intelligence_version,created_at)
               VALUES(?,'visual',?,?,?,?,?,'creator-packaging-v6',CURRENT_TIMESTAMP)""",
            (package_id, str(clip_id), json.dumps(evidence, default=str),
             float(evidence.get("confidence") or 0), self.PROVIDER, model),
        )

    def _record_usage(self, package_id, model, status, error=None):
        self.db.execute(
            """INSERT INTO intelligence_provider_usage(provider,model,operation,package_id,
               input_units,output_units,status,error,created_at)
               VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (self.PROVIDER, model, "clip-frame-analysis", package_id,
             self.last_usage.get("input_tokens"), self.last_usage.get("output_tokens"),
             status, error),
        )
