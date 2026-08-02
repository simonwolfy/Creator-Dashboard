from __future__ import annotations

from datetime import datetime
import importlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from creator_intelligence.services.transcript_intelligence import TranscriptIntelligenceMixin
from creator_intelligence.services.transcripts import (
    TranscriptEngineStatus,
    TranscriptService,
)


_DLL_DIRECTORY_HANDLES: list[Any] = []
_DLL_DIRECTORIES_REGISTERED = False


def _register_nvidia_dll_directories() -> list[Path]:
    """Expose pip- and toolkit-installed NVIDIA runtime DLLs on Windows."""
    global _DLL_DIRECTORIES_REGISTERED
    if _DLL_DIRECTORIES_REGISTERED:
        return []
    _DLL_DIRECTORIES_REGISTERED = True

    candidates: list[Path] = []
    for package_name in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            package = importlib.import_module(package_name)
            for package_path in getattr(package, "__path__", []):
                candidates.append(Path(package_path) / "bin")
        except ImportError:
            continue

    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        candidates.append(Path(cuda_path) / "bin")

    toolkit_root = Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA")
    if toolkit_root.is_dir():
        candidates.extend(
            version_dir / "bin"
            for version_dir in sorted(toolkit_root.glob("v*"), reverse=True)
        )

    registered: list[Path] = []
    seen: set[str] = set()
    add_dll_directory = getattr(os, "add_dll_directory", None)
    for directory in candidates:
        if not directory.is_dir():
            continue
        normalized = os.path.normcase(str(directory.resolve()))
        if normalized in seen:
            continue
        seen.add(normalized)
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
        if add_dll_directory is not None:
            try:
                _DLL_DIRECTORY_HANDLES.append(add_dll_directory(str(directory)))
            except OSError:
                continue
        registered.append(directory)
    return registered


class LocalWhisperTranscriptService(TranscriptIntelligenceMixin, TranscriptService):
    """Transcript service with direct faster-whisper and editing intelligence."""

    def engine_status(self):
        if importlib.util.find_spec("faster_whisper") is not None:
            return TranscriptEngineStatus(
                "embedded-faster-whisper",
                True,
                None,
                "Embedded faster-whisper is available. GPU acceleration will be used when possible.",
            )
        return super().engine_status()

    def _run_engine(self, job, status, cancel, progress_callback):
        if status.engine != "embedded-faster-whisper":
            return super()._run_engine(job, status, cancel, progress_callback)

        _register_nvidia_dll_directories()
        settings = self._job_settings(job)
        model_name = str(job.get("model_name") or "base")
        input_path = str(job["input_path"])
        transcript = self.transcript(job["transcript_id"])
        language = str(transcript.get("language") or "en")
        duration = self._duration_for_job(job)
        device = str(settings.get("device") or "auto").lower()
        compute_type = str(settings.get("compute_type") or "auto").lower()
        beam_size = max(1, int(settings.get("beam_size") or 5))
        vad_filter = bool(settings.get("vad_filter", True))

        model = self._load_model(model_name, device, compute_type)
        segment_iter, info = model.transcribe(
            input_path,
            language=None if language == "auto" else language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            word_timestamps=True,
            condition_on_previous_text=True,
        )

        rows: list[dict[str, Any]] = []
        for segment in segment_iter:
            if cancel.is_set():
                return []
            words = []
            probabilities = []
            for word in segment.words or []:
                probability = getattr(word, "probability", None)
                if probability is not None:
                    probabilities.append(float(probability))
                words.append({
                    "start": getattr(word, "start", None),
                    "end": getattr(word, "end", None),
                    "word": str(getattr(word, "word", "")).strip(),
                    "probability": probability,
                })

            confidence = sum(probabilities) / len(probabilities) if probabilities else None
            end_seconds = float(segment.end or 0)
            rows.append({
                "start": float(segment.start or 0),
                "end": end_seconds,
                "text": str(segment.text or "").strip(),
                "confidence": confidence,
                "words": words,
                "tags": ["faster-whisper", f"language:{info.language}"],
            })
            percent = min(99.0, end_seconds / duration * 100.0) if duration else 0.0
            self.db.execute(
                """UPDATE transcript_jobs SET progress_percent=?,updated_at=? WHERE id=?""",
                (percent, datetime.now().isoformat(), int(job["id"])),
            )
            if progress_callback:
                progress_callback(int(job["id"]), percent, f"{end_seconds:.1f}s transcribed")
        return rows

    def _load_model(self, model_name: str, device: str, compute_type: str):
        _register_nvidia_dll_directories()
        from faster_whisper import WhisperModel

        if device != "auto":
            resolved_compute = compute_type
            if resolved_compute == "auto":
                resolved_compute = "float16" if device == "cuda" else "int8"
            return WhisperModel(model_name, device=device, compute_type=resolved_compute)

        try:
            return WhisperModel(
                model_name,
                device="cuda",
                compute_type="float16" if compute_type == "auto" else compute_type,
            )
        except Exception:
            return WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8" if compute_type == "auto" else compute_type,
            )

    def _job_settings(self, job) -> dict[str, Any]:
        raw = job.get("settings_json")
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            value = json.loads(str(raw))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _duration_for_job(self, job) -> float:
        if self.video_processing and job.get("media_asset_id"):
            try:
                asset = self.video_processing.asset(int(job["media_asset_id"]))
                return float(asset.get("duration_seconds") or 0)
            except Exception:
                pass
        try:
            return float(self.transcript(job["transcript_id"]).get("duration_seconds") or 0)
        except Exception:
            return 0.0
