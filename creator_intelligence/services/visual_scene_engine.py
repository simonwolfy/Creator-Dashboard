from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import subprocess
from typing import Any, Callable


_SHOWINFO_TIME = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")
_SHOWINFO_SCORE = re.compile(r"scene_score=([0-9]+(?:\.[0-9]+)?)")


class VisualSceneEngineService:
    """Detect visual cuts with FFmpeg without modifying or permanently caching media."""

    def __init__(self, db, video_processing):
        self.db = db
        self.processing = video_processing
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS visual_scene_changes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER NOT NULL,
                occurred_at_seconds REAL NOT NULL,
                scene_score REAL,
                threshold REAL NOT NULL,
                source_path TEXT NOT NULL,
                source_kind TEXT NOT NULL DEFAULT 'local',
                created_at TEXT NOT NULL,
                UNIQUE(media_asset_id,occurred_at_seconds,threshold)
            )"""
        )
        self.db.execute(
            """CREATE INDEX IF NOT EXISTS idx_visual_scene_asset_time
               ON visual_scene_changes(media_asset_id,occurred_at_seconds)"""
        )

    def assets(self):
        return self.db.frame(
            """SELECT a.id,a.display_name,a.duration_seconds,a.width,a.height,
                      a.source_path,
                      COUNT(v.id) AS detected_cuts,
                      MAX(v.created_at) AS last_analyzed
               FROM media_assets a
               LEFT JOIN visual_scene_changes v ON v.media_asset_id=a.id
               WHERE a.asset_type='Video'
               GROUP BY a.id
               ORDER BY a.created_at DESC"""
        )

    def changes(self, media_asset_id: int | None = None):
        sql = """SELECT v.*,a.display_name
                 FROM visual_scene_changes v
                 JOIN media_assets a ON a.id=v.media_asset_id"""
        params: list[Any] = []
        if media_asset_id is not None:
            sql += " WHERE v.media_asset_id=?"
            params.append(int(media_asset_id))
        return self.db.frame(sql + " ORDER BY v.occurred_at_seconds", params)

    def source_for(self, media_asset_id: int) -> tuple[Path, str]:
        asset = self.processing.asset(media_asset_id)
        local = Path(str(asset.get("source_path") or ""))
        if local.is_file():
            return local, "original"
        proxy = self.db.frame(
            """SELECT file_path FROM media_artifacts
               WHERE media_asset_id=? AND artifact_type='Proxy'
               ORDER BY created_at DESC LIMIT 1""",
            (int(media_asset_id),),
        )
        if not proxy.empty:
            path = Path(str(proxy.iloc[0]["file_path"]))
            if path.is_file():
                return path, "proxy"
        raise FileNotFoundError("Visual analysis requires a local video or completed proxy.")

    def detect(
        self,
        media_asset_id: int,
        threshold: float = 0.35,
        min_gap_seconds: float = 1.0,
        replace: bool = True,
        progress_callback: Callable[[float, str], None] | None = None,
    ):
        threshold = max(0.05, min(float(threshold), 0.95))
        min_gap_seconds = max(0.0, float(min_gap_seconds))
        source, source_kind = self.source_for(media_asset_id)
        asset = self.processing.asset(media_asset_id)
        duration = float(asset.get("duration_seconds") or 0)
        ffmpeg = self.processing.ffmpeg_path
        if not ffmpeg:
            raise RuntimeError("FFmpeg is unavailable.")

        if replace:
            self.db.execute(
                "DELETE FROM visual_scene_changes WHERE media_asset_id=?",
                (int(media_asset_id),),
            )

        expression = f"select='gt(scene,{threshold})',metadata=print"
        command = [
            ffmpeg,
            "-hide_banner",
            "-i", str(source),
            "-an",
            "-vf", expression,
            "-vsync", "vfr",
            "-f", "null",
            "-",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        detected: list[tuple[float, float | None]] = []
        pending_time: float | None = None
        pending_score: float | None = None
        last_kept = -10_000.0

        assert process.stderr is not None
        for line in process.stderr:
            time_match = _SHOWINFO_TIME.search(line)
            if time_match:
                pending_time = float(time_match.group(1))
            score_match = _SHOWINFO_SCORE.search(line)
            if score_match:
                pending_score = float(score_match.group(1))
            if "lavfi.scene_score=" in line:
                try:
                    pending_score = float(line.rsplit("=", 1)[1].strip())
                except ValueError:
                    pass
            if pending_time is not None and pending_time - last_kept >= min_gap_seconds:
                detected.append((pending_time, pending_score))
                last_kept = pending_time
                if progress_callback and duration:
                    progress_callback(
                        min(99.0, pending_time / duration * 100.0),
                        f"{pending_time:.1f}s analyzed",
                    )
                pending_time = None
                pending_score = None

        return_code = process.wait()
        if return_code:
            raise RuntimeError(f"FFmpeg scene detection exited with {return_code}.")

        now = datetime.now().isoformat()
        for occurred_at, score in detected:
            self.db.execute(
                """INSERT OR IGNORE INTO visual_scene_changes(
                       media_asset_id,occurred_at_seconds,scene_score,threshold,
                       source_path,source_kind,created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    int(media_asset_id), occurred_at, score, threshold,
                    str(source), source_kind, now,
                ),
            )
        if progress_callback:
            progress_callback(100.0, f"{len(detected)} visual cuts detected")
        return self.changes(media_asset_id)
