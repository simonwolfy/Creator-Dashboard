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

    def _shift_indexes_up(self, table: str, index_column: str,
                          transcript_id: int, after_index: int) -> None:
        """Shift ordered rows without violating SQLite's immediate UNIQUE checks."""
        allowed = {
            ("transcript_segments", "segment_index"),
            ("transcript_chapters", "chapter_index"),
        }
        if (table, index_column) not in allowed:
            raise ValueError("Unsupported transcript index table.")

        self.db.execute(
            f"""UPDATE {table}
                SET {index_column}=-{index_column}-1
                WHERE transcript_id=? AND {index_column}>?""",
            (int(transcript_id), int(after_index)),
        )
        self.db.execute(
            f"""UPDATE {table}
                SET {index_column}=-{index_column}
                WHERE transcript_id=? AND {index_column}<0""",
            (int(transcript_id),),
        )

    def split_segment(self, segment_id: int, split_seconds: float,
                      left_text: str | None = None,
                      right_text: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        row = self._segment(segment_id)
        start = float(row["start_seconds"])
        end = float(row["end_seconds"])
        split = float(split_seconds)
        if not start < split < end:
            raise ValueError("Split time must fall inside the segment.")

        original = str(row["text"]).strip()
        if left_text is None or right_text is None:
            words = original.split()
            ratio = (split - start) / max(0.001, end - start)
            cut = min(max(1, round(len(words) * ratio)), max(1, len(words) - 1))
            left_text = left_text or " ".join(words[:cut])
            right_text = right_text or " ".join(words[cut:])
        if not str(left_text).strip() or not str(right_text).strip():
            raise ValueError("Both split segments require text.")

        transcript_id = int(row["transcript_id"])
        old_index = int(row["segment_index"])
        now = datetime.now().isoformat()
        self._shift_indexes_up(
            "transcript_segments", "segment_index", transcript_id, old_index
        )
        self.db.execute(
            """UPDATE transcript_segments
               SET end_seconds=?,text=?,updated_at=? WHERE id=?""",
            (split, str(left_text).strip(), now, int(segment_id)),
        )
        new_id = int(self.db.execute(
            """INSERT INTO transcript_segments(
                transcript_id,segment_index,start_seconds,end_seconds,text,speaker,
                confidence,words_json,tags_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                transcript_id, old_index + 1, split, end, str(right_text).strip(),
                row.get("speaker"), row.get("confidence"), "[]",
                row.get("tags_json") or "[]", now, now,
            ),
        ))
        self._refresh_transcript(transcript_id)
        return self._segment(segment_id), self._segment(new_id)

    def split_chapter(self, chapter_id: int, split_seconds: float,
                      second_title: str | None = None) -> int:
        chapter = self._chapter(chapter_id)
        split = float(split_seconds)
        if not float(chapter["start_seconds"]) < split < float(chapter["end_seconds"]):
            raise ValueError("Split time must fall inside the chapter.")

        transcript_id = int(chapter["transcript_id"])
        index = int(chapter["chapter_index"])
        old_end = float(chapter["end_seconds"])
        now = datetime.now().isoformat()
        self._shift_indexes_up(
            "transcript_chapters", "chapter_index", transcript_id, index
        )
        self.db.execute(
            """UPDATE transcript_chapters
               SET end_seconds=?,source='manual',updated_at=? WHERE id=?""",
            (split, now, int(chapter_id)),
        )
        return int(self.db.execute(
            """INSERT INTO transcript_chapters(
                transcript_id,chapter_index,start_seconds,end_seconds,title,summary,
                keywords_json,confidence,source,review_status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                transcript_id, index + 1, split, old_end,
                str(second_title or f'{chapter["title"]} — Part 2'), "", "[]",
                chapter.get("confidence") or 0.5, "manual", "Unreviewed", now, now,
            ),
        ))

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
