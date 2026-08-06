from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable


class VideoMetadataService:
    """Extract technical metadata for canonical managed video assets with FFprobe."""

    def __init__(self, db, *, ffprobe_path: str | None = None, runner: Callable[..., Any] | None = None):
        self.db = db
        self.ffprobe_path = ffprobe_path or shutil.which("ffprobe")
        self.runner = runner or subprocess.run

    def tool_status(self) -> dict[str, Any]:
        return {
            "available": bool(self.ffprobe_path),
            "ffprobe_path": self.ffprobe_path,
            "message": (
                "FFprobe is available."
                if self.ffprobe_path
                else "FFprobe was not found. Install FFmpeg or set CREATOR_INTELLIGENCE_FFPROBE."
            ),
        }

    def assets(self, *, status: str | None = None) -> list[dict[str, Any]]:
        clauses = ["a.asset_type='Video'"]
        params: list[Any] = []
        if status and status != "All":
            clauses.append("COALESCE(m.probe_status,'Pending')=?")
            params.append(status)
        frame = self.db.frame(
            f"""
            SELECT a.id,a.name,a.storage_provider,a.location,a.size_bytes,a.status AS asset_status,
                   COALESCE(m.probe_status,'Pending') AS probe_status,m.duration_seconds,
                   m.width,m.height,m.frame_rate,m.video_codec,m.video_profile,m.pixel_format,
                   m.hdr_format,m.audio_codec,m.audio_tracks,m.audio_channels,m.audio_sample_rate,
                   m.container_format,m.bit_rate,m.rotation,m.probed_at,m.probe_error
            FROM managed_assets a
            LEFT JOIN video_asset_metadata m ON m.managed_asset_id=a.id
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(m.probed_at,a.updated_at) DESC,a.name
            """,
            params,
        )
        return frame.to_dict("records")

    def metadata(self, asset_id: str) -> dict[str, Any] | None:
        frame = self.db.frame(
            "SELECT * FROM video_asset_metadata WHERE managed_asset_id=?", (asset_id,)
        )
        return None if frame.empty else frame.iloc[0].to_dict()

    def probe_asset(self, asset_id: str) -> dict[str, Any]:
        asset = self._asset(asset_id)
        path = self._local_path(asset)
        if not self.ffprobe_path:
            return self._record_error(asset_id, "FFprobe is not installed or configured.", "Unavailable")
        if path is None:
            return self._record_error(
                asset_id,
                "This asset is cloud-only. Download or map a local copy before probing.",
                "Needs local file",
            )
        if not path.is_file():
            return self._record_error(asset_id, f"Local file was not found: {path}", "Missing")

        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            result = self.runner(command, capture_output=True, text=True, timeout=120)
            if int(getattr(result, "returncode", 0)) != 0:
                raise RuntimeError((getattr(result, "stderr", "") or "FFprobe failed").strip())
            payload = json.loads(getattr(result, "stdout", "") or "{}")
            values = self._parse(payload)
            self._save(asset_id, values, payload)
            return self.metadata(asset_id) or values
        except Exception as exc:
            return self._record_error(asset_id, str(exc), "Failed")

    def probe_pending_local(self, *, limit: int = 25) -> dict[str, int]:
        rows = self.db.frame(
            """
            SELECT a.id
            FROM managed_assets a
            LEFT JOIN video_asset_metadata m ON m.managed_asset_id=a.id
            WHERE a.asset_type='Video' AND a.storage_provider='Local'
              AND COALESCE(m.probe_status,'Pending') IN ('Pending','Failed','Missing')
            ORDER BY a.updated_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).to_dict("records")
        complete = failed = 0
        for row in rows:
            result = self.probe_asset(str(row["id"]))
            if result.get("probe_status") == "Complete":
                complete += 1
            else:
                failed += 1
        return {"attempted": len(rows), "complete": complete, "failed": failed}

    def _asset(self, asset_id: str) -> dict[str, Any]:
        frame = self.db.frame("SELECT * FROM managed_assets WHERE id=?", (asset_id,))
        if frame.empty:
            raise KeyError(asset_id)
        asset = frame.iloc[0].to_dict()
        if asset.get("asset_type") != "Video":
            raise ValueError("Only video assets can be probed.")
        return asset

    @staticmethod
    def _local_path(asset: dict[str, Any]) -> Path | None:
        if asset.get("storage_provider") != "Local":
            return None
        location = str(asset.get("location") or "").strip()
        return Path(location).expanduser() if location else None

    @staticmethod
    def _parse(payload: dict[str, Any]) -> dict[str, Any]:
        streams = list(payload.get("streams") or [])
        format_data = dict(payload.get("format") or {})
        video = next((item for item in streams if item.get("codec_type") == "video"), {})
        audio = [item for item in streams if item.get("codec_type") == "audio"]
        primary_audio = audio[0] if audio else {}
        tags = video.get("tags") or {}
        side_data = video.get("side_data_list") or []
        rotation = tags.get("rotate")
        if rotation is None:
            rotation = next((item.get("rotation") for item in side_data if item.get("rotation") is not None), 0)
        transfer = video.get("color_transfer")
        hdr = "HDR" if transfer in {"smpte2084", "arib-std-b67"} else "SDR"
        return {
            "duration_seconds": _float(format_data.get("duration") or video.get("duration")),
            "width": _int(video.get("width")),
            "height": _int(video.get("height")),
            "frame_rate": _rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
            "video_codec": video.get("codec_name"),
            "video_profile": video.get("profile"),
            "pixel_format": video.get("pix_fmt"),
            "color_space": video.get("color_space"),
            "color_transfer": transfer,
            "color_primaries": video.get("color_primaries"),
            "hdr_format": hdr,
            "audio_codec": primary_audio.get("codec_name"),
            "audio_tracks": len(audio),
            "audio_channels": _int(primary_audio.get("channels")),
            "audio_sample_rate": _int(primary_audio.get("sample_rate")),
            "container_format": format_data.get("format_name"),
            "bit_rate": _int(format_data.get("bit_rate")),
            "rotation": _int(rotation) or 0,
        }

    def _save(self, asset_id: str, values: dict[str, Any], payload: dict[str, Any]) -> None:
        now = _now()
        columns = [
            "duration_seconds", "width", "height", "frame_rate", "video_codec",
            "video_profile", "pixel_format", "color_space", "color_transfer",
            "color_primaries", "hdr_format", "audio_codec", "audio_tracks",
            "audio_channels", "audio_sample_rate", "container_format", "bit_rate", "rotation",
        ]
        self.db.execute(
            f"""
            INSERT INTO video_asset_metadata(
                managed_asset_id,{','.join(columns)},probe_status,probe_error,probed_at,probe_json,updated_at
            ) VALUES({','.join('?' for _ in range(len(columns) + 6))})
            ON CONFLICT(managed_asset_id) DO UPDATE SET
                {','.join(f'{column}=excluded.{column}' for column in columns)},
                probe_status='Complete',probe_error=NULL,probed_at=excluded.probed_at,
                probe_json=excluded.probe_json,updated_at=excluded.updated_at
            """,
            (
                asset_id,
                *(values.get(column) for column in columns),
                "Complete",
                None,
                now,
                json.dumps(payload),
                now,
            ),
        )

    def _record_error(self, asset_id: str, message: str, status: str) -> dict[str, Any]:
        now = _now()
        self.db.execute(
            """
            INSERT INTO video_asset_metadata(managed_asset_id,probe_status,probe_error,updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(managed_asset_id) DO UPDATE SET
                probe_status=excluded.probe_status,probe_error=excluded.probe_error,
                updated_at=excluded.updated_at
            """,
            (asset_id, status, message, now),
        )
        return self.metadata(asset_id) or {"managed_asset_id": asset_id, "probe_status": status, "probe_error": message}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _int(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rate(value: Any) -> float | None:
    if value in (None, "", "0/0", "N/A"):
        return None
    try:
        numerator, denominator = str(value).split("/", 1)
        denominator_value = float(denominator)
        return None if denominator_value == 0 else float(numerator) / denominator_value
    except (ValueError, ZeroDivisionError):
        return _float(value)
