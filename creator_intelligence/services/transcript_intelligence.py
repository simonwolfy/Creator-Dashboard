from __future__ import annotations

from datetime import datetime
import json
import math
import re
from typing import Any


class TranscriptIntelligenceMixin:
    """Editing, review, speaker, chapter, and analytics operations.

    The mixin intentionally depends only on the existing database adapter so it
    can be used by both the embedded faster-whisper service and future engines.
    """

    def _ensure_schema(self):
        super()._ensure_schema()
        statements = [
            """CREATE TABLE IF NOT EXISTS transcript_speakers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id INTEGER NOT NULL,
                speaker_key TEXT NOT NULL,
                display_name TEXT NOT NULL,
                color TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(transcript_id,speaker_key)
            )""",
            """CREATE TABLE IF NOT EXISTS transcript_segment_reviews(
                segment_id INTEGER PRIMARY KEY,
                review_status TEXT NOT NULL DEFAULT 'Unreviewed',
                reviewed_at TEXT,
                reviewed_by TEXT,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS transcript_embeddings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id INTEGER NOT NULL,
                segment_id INTEGER,
                model_name TEXT NOT NULL,
                dimensions INTEGER,
                vector_json TEXT,
                content_hash TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(segment_id,model_name)
            )""",
            """CREATE TABLE IF NOT EXISTS transcript_clip_candidates(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id INTEGER NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                title TEXT,
                reason TEXT,
                score REAL DEFAULT 0,
                source TEXT DEFAULT 'manual',
                review_status TEXT DEFAULT 'Unreviewed',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
        ]
        for statement in statements:
            self.db.execute(statement)

    def transcript_statistics(self, transcript_id: int) -> dict[str, Any]:
        transcript = self.transcript(transcript_id)
        segments = self.segments(transcript_id)
        chapters = self.chapters(transcript_id)
        if segments.empty:
            return {
                "duration_seconds": float(transcript.get("duration_seconds") or 0),
                "segment_count": 0,
                "word_count": 0,
                "chapter_count": len(chapters),
                "speaker_count": 0,
                "speaking_seconds": 0.0,
                "silence_seconds": 0.0,
                "silence_percent": 0.0,
                "words_per_minute": 0.0,
                "longest_pause_seconds": 0.0,
                "average_confidence": None,
            }

        ordered = segments.sort_values(["start_seconds", "end_seconds"])
        duration = max(
            float(transcript.get("duration_seconds") or 0),
            float(ordered["end_seconds"].max()),
        )
        speaking = 0.0
        merged_end = 0.0
        longest_pause = 0.0
        for _, row in ordered.iterrows():
            start = max(0.0, float(row["start_seconds"]))
            end = max(start, float(row["end_seconds"]))
            longest_pause = max(longest_pause, max(0.0, start - merged_end))
            if end > merged_end:
                speaking += end - max(start, merged_end)
                merged_end = end
        longest_pause = max(longest_pause, max(0.0, duration - merged_end))
        silence = max(0.0, duration - speaking)
        word_count = int(transcript.get("word_count") or 0)
        if not word_count:
            word_count = sum(
                len(re.findall(r"\b[\w'-]+\b", str(value)))
                for value in ordered["text"]
            )
        confidence = ordered["confidence"].dropna() if "confidence" in ordered else []
        speakers = {
            str(value).strip()
            for value in ordered.get("speaker", [])
            if str(value).strip() and str(value).lower() != "none"
        }
        return {
            "duration_seconds": round(duration, 2),
            "segment_count": len(ordered),
            "word_count": word_count,
            "chapter_count": len(chapters),
            "speaker_count": len(speakers),
            "speaking_seconds": round(speaking, 2),
            "silence_seconds": round(silence, 2),
            "silence_percent": round((silence / duration * 100.0) if duration else 0.0, 2),
            "words_per_minute": round((word_count / speaking * 60.0) if speaking else 0.0, 2),
            "longest_pause_seconds": round(longest_pause, 2),
            "average_confidence": round(float(confidence.mean()), 4) if len(confidence) else None,
        }

    def update_segment(self, segment_id: int, *, text: str | None = None,
                       speaker: str | None = None,
                       review_status: str | None = None) -> dict[str, Any]:
        row = self._segment(segment_id)
        now = datetime.now().isoformat()
        if text is not None:
            clean = re.sub(r"\s+", " ", str(text)).strip()
            if not clean:
                raise ValueError("Segment text cannot be empty.")
            self.db.execute(
                "UPDATE transcript_segments SET text=?,updated_at=? WHERE id=?",
                (clean, now, int(segment_id)),
            )
        if speaker is not None:
            clean_speaker = re.sub(r"\s+", " ", str(speaker)).strip() or None
            self.db.execute(
                "UPDATE transcript_segments SET speaker=?,updated_at=? WHERE id=?",
                (clean_speaker, now, int(segment_id)),
            )
            if clean_speaker:
                self.upsert_speaker(int(row["transcript_id"]), clean_speaker, clean_speaker)
        if review_status is not None:
            self.set_segment_review(segment_id, review_status)
        self._refresh_transcript(int(row["transcript_id"]))
        return self._segment(segment_id)

    def merge_segments(self, first_id: int, second_id: int) -> dict[str, Any]:
        first = self._segment(first_id)
        second = self._segment(second_id)
        if int(first["transcript_id"]) != int(second["transcript_id"]):
            raise ValueError("Segments must belong to the same transcript.")
        if int(second["segment_index"]) != int(first["segment_index"]) + 1:
            raise ValueError("Only adjacent segments can be merged.")
        now = datetime.now().isoformat()
        text = f'{str(first["text"]).strip()} {str(second["text"]).strip()}'.strip()
        confidence_values = [v for v in (first.get("confidence"), second.get("confidence")) if v is not None]
        confidence = sum(float(v) for v in confidence_values) / len(confidence_values) if confidence_values else None
        self.db.execute(
            """UPDATE transcript_segments SET end_seconds=?,text=?,speaker=?,confidence=?,updated_at=?
               WHERE id=?""",
            (
                max(float(first["end_seconds"]), float(second["end_seconds"])),
                text,
                first.get("speaker") or second.get("speaker"),
                confidence,
                now,
                int(first_id),
            ),
        )
        self.db.execute("DELETE FROM transcript_words WHERE segment_id=?", (int(second_id),))
        self.db.execute("DELETE FROM transcript_segment_reviews WHERE segment_id=?", (int(second_id),))
        self.db.execute("DELETE FROM transcript_segments WHERE id=?", (int(second_id),))
        self._reindex_segments(int(first["transcript_id"]))
        self._refresh_transcript(int(first["transcript_id"]))
        return self._segment(first_id)

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
        self.db.execute(
            """UPDATE transcript_segments SET segment_index=segment_index+1
               WHERE transcript_id=? AND segment_index>?""",
            (transcript_id, old_index),
        )
        self.db.execute(
            """UPDATE transcript_segments SET end_seconds=?,text=?,updated_at=? WHERE id=?""",
            (split, str(left_text).strip(), now, int(segment_id)),
        )
        new_id = int(self.db.execute(
            """INSERT INTO transcript_segments(
                transcript_id,segment_index,start_seconds,end_seconds,text,speaker,
                confidence,words_json,tags_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                transcript_id, old_index + 1, split, end, str(right_text).strip(),
                row.get("speaker"), row.get("confidence"), "[]", row.get("tags_json") or "[]",
                now, now,
            ),
        ))
        self._refresh_transcript(transcript_id)
        return self._segment(segment_id), self._segment(new_id)

    def delete_segment(self, segment_id: int) -> None:
        row = self._segment(segment_id)
        transcript_id = int(row["transcript_id"])
        self.db.execute("DELETE FROM transcript_words WHERE segment_id=?", (int(segment_id),))
        self.db.execute("DELETE FROM transcript_segment_reviews WHERE segment_id=?", (int(segment_id),))
        self.db.execute("DELETE FROM transcript_segments WHERE id=?", (int(segment_id),))
        self._reindex_segments(transcript_id)
        self._refresh_transcript(transcript_id)

    def set_segment_review(self, segment_id: int, status: str, reviewed_by: str | None = None) -> None:
        allowed = {"Unreviewed", "Reviewed", "Needs revision"}
        if status not in allowed:
            raise ValueError(f"Review status must be one of: {', '.join(sorted(allowed))}")
        now = datetime.now().isoformat()
        self.db.execute(
            """INSERT INTO transcript_segment_reviews(
                segment_id,review_status,reviewed_at,reviewed_by,updated_at
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(segment_id) DO UPDATE SET
                review_status=excluded.review_status,
                reviewed_at=excluded.reviewed_at,
                reviewed_by=excluded.reviewed_by,
                updated_at=excluded.updated_at""",
            (int(segment_id), status, now if status == "Reviewed" else None, reviewed_by, now),
        )

    def upsert_speaker(self, transcript_id: int, speaker_key: str,
                       display_name: str, color: str | None = None,
                       notes: str | None = None) -> int:
        now = datetime.now().isoformat()
        self.db.execute(
            """INSERT INTO transcript_speakers(
                transcript_id,speaker_key,display_name,color,notes,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(transcript_id,speaker_key) DO UPDATE SET
                display_name=excluded.display_name,color=excluded.color,
                notes=excluded.notes,updated_at=excluded.updated_at""",
            (int(transcript_id), str(speaker_key), str(display_name), color, notes, now, now),
        )
        frame = self.db.frame(
            "SELECT id FROM transcript_speakers WHERE transcript_id=? AND speaker_key=?",
            (int(transcript_id), str(speaker_key)),
        )
        return int(frame.iloc[0]["id"])

    def speakers(self, transcript_id: int):
        return self.db.frame(
            "SELECT * FROM transcript_speakers WHERE transcript_id=? ORDER BY display_name",
            (int(transcript_id),),
        )

    def rename_chapter(self, chapter_id: int, title: str) -> None:
        clean = re.sub(r"\s+", " ", str(title)).strip()
        if not clean:
            raise ValueError("Chapter title cannot be empty.")
        self.db.execute(
            "UPDATE transcript_chapters SET title=?,source='manual',updated_at=? WHERE id=?",
            (clean, datetime.now().isoformat(), int(chapter_id)),
        )

    def delete_chapter(self, chapter_id: int) -> None:
        chapter = self._chapter(chapter_id)
        self.db.execute("DELETE FROM transcript_chapters WHERE id=?", (int(chapter_id),))
        self._reindex_chapters(int(chapter["transcript_id"]))

    def merge_chapters(self, first_id: int, second_id: int, title: str | None = None) -> None:
        first = self._chapter(first_id)
        second = self._chapter(second_id)
        if int(first["transcript_id"]) != int(second["transcript_id"]):
            raise ValueError("Chapters must belong to the same transcript.")
        if int(second["chapter_index"]) != int(first["chapter_index"]) + 1:
            raise ValueError("Only adjacent chapters can be merged.")
        now = datetime.now().isoformat()
        merged_title = str(title or first["title"]).strip()
        merged_summary = " ".join(filter(None, [first.get("summary"), second.get("summary")])).strip()
        self.db.execute(
            """UPDATE transcript_chapters SET end_seconds=?,title=?,summary=?,
               source='manual',updated_at=? WHERE id=?""",
            (float(second["end_seconds"]), merged_title, merged_summary, now, int(first_id)),
        )
        self.db.execute("DELETE FROM transcript_chapters WHERE id=?", (int(second_id),))
        self._reindex_chapters(int(first["transcript_id"]))

    def split_chapter(self, chapter_id: int, split_seconds: float,
                      second_title: str | None = None) -> int:
        chapter = self._chapter(chapter_id)
        split = float(split_seconds)
        if not float(chapter["start_seconds"]) < split < float(chapter["end_seconds"]):
            raise ValueError("Split time must fall inside the chapter.")
        transcript_id = int(chapter["transcript_id"])
        index = int(chapter["chapter_index"])
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE transcript_chapters SET chapter_index=chapter_index+1
               WHERE transcript_id=? AND chapter_index>?""",
            (transcript_id, index),
        )
        old_end = float(chapter["end_seconds"])
        self.db.execute(
            "UPDATE transcript_chapters SET end_seconds=?,source='manual',updated_at=? WHERE id=?",
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

    def create_manual_chapter(self, transcript_id: int, start_seconds: float,
                              end_seconds: float, title: str) -> int:
        start = float(start_seconds)
        end = float(end_seconds)
        if start < 0 or end <= start:
            raise ValueError("Chapter end must be after its start.")
        clean = re.sub(r"\s+", " ", str(title)).strip()
        if not clean:
            raise ValueError("Chapter title cannot be empty.")
        frame = self.db.frame(
            "SELECT COALESCE(MAX(chapter_index),-1)+1 AS next_index FROM transcript_chapters WHERE transcript_id=?",
            (int(transcript_id),),
        )
        index = int(frame.iloc[0]["next_index"])
        now = datetime.now().isoformat()
        return int(self.db.execute(
            """INSERT INTO transcript_chapters(
                transcript_id,chapter_index,start_seconds,end_seconds,title,
                keywords_json,confidence,source,review_status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (int(transcript_id), index, start, end, clean, "[]", 1.0, "manual", "Unreviewed", now, now),
        ))

    def add_clip_candidate(self, transcript_id: int, start_seconds: float,
                           end_seconds: float, title: str = "",
                           reason: str = "", score: float = 0.0,
                           source: str = "manual") -> int:
        start = float(start_seconds)
        end = float(end_seconds)
        if start < 0 or end <= start:
            raise ValueError("Clip end must be after its start.")
        now = datetime.now().isoformat()
        return int(self.db.execute(
            """INSERT INTO transcript_clip_candidates(
                transcript_id,start_seconds,end_seconds,title,reason,score,source,
                created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (int(transcript_id), start, end, title, reason, float(score), source, now, now),
        ))

    def _segment(self, segment_id: int) -> dict[str, Any]:
        frame = self.db.frame("SELECT * FROM transcript_segments WHERE id=?", (int(segment_id),))
        if frame.empty:
            raise KeyError(segment_id)
        return frame.iloc[0].to_dict()

    def _chapter(self, chapter_id: int) -> dict[str, Any]:
        frame = self.db.frame("SELECT * FROM transcript_chapters WHERE id=?", (int(chapter_id),))
        if frame.empty:
            raise KeyError(chapter_id)
        return frame.iloc[0].to_dict()

    def _reindex_segments(self, transcript_id: int) -> None:
        rows = self.db.frame(
            "SELECT id FROM transcript_segments WHERE transcript_id=? ORDER BY start_seconds,id",
            (int(transcript_id),),
        )
        for index, row in rows.iterrows():
            self.db.execute(
                "UPDATE transcript_segments SET segment_index=? WHERE id=?",
                (int(index), int(row["id"])),
            )

    def _reindex_chapters(self, transcript_id: int) -> None:
        rows = self.db.frame(
            "SELECT id FROM transcript_chapters WHERE transcript_id=? ORDER BY start_seconds,id",
            (int(transcript_id),),
        )
        for index, row in rows.iterrows():
            self.db.execute(
                "UPDATE transcript_chapters SET chapter_index=? WHERE id=?",
                (int(index), int(row["id"])),
            )

    def _refresh_transcript(self, transcript_id: int) -> None:
        segments = self.segments(transcript_id)
        duration = float(segments["end_seconds"].max()) if not segments.empty else 0.0
        words = sum(
            len(re.findall(r"\b[\w'-]+\b", str(value)))
            for value in segments.get("text", [])
        )
        confidence = segments["confidence"].dropna() if not segments.empty and "confidence" in segments else []
        self.db.execute(
            """UPDATE transcripts SET duration_seconds=?,word_count=?,segment_count=?,
               confidence=?,updated_at=? WHERE id=?""",
            (
                duration, words, len(segments),
                float(confidence.mean()) if len(confidence) else None,
                datetime.now().isoformat(), int(transcript_id),
            ),
        )
        self.build_search_index(transcript_id)
