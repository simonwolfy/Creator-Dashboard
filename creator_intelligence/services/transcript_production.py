from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Iterable


CLIP_REVIEW_STATUSES = ("Unreviewed", "Approved", "Rejected", "Needs work")


class TranscriptProductionMixin:
    """Creator review, clip intelligence, and production handoff operations."""

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
        self._ensure_clip_intelligence_columns()

    def _ensure_clip_intelligence_columns(self) -> None:
        existing = {
            str(row["name"])
            for _, row in self.db.frame(
                "PRAGMA table_info(transcript_clip_candidates)"
            ).iterrows()
        }
        columns = {
            "hook_score": "REAL",
            "humor_score": "REAL",
            "surprise_score": "REAL",
            "emotion_score": "REAL",
            "quote_score": "REAL",
            "viral_score": "REAL",
            "suggested_start_seconds": "REAL",
            "suggested_end_seconds": "REAL",
            "suggested_title": "TEXT",
            "suggested_caption": "TEXT",
            "suggested_hashtags_json": "TEXT",
            "intelligence_version": "TEXT",
            "analyzed_at": "TEXT",
        }
        for name, sql_type in columns.items():
            if name not in existing:
                self.db.execute(
                    f"ALTER TABLE transcript_clip_candidates ADD COLUMN {name} {sql_type}"
                )

    def clip_candidates(self, transcript_id: int, review_status: str | None = None):
        sql = """SELECT c.id,c.transcript_id,c.start_seconds,c.end_seconds,
                        c.title,c.reason,c.score,c.source,c.review_status,c.created_at,
                        c.hook_score,c.humor_score,c.surprise_score,c.emotion_score,
                        c.quote_score,c.viral_score,c.suggested_start_seconds,
                        c.suggested_end_seconds,c.suggested_title,c.suggested_caption,
                        c.suggested_hashtags_json,c.intelligence_version,c.analyzed_at,
                        CASE WHEN j.id IS NULL THEN 0 ELSE 1 END AS sent_to_production,
                        j.id AS production_job_id,j.status AS production_status
                 FROM transcript_clip_candidates c
                 LEFT JOIN production_clip_jobs j ON j.clip_candidate_id=c.id
                 WHERE c.transcript_id=?"""
        params: list[object] = [int(transcript_id)]
        if review_status and review_status != "All":
            sql += " AND c.review_status=?"
            params.append(review_status)
        sql += " ORDER BY COALESCE(c.viral_score,c.score) DESC,c.start_seconds,c.id"
        return self.db.frame(sql, params)

    def analyze_clip_candidates(self, clip_ids: Iterable[int]) -> list[dict]:
        results = []
        for clip_id in dict.fromkeys(int(value) for value in clip_ids):
            results.append(self.analyze_clip_candidate(clip_id))
        return results

    def analyze_clip_candidate(self, clip_id: int) -> dict:
        frame = self.db.frame(
            "SELECT * FROM transcript_clip_candidates WHERE id=?", (int(clip_id),)
        )
        if frame.empty:
            raise KeyError(clip_id)
        clip = frame.iloc[0].to_dict()
        transcript_id = int(clip["transcript_id"])
        start = float(clip["start_seconds"])
        end = float(clip["end_seconds"])
        segments = self.segments(transcript_id, start=start, end=end)
        text = " ".join(
            str(value).strip() for value in segments.get("text", []) if str(value).strip()
        ).strip()
        if not text:
            text = str(clip.get("title") or "").strip()

        analysis = self._score_clip_text(text, start, end)
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE transcript_clip_candidates SET
               hook_score=?,humor_score=?,surprise_score=?,emotion_score=?,
               quote_score=?,viral_score=?,suggested_start_seconds=?,
               suggested_end_seconds=?,suggested_title=?,suggested_caption=?,
               suggested_hashtags_json=?,intelligence_version=?,analyzed_at=?,
               updated_at=? WHERE id=?""",
            (
                analysis["hook_score"], analysis["humor_score"],
                analysis["surprise_score"], analysis["emotion_score"],
                analysis["quote_score"], analysis["viral_score"],
                analysis["suggested_start_seconds"],
                analysis["suggested_end_seconds"], analysis["suggested_title"],
                analysis["suggested_caption"],
                json.dumps(analysis["suggested_hashtags"]),
                "local-heuristic-v1", now, now, int(clip_id),
            ),
        )
        return {"id": int(clip_id), **analysis}

    @staticmethod
    def _score_clip_text(text: str, start: float, end: float) -> dict:
        clean = re.sub(r"\s+", " ", text).strip()
        lowered = clean.lower()
        words = re.findall(r"\b[\w'-]+\b", clean)
        word_count = len(words)
        duration = max(0.1, end - start)

        questions = clean.count("?")
        exclamations = clean.count("!")
        first_words = " ".join(words[:12]).lower()
        hook_terms = {
            "wait", "look", "listen", "what", "why", "how", "never", "secret",
            "crazy", "actually", "imagine", "guess", "watch", "this", "here",
        }
        humor_terms = {
            "lol", "lmao", "funny", "joke", "laugh", "ridiculous", "stupid",
            "dumb", "bro", "bruh", "what the", "no way", "potato", "bonk",
        }
        surprise_terms = {
            "wow", "whoa", "wait", "suddenly", "unexpected", "secret", "found",
            "discovered", "no way", "what", "oh my", "seriously", "actually",
        }
        emotion_terms = {
            "love", "hate", "angry", "mad", "terrified", "scared", "sad", "happy",
            "excited", "insane", "amazing", "awful", "panic", "rage", "scream",
        }

        def matches(terms: set[str]) -> int:
            return sum(1 for term in terms if term in lowered)

        hook = 28 + min(30, questions * 10 + exclamations * 6)
        hook += min(24, matches(hook_terms) * 6)
        if any(first_words.startswith(term) for term in hook_terms):
            hook += 12
        if 6 <= duration <= 45:
            hook += 8

        humor = 12 + min(70, matches(humor_terms) * 14)
        humor += min(18, exclamations * 4)

        surprise = 15 + min(65, matches(surprise_terms) * 11)
        surprise += min(20, questions * 5 + exclamations * 5)

        emotion = 15 + min(65, matches(emotion_terms) * 12)
        emotion += min(20, exclamations * 5)

        quote = 20
        if 5 <= word_count <= 45:
            quote += 25
        if questions or exclamations:
            quote += 15
        if len(clean) <= 220:
            quote += 15
        unique_ratio = len(set(word.lower() for word in words)) / max(1, word_count)
        quote += min(20, unique_ratio * 20)

        scores = [
            max(0.0, min(100.0, value))
            for value in (hook, humor, surprise, emotion, quote)
        ]
        hook, humor, surprise, emotion, quote = scores
        viral = (
            hook * 0.30 + humor * 0.18 + surprise * 0.20
            + emotion * 0.14 + quote * 0.18
        )
        if 8 <= duration <= 60:
            viral += 6
        viral = max(0.0, min(100.0, viral))

        suggested_start = max(0.0, start - min(1.5, start))
        suggested_end = end + (1.0 if duration < 60 else 0.0)
        title = TranscriptProductionMixin._suggest_title(clean)
        caption = TranscriptProductionMixin._suggest_caption(clean, title)
        hashtags = TranscriptProductionMixin._suggest_hashtags(lowered)

        return {
            "hook_score": round(hook, 1),
            "humor_score": round(humor, 1),
            "surprise_score": round(surprise, 1),
            "emotion_score": round(emotion, 1),
            "quote_score": round(quote, 1),
            "viral_score": round(viral, 1),
            "suggested_start_seconds": round(suggested_start, 2),
            "suggested_end_seconds": round(suggested_end, 2),
            "suggested_title": title,
            "suggested_caption": caption,
            "suggested_hashtags": hashtags,
        }

    @staticmethod
    def _suggest_title(text: str) -> str:
        if not text:
            return "Untitled Clip"
        sentence = re.split(r"(?<=[.!?])\s+", text)[0].strip(" .!?")
        words = sentence.split()
        if len(words) > 10:
            sentence = " ".join(words[:10]) + "…"
        return sentence[:72] or "Untitled Clip"

    @staticmethod
    def _suggest_caption(text: str, title: str) -> str:
        if not text:
            return title
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) > 180:
            compact = compact[:180].rsplit(" ", 1)[0] + "…"
        return compact

    @staticmethod
    def _suggest_hashtags(lowered: str) -> list[str]:
        tags = ["#gaming", "#streamer", "#clips"]
        topic_map = {
            "minecraft": "#minecraft",
            "tarkov": "#escapefromtarkov",
            "rimworld": "#rimworld",
            "pokemon": "#pokemon",
            "funny": "#funny",
            "secret": "#discovery",
            "boss": "#bossfight",
            "death": "#gamingfails",
        }
        for token, tag in topic_map.items():
            if token in lowered and tag not in tags:
                tags.append(tag)
        return tags[:6]

    def set_clip_review_status(self, clip_ids: Iterable[int], status: str) -> int:
        if status not in CLIP_REVIEW_STATUSES:
            raise ValueError(status)
        now = datetime.now().isoformat()
        count = 0
        for clip_id in {int(value) for value in clip_ids}:
            cursor = self.db.execute(
                """UPDATE transcript_clip_candidates
                   SET review_status=?,updated_at=? WHERE id=?""",
                (status, now, clip_id),
            )
            count += int(getattr(cursor, "rowcount", 1) or 0)
        return count

    def send_clips_to_production(
        self,
        clip_ids: Iterable[int],
        *,
        export_preset: str = "YouTube Shorts",
        priority: str = "Normal",
        destination: str | None = None,
    ) -> list[int]:
        now = datetime.now().isoformat()
        created: list[int] = []
        for clip_id in {int(value) for value in clip_ids}:
            frame = self.db.frame(
                "SELECT * FROM transcript_clip_candidates WHERE id=?",
                (clip_id,),
            )
            if frame.empty:
                raise KeyError(clip_id)
            row = frame.iloc[0].to_dict()
            if row.get("review_status") == "Rejected":
                raise ValueError("Rejected clips cannot be sent to production.")
            existing = self.db.frame(
                "SELECT id FROM production_clip_jobs WHERE clip_candidate_id=?",
                (clip_id,),
            )
            if not existing.empty:
                created.append(int(existing.iloc[0]["id"]))
                continue
            job_id = int(self.db.execute(
                """INSERT INTO production_clip_jobs(
                    clip_candidate_id,transcript_id,title,start_seconds,end_seconds,
                    status,priority,export_preset,destination,source_reason,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,'New',?,?,?,?,?,?)""",
                (
                    clip_id,
                    int(row["transcript_id"]),
                    str(row.get("suggested_title") or row.get("title") or f"Clip {clip_id}"),
                    float(row.get("suggested_start_seconds") or row["start_seconds"]),
                    float(row.get("suggested_end_seconds") or row["end_seconds"]),
                    priority,
                    export_preset,
                    destination,
                    row.get("reason"),
                    now,
                    now,
                ),
            ))
            created.append(job_id)
            self.db.execute(
                """UPDATE transcript_clip_candidates
                   SET review_status='Approved',updated_at=? WHERE id=?""",
                (now, clip_id),
            )
        return created
