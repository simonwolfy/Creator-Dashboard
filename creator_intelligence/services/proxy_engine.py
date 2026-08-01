from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProxyPreset:
    key: str
    label: str
    height: int
    crf: int
    video_preset: str
    audio_bitrate: str


PRESETS: tuple[ProxyPreset, ...] = (
    ProxyPreset("small", "Small · 540p", 540, 30, "veryfast", "64k"),
    ProxyPreset("balanced", "Balanced · 720p", 720, 28, "veryfast", "96k"),
    ProxyPreset("quality", "Quality · 1080p", 1080, 25, "fast", "128k"),
)


class ProxyEngineService:
    """Orchestrates disposable editing proxies without modifying source media."""

    def __init__(self, processing_service):
        self.processing = processing_service

    def presets(self) -> tuple[ProxyPreset, ...]:
        return PRESETS

    def assets(self) -> list[dict[str, Any]]:
        frame = self.processing.assets().copy()
        if frame.empty:
            return []
        proxy_counts = self.processing.db.frame(
            """
            SELECT media_asset_id, COUNT(*) AS proxy_count,
                   MAX(created_at) AS latest_proxy_at,
                   MAX(file_path) AS latest_proxy_path
            FROM media_artifacts
            WHERE artifact_type='Proxy'
            GROUP BY media_asset_id
            """
        )
        if not proxy_counts.empty:
            frame = frame.merge(
                proxy_counts,
                how="left",
                left_on="id",
                right_on="media_asset_id",
            )
        for column, default in (
            ("proxy_count", 0),
            ("latest_proxy_at", None),
            ("latest_proxy_path", None),
        ):
            if column not in frame:
                frame[column] = default
        frame["proxy_count"] = frame["proxy_count"].fillna(0).astype(int)
        return frame.to_dict("records")

    def queue_proxy(self, media_asset_id: int, preset_key: str = "balanced") -> int:
        preset = self._preset(preset_key)
        asset = self.processing.asset(media_asset_id)
        source = Path(str(asset.get("source_path") or ""))
        if not source.is_file():
            raise FileNotFoundError(f"Source video is not available locally: {source}")
        settings = {
            "preset_key": preset.key,
            "height": preset.height,
            "crf": preset.crf,
            "video_preset": preset.video_preset,
            "audio_bitrate": preset.audio_bitrate,
            "disposable": True,
        }
        return self.processing.queue_job(
            media_asset_id,
            "Generate proxy",
            settings,
            priority=40,
        )

    def queue_missing(self, preset_key: str = "balanced", limit: int = 25) -> dict[str, int]:
        queued = skipped = 0
        for asset in self.assets():
            if queued >= max(1, min(int(limit), 250)):
                break
            if int(asset.get("proxy_count") or 0) > 0:
                skipped += 1
                continue
            source = Path(str(asset.get("source_path") or ""))
            if not source.is_file():
                skipped += 1
                continue
            self.queue_proxy(int(asset["id"]), preset_key)
            queued += 1
        return {"queued": queued, "skipped": skipped}

    def remove_proxy(self, artifact_id: int) -> None:
        frame = self.processing.db.frame(
            "SELECT * FROM media_artifacts WHERE id=? AND artifact_type='Proxy'",
            (int(artifact_id),),
        )
        if frame.empty:
            raise KeyError(artifact_id)
        path = Path(str(frame.iloc[0]["file_path"]))
        if path.exists():
            path.unlink()
        self.processing.db.execute(
            "DELETE FROM media_artifacts WHERE id=?",
            (int(artifact_id),),
        )

    def proxy_artifacts(self, media_asset_id: int | None = None) -> list[dict[str, Any]]:
        frame = self.processing.artifacts(media_asset_id)
        if frame.empty:
            return []
        return frame[frame["artifact_type"] == "Proxy"].to_dict("records")

    @staticmethod
    def estimated_size_bytes(duration_seconds: float | None, preset_key: str) -> int | None:
        if not duration_seconds:
            return None
        preset = next(item for item in PRESETS if item.key == preset_key)
        video_kbps = {"small": 900, "balanced": 1600, "quality": 3200}[preset.key]
        audio_kbps = int(preset.audio_bitrate.rstrip("k"))
        return int(float(duration_seconds) * (video_kbps + audio_kbps) * 1000 / 8)

    @staticmethod
    def _preset(key: str) -> ProxyPreset:
        for preset in PRESETS:
            if preset.key == key:
                return preset
        raise ValueError(f"Unknown proxy preset: {key}")
