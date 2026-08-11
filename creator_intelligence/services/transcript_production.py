from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from datetime import datetime

CLIP_REVIEW_STATUSES = ("Unreviewed", "Approved", "Rejected", "Needs work")
TRANSCRIPT_DISCOVERY_SOURCE = "automatic-transcript-discovery-v2"
LEGACY_TRANSCRIPT_DISCOVERY_SOURCES = (
    "automatic-transcript-discovery-v1",
    TRANSCRIPT_DISCOVERY_SOURCE,
)


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
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS transcript_discovery_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id INTEGER NOT NULL,
                algorithm_version TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Running',
                segments_scanned INTEGER NOT NULL DEFAULT 0,
                windows_considered INTEGER NOT NULL DEFAULT 0,
                candidates_created INTEGER NOT NULL DEFAULT 0,
                duplicates_removed INTEGER NOT NULL DEFAULT 0,
                settings_json TEXT,
                error_message TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT
            )"""
        )
        self.db.execute(
            """CREATE INDEX IF NOT EXISTS idx_transcript_discovery_runs
               ON transcript_discovery_runs(transcript_id,started_at)"""
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
            "discovery_run_id": "INTEGER",
            "discovery_rank": "REAL",
            "creator_dna_score": "REAL",
            "discovery_chapter_id": "INTEGER",
            "discovery_chapter_title": "TEXT",
            "range_edited_at": "TEXT",
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
                        c.discovery_run_id,c.discovery_rank,c.creator_dna_score,
                        c.discovery_chapter_id,c.discovery_chapter_title,
                        c.range_edited_at,
                        CASE WHEN j.id IS NULL THEN 0 ELSE 1 END AS sent_to_production,
                        j.id AS production_job_id,j.status AS production_status
                 FROM transcript_clip_candidates c
                 LEFT JOIN production_clip_jobs j ON j.clip_candidate_id=c.id
                 WHERE c.transcript_id=?"""
        params: list[object] = [int(transcript_id)]
        if review_status and review_status != "All":
            sql += " AND c.review_status=?"
            params.append(review_status)
        sql += " ORDER BY COALESCE(c.discovery_rank,c.viral_score,c.score) DESC,c.start_seconds,c.id"
        return self.db.frame(sql, params)

    def discover_clip_candidates(
        self,
        transcript_id: int,
        *,
        min_score: float = 55.0,
        max_candidates: int = 20,
        min_seconds: float = 8.0,
        max_seconds: float = 60.0,
        overlap_threshold: float = 0.55,
        replace_unreviewed: bool = True,
    ) -> dict:
        """Scan a complete transcript and stage ranked moments for creator review."""
        transcript_id = int(transcript_id)
        min_score = float(min_score)
        max_candidates = int(max_candidates)
        min_seconds = float(min_seconds)
        max_seconds = float(max_seconds)
        overlap_threshold = float(overlap_threshold)
        if not 0 <= min_score <= 100:
            raise ValueError("Minimum score must be between 0 and 100.")
        if max_candidates < 1:
            raise ValueError("Maximum candidates must be at least 1.")
        if min_seconds <= 0 or max_seconds < min_seconds:
            raise ValueError("Clip duration limits are invalid.")
        if not 0 < overlap_threshold <= 1:
            raise ValueError("Overlap threshold must be greater than 0 and at most 1.")

        # Resolve the transcript up front so an invalid id does not create a run row.
        self.transcript(transcript_id)
        settings = {
            "min_score": min_score,
            "max_candidates": max_candidates,
            "min_seconds": min_seconds,
            "max_seconds": max_seconds,
            "overlap_threshold": overlap_threshold,
            "replace_unreviewed": bool(replace_unreviewed),
        }
        started_at = datetime.now().isoformat()
        run_id = int(self.db.execute(
            """INSERT INTO transcript_discovery_runs(
                transcript_id,algorithm_version,status,settings_json,started_at
            ) VALUES(?,?,'Running',?,?)""",
            (
                transcript_id,
                TRANSCRIPT_DISCOVERY_SOURCE,
                json.dumps(settings, sort_keys=True),
                started_at,
            ),
        ))
        try:
            segments = self.segments(transcript_id)
            ordered = self._discovery_segments(segments)
            chapters = self.chapters(transcript_id)
            if ordered and chapters.empty:
                self.build_chapters(transcript_id)
                chapters = self.chapters(transcript_id)
            discovery_chapters = self._discovery_chapters(chapters)
            if replace_unreviewed:
                self.db.execute(
                    """DELETE FROM transcript_clip_candidates
                       WHERE transcript_id=? AND source IN (?,?)
                         AND review_status='Unreviewed'
                         AND NOT EXISTS(
                             SELECT 1 FROM production_clip_jobs j
                             WHERE j.clip_candidate_id=transcript_clip_candidates.id
                         )""",
                    (transcript_id, *LEGACY_TRANSCRIPT_DISCOVERY_SOURCES),
                )
            protected = self._protected_clip_ranges(transcript_id)

            windows = self._candidate_windows(
                ordered,
                chapters=discovery_chapters,
                min_score=min_score,
                min_seconds=min_seconds,
                max_seconds=max_seconds,
            )
            transcript = self.transcript(transcript_id)
            metadata = str(transcript.get("title") or "")
            windows = [
                self._enrich_discovery_window(window, metadata)
                for window in windows
            ]
            considered = len(windows)
            selected: list[dict] = []
            duplicates_removed = 0
            for window in sorted(
                windows,
                key=lambda item: (-item["discovery_rank"], item["start_seconds"]),
            ):
                interval = (window["start_seconds"], window["end_seconds"])
                conflicts = protected + [
                    (item["start_seconds"], item["end_seconds"])
                    for item in selected
                ]
                if any(
                    self._interval_overlap_ratio(interval, existing) >= overlap_threshold
                    for existing in conflicts
                ):
                    duplicates_removed += 1
                    continue
                selected.append(window)
                if len(selected) >= max_candidates:
                    break

            created_ids: list[int] = []
            for window in selected:
                clip_id = self.add_clip_candidate(
                    transcript_id,
                    window["start_seconds"],
                    window["end_seconds"],
                    window["suggested_title"],
                    window["selection_reason"],
                    window["viral_score"],
                    TRANSCRIPT_DISCOVERY_SOURCE,
                )
                analysis = self.analyze_clip_candidate(clip_id)
                analysis["suggested_start_seconds"] = round(
                    max(
                        float(window["start_seconds"]),
                        float(analysis["suggested_start_seconds"]),
                    ),
                    2,
                )
                analysis["suggested_end_seconds"] = round(
                    min(
                        float(window["end_seconds"]),
                        float(analysis["suggested_end_seconds"]),
                    ),
                    2,
                )
                dna_score = self._creator_dna_candidate_score(analysis)
                discovery_rank = self._discovery_rank(analysis, dna_score)
                reason = self._discovery_reason(
                    analysis,
                    dna_score,
                    discovery_rank,
                    window.get("chapter_title"),
                )
                self.db.execute(
                    """UPDATE transcript_clip_candidates
                       SET discovery_run_id=?,discovery_rank=?,creator_dna_score=?,
                           discovery_chapter_id=?,discovery_chapter_title=?,reason=?,
                           suggested_start_seconds=?,suggested_end_seconds=?,updated_at=?
                       WHERE id=?""",
                    (
                        run_id,
                        discovery_rank,
                        dna_score,
                        window.get("chapter_id"),
                        window.get("chapter_title"),
                        reason,
                        analysis["suggested_start_seconds"],
                        analysis["suggested_end_seconds"],
                        datetime.now().isoformat(),
                        clip_id,
                    ),
                )
                created_ids.append(clip_id)

            completed_at = datetime.now().isoformat()
            self.db.execute(
                """UPDATE transcript_discovery_runs SET
                   status='Completed',segments_scanned=?,windows_considered=?,
                   candidates_created=?,duplicates_removed=?,completed_at=?
                   WHERE id=?""",
                (
                    len(ordered),
                    considered,
                    len(created_ids),
                    duplicates_removed,
                    completed_at,
                    run_id,
                ),
            )
            return {
                "run_id": run_id,
                "transcript_id": transcript_id,
                "segments_scanned": len(ordered),
                "windows_considered": considered,
                "candidates_created": len(created_ids),
                "duplicates_removed": duplicates_removed,
                "candidate_ids": created_ids,
                "status": "Completed",
            }
        except Exception as exc:
            self.db.execute(
                """UPDATE transcript_discovery_runs
                   SET status='Failed',error_message=?,completed_at=? WHERE id=?""",
                (str(exc), datetime.now().isoformat(), run_id),
            )
            raise

    @staticmethod
    def _discovery_segments(frame) -> list[dict]:
        if frame.empty:
            return []
        rows: list[dict] = []
        for _, raw in frame.sort_values(["start_seconds", "end_seconds", "id"]).iterrows():
            text = re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()
            try:
                start = float(raw["start_seconds"])
                end = float(raw["end_seconds"])
            except (TypeError, ValueError):
                continue
            if not text or not math.isfinite(start) or not math.isfinite(end) or end <= start:
                continue
            rows.append({"start": max(0.0, start), "end": end, "text": text})
        return rows

    @staticmethod
    def _discovery_chapters(frame) -> list[dict]:
        if frame.empty:
            return []
        chapters: list[dict] = []
        for _, raw in frame.sort_values(
            ["start_seconds", "end_seconds", "chapter_index"]
        ).iterrows():
            try:
                start = float(raw["start_seconds"])
                end = float(raw["end_seconds"])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                continue
            chapters.append({
                "id": int(raw["id"]),
                "start": max(0.0, start),
                "end": end,
                "title": str(raw.get("title") or "").strip(),
            })
        return chapters

    def _candidate_windows(
        self,
        segments: list[dict],
        *,
        chapters: list[dict] | None = None,
        min_score: float,
        min_seconds: float,
        max_seconds: float,
    ) -> list[dict]:
        windows: list[dict] = []
        anchor_floor = max(30.0, min_score - 18.0)
        for index, segment in enumerate(segments):
            anchor = self._score_clip_text(
                segment["text"], segment["start"], segment["end"]
            )
            if float(anchor["viral_score"]) < anchor_floor:
                continue
            midpoint = (segment["start"] + segment["end"]) / 2.0
            chapter = next(
                (
                    item for item in (chapters or [])
                    if item["start"] <= midpoint <= item["end"]
                ),
                None,
            )
            chapter_start = float(chapter["start"]) if chapter else 0.0
            chapter_end = float(chapter["end"]) if chapter else math.inf
            target_start = max(chapter_start, segment["start"] - 8.0)
            target_end = min(
                chapter_end,
                target_start + max_seconds,
                segment["end"] + 22.0,
            )
            left = index
            while (
                left > 0
                and segments[left - 1]["end"] > target_start
                and segments[left - 1]["start"] >= chapter_start
            ):
                left -= 1
            right = index
            while (
                right + 1 < len(segments)
                and segments[right + 1]["start"] < target_end
                and segments[right + 1]["end"] <= chapter_end
            ):
                right += 1
            while (
                right + 1 < len(segments)
                and segments[right]["end"] - segments[left]["start"] < min_seconds
                and segments[right + 1]["end"] <= chapter_end
            ):
                if (
                    segments[right + 1]["end"] - segments[left]["start"]
                    > max_seconds
                ):
                    break
                right += 1
            start = max(chapter_start, segments[left]["start"])
            end = min(chapter_end, segments[right]["end"], start + max_seconds)
            if end - start < min_seconds:
                continue
            text = " ".join(
                item["text"] for item in segments[left:right + 1]
                if item["start"] < end and item["end"] > start
            )
            analysis = self._score_clip_text(text, start, end)
            if float(analysis["viral_score"]) < min_score:
                continue
            windows.append({
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "text": text,
                "chapter_id": chapter.get("id") if chapter else None,
                "chapter_title": chapter.get("title") if chapter else None,
                **analysis,
            })
        return windows

    def _enrich_discovery_window(self, window: dict, metadata: str) -> dict:
        from creator_intelligence.services.creator_packaging_context import (
            extract_packaging_context,
        )

        enriched = dict(window)
        context = extract_packaging_context(
            str(window.get("text") or ""), metadata, window
        ).as_dict()
        candidates = self._title_options(context)
        titles, ranking = self._rank_titles_for_creator(
            candidates, 0, include_scores=True
        )
        title = titles[0] if titles else str(window.get("suggested_title") or "")
        selected = next(
            (
                item for item in ranking
                if str(item.get("title") or "") == title
            ),
            ranking[0] if ranking else {},
        )
        style = float(selected.get("style_score") or 0.0)
        similarity = float(selected.get("duplicate_similarity") or 0.0)
        dna_score = round(
            max(0.0, min(100.0, 50.0 + style - similarity * 20.0)), 1
        )
        preview_rank = round(
            max(
                0.0,
                min(
                    100.0,
                    float(window.get("viral_score") or 0.0) * 0.8
                    + dna_score * 0.2,
                ),
            ),
            1,
        )
        enriched.update({
            "suggested_title": title,
            "creator_dna_score": dna_score,
            "discovery_rank": preview_rank,
            "selection_reason": self._discovery_reason(
                window,
                dna_score,
                preview_rank,
                window.get("chapter_title"),
            ),
        })
        return enriched

    @staticmethod
    def _discovery_reason(
        analysis: dict,
        dna_score: float,
        discovery_rank: float,
        chapter_title: str | None,
    ) -> str:
        dimensions = {
            "hook": float(analysis.get("hook_score") or 0.0),
            "humor": float(analysis.get("humor_score") or 0.0),
            "surprise": float(analysis.get("surprise_score") or 0.0),
            "emotion": float(analysis.get("emotion_score") or 0.0),
            "standalone quote": float(analysis.get("quote_score") or 0.0),
        }
        strongest = sorted(
            dimensions.items(), key=lambda item: (-item[1], item[0])
        )[:2]
        signals = " and ".join(
            f"{label} {score:.0f}" for label, score in strongest
        )
        chapter = (
            f' in chapter “{str(chapter_title).strip()}”'
            if str(chapter_title or "").strip()
            else ""
        )
        return (
            f"Full-transcript candidate{chapter}: {signals}; Creator DNA "
            f"fit {float(dna_score):.0f}; ranked {float(discovery_rank):.1f}/100. "
            "Creator approval is required before Production."
        )

    def _protected_clip_ranges(self, transcript_id: int) -> list[tuple[float, float]]:
        frame = self.db.frame(
            """SELECT c.start_seconds,c.end_seconds
               FROM transcript_clip_candidates c
               WHERE c.transcript_id=?""",
            (int(transcript_id),),
        )
        return [
            (float(row["start_seconds"]), float(row["end_seconds"]))
            for _, row in frame.iterrows()
        ]

    @staticmethod
    def _interval_overlap_ratio(
        first: tuple[float, float], second: tuple[float, float]
    ) -> float:
        overlap = max(0.0, min(first[1], second[1]) - max(first[0], second[0]))
        shorter = min(first[1] - first[0], second[1] - second[0])
        return overlap / shorter if shorter > 0 else 0.0

    @staticmethod
    def _creator_dna_candidate_score(analysis: dict) -> float:
        context = analysis.get("packaging_context") or {}
        ranking = context.get("title_ranking") or []
        selected_title = str(analysis.get("suggested_title") or "")
        selected = next(
            (item for item in ranking if str(item.get("title") or "") == selected_title),
            ranking[0] if ranking else {},
        )
        style = float(selected.get("style_score") or 0.0)
        duplicate_similarity = float(selected.get("duplicate_similarity") or 0.0)
        return round(max(0.0, min(100.0, 50.0 + style - duplicate_similarity * 20.0)), 1)

    @staticmethod
    def _discovery_rank(analysis: dict, dna_score: float) -> float:
        rank = (
            float(analysis.get("viral_score") or 0.0) * 0.55
            + float(analysis.get("replayability_score") or 0.0) * 0.10
            + float(analysis.get("shareability_score") or 0.0) * 0.10
            + float(analysis.get("retention_estimate") or 0.0) * 0.05
            + float(dna_score) * 0.20
        )
        return round(max(0.0, min(100.0, rank)), 1)

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
        if str(clip.get("source") or "") in LEGACY_TRANSCRIPT_DISCOVERY_SOURCES:
            analysis["suggested_start_seconds"] = round(
                max(start, float(analysis["suggested_start_seconds"])), 2
            )
            analysis["suggested_end_seconds"] = round(
                min(end, float(analysis["suggested_end_seconds"])), 2
            )
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

    def edit_clip_candidate_range(
        self, clip_id: int, start_seconds: float, end_seconds: float
    ) -> dict:
        clip_id = int(clip_id)
        start = float(start_seconds)
        end = float(end_seconds)
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("Clip boundaries must be finite numbers.")
        if start < 0 or end <= start:
            raise ValueError("Clip end time must be after its non-negative start time.")
        frame = self.db.frame(
            "SELECT * FROM transcript_clip_candidates WHERE id=?", (clip_id,)
        )
        if frame.empty:
            raise KeyError(clip_id)
        before = frame.iloc[0].to_dict()
        handed_off = self.db.frame(
            "SELECT id FROM production_clip_jobs WHERE clip_candidate_id=?",
            (clip_id,),
        )
        if not handed_off.empty:
            raise ValueError(
                "This clip is already in Production. Edit the Production job instead."
            )
        transcript_id = int(before["transcript_id"])
        transcript = self.transcript(transcript_id)
        duration = float(transcript.get("duration_seconds") or 0.0)
        if duration > 0 and end > duration + 0.01:
            raise ValueError(
                f"Clip end time cannot exceed transcript duration ({duration:.2f}s)."
            )

        self.set_clip_review_status([clip_id], "Needs work")
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE transcript_clip_candidates SET
               start_seconds=?,end_seconds=?,suggested_start_seconds=NULL,
               suggested_end_seconds=NULL,hook_score=NULL,humor_score=NULL,
               surprise_score=NULL,emotion_score=NULL,quote_score=NULL,
               viral_score=NULL,discovery_rank=NULL,creator_dna_score=NULL,
               analyzed_at=NULL,range_edited_at=?,updated_at=? WHERE id=?""",
            (start, end, now, now, clip_id),
        )
        analysis = self.analyze_clip_candidate(clip_id)
        analysis["suggested_start_seconds"] = round(start, 2)
        analysis["suggested_end_seconds"] = round(end, 2)
        self.db.execute(
            """UPDATE transcript_clip_candidates SET
               suggested_start_seconds=?,suggested_end_seconds=?,updated_at=?
               WHERE id=?""",
            (start, end, datetime.now().isoformat(), clip_id),
        )
        from creator_intelligence.services.creator_dna import CreatorDNAService

        dna = CreatorDNAService(self.db)
        dna.record_event(
            "clip_range_edited",
            clip_id=clip_id,
            subject_type="clip",
            subject_id=clip_id,
            field_name="time_range",
            old_value={
                "start_seconds": before.get("start_seconds"),
                "end_seconds": before.get("end_seconds"),
            },
            new_value={"start_seconds": start, "end_seconds": end},
            metadata={"clip": dna._clip_snapshot(clip_id), "analysis": analysis},
            source="transcript_review",
        )
        return self.db.frame(
            "SELECT * FROM transcript_clip_candidates WHERE id=?", (clip_id,)
        ).iloc[0].to_dict()

    def set_clip_review_status(self, clip_ids: Iterable[int], status: str) -> int:
        if status not in CLIP_REVIEW_STATUSES:
            raise ValueError(status)
        from creator_intelligence.services.creator_dna import CreatorDNAService
        dna = CreatorDNAService(self.db)
        dna.ensure_event_history()
        now = datetime.now().isoformat()
        count = 0
        for clip_id in {int(value) for value in clip_ids}:
            before = self.db.frame(
                "SELECT * FROM transcript_clip_candidates WHERE id=?", (clip_id,)
            )
            if before.empty:
                raise KeyError(clip_id)
            old_status = str(before.iloc[0].get("review_status") or "Unreviewed")
            cursor = self.db.execute(
                """UPDATE transcript_clip_candidates
                   SET review_status=?,updated_at=? WHERE id=?""",
                (status, now, clip_id),
            )
            count += int(getattr(cursor, "rowcount", 1) or 0)
            if old_status != status:
                after = self.db.frame(
                    "SELECT * FROM transcript_clip_candidates WHERE id=?", (clip_id,)
                ).iloc[0].to_dict()
                event_type = {
                    "Approved": "clip_approved",
                    "Rejected": "clip_rejected",
                    "Needs work": "clip_needs_work",
                    "Unreviewed": "clip_review_reset",
                }[status]
                dna.record_event(
                    event_type,
                    clip_id=clip_id,
                    subject_type="clip",
                    subject_id=clip_id,
                    field_name="decision",
                    old_value=old_status,
                    new_value=status,
                    metadata={"clip": dna._json_safe(after)},
                    source="transcript_review",
                )
        return count

    def send_clips_to_production(
        self,
        clip_ids: Iterable[int],
        *,
        export_preset: str = "YouTube Shorts",
        priority: str = "Normal",
        destination: str | None = None,
    ) -> list[int]:
        from creator_intelligence.services.creator_dna import CreatorDNAService
        dna = CreatorDNAService(self.db)
        dna.ensure_event_history()
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
            if row.get("review_status") != "Approved":
                raise ValueError(
                    "Only approved clips can be sent to Production. Review and approve "
                    "the clip first."
                )
            existing = self.db.frame(
                "SELECT id FROM production_clip_jobs WHERE clip_candidate_id=?",
                (clip_id,),
            )
            if not existing.empty:
                job_id = int(existing.iloc[0]["id"])
            else:
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
                        float(
                            row["start_seconds"]
                            if row.get("range_edited_at")
                            else row.get("suggested_start_seconds")
                            or row["start_seconds"]
                        ),
                        float(
                            row["end_seconds"]
                            if row.get("range_edited_at")
                            else row.get("suggested_end_seconds")
                            or row["end_seconds"]
                        ),
                        priority,
                        export_preset,
                        destination,
                        row.get("reason"),
                        now,
                        now,
                    ),
                ))
            created.append(job_id)
            after = dna._clip_snapshot(clip_id)
            job = self.db.frame(
                "SELECT * FROM production_clip_jobs WHERE id=?", (job_id,)
            ).iloc[0].to_dict()
            dna.record_event(
                "production_handoff",
                clip_id=clip_id,
                subject_type="production_job",
                subject_id=job_id,
                field_name="title",
                new_value=job.get("title"),
                metadata={
                    "copy": {"title": job.get("title")},
                    "clip": after,
                    "job": dna._json_safe(job),
                },
                source="transcript_production",
                event_key=f"production-job-handoff:{job_id}",
            )
        return created
