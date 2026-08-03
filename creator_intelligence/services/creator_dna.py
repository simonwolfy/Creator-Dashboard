from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import re
from typing import Any

import pandas as pd


class CreatorDNAService:
    """Builds a local creator profile from clip decisions and packaging data."""

    PROFILE_VERSION = "creator-dna-v1"

    def __init__(self, db):
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_profiles(
                id INTEGER PRIMARY KEY CHECK(id=1),
                profile_version TEXT NOT NULL,
                approved_clips INTEGER NOT NULL DEFAULT 0,
                rejected_clips INTEGER NOT NULL DEFAULT 0,
                needs_work_clips INTEGER NOT NULL DEFAULT 0,
                average_clip_length REAL NOT NULL DEFAULT 0,
                average_hook REAL NOT NULL DEFAULT 0,
                average_humor REAL NOT NULL DEFAULT 0,
                average_surprise REAL NOT NULL DEFAULT 0,
                average_emotion REAL NOT NULL DEFAULT 0,
                average_quote REAL NOT NULL DEFAULT 0,
                average_viral REAL NOT NULL DEFAULT 0,
                average_retention REAL NOT NULL DEFAULT 0,
                preferred_title_style TEXT,
                preferred_caption_style TEXT,
                favorite_hashtags_json TEXT NOT NULL DEFAULT '[]',
                packaging_confidence REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_learning_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clip_id INTEGER,
                event_type TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_recommendations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_key TEXT NOT NULL UNIQUE,
                recommendation_type TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 50,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                source_clip_id INTEGER,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE INDEX IF NOT EXISTS idx_creator_events_created
               ON creator_learning_events(created_at,event_type)"""
        )

    def record_event(
        self,
        event_type: str,
        *,
        clip_id: int | None = None,
        old_value: str | None = None,
        new_value: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        return int(self.db.execute(
            """INSERT INTO creator_learning_events(
                clip_id,event_type,old_value,new_value,metadata_json,created_at
            ) VALUES(?,?,?,?,?,?)""",
            (
                int(clip_id) if clip_id is not None else None,
                event_type,
                old_value,
                new_value,
                json.dumps(metadata or {}),
                datetime.now().isoformat(),
            ),
        ))

    def rebuild_profile(self) -> dict[str, Any]:
        clips = self._clip_frame()
        approved = clips[clips.get("review_status", pd.Series(dtype=str)) == "Approved"] if not clips.empty else clips
        rejected_count = self._status_count(clips, "Rejected")
        needs_work_count = self._status_count(clips, "Needs work")

        source = approved if not approved.empty else clips.iloc[0:0]
        title_styles = Counter()
        caption_styles = Counter()
        hashtags = Counter()
        for _, row in source.iterrows():
            title_styles[self.classify_title(str(row.get("suggested_title") or row.get("title") or ""))] += 1
            caption_styles[self.classify_caption(
                str(row.get("suggested_caption") or ""),
                str(row.get("caption_style") or ""),
            )] += 1
            for tag in self._load_json(row.get("suggested_hashtags_json"), []):
                hashtags[str(tag)] += 1

        analyzed = int(pd.to_numeric(source.get("viral_score", pd.Series(dtype=float)), errors="coerce").notna().sum())
        confidence = min(100.0, analyzed * 12.5)
        now = datetime.now().isoformat()
        profile = {
            "profile_version": self.PROFILE_VERSION,
            "approved_clips": int(len(approved)),
            "rejected_clips": rejected_count,
            "needs_work_clips": needs_work_count,
            "average_clip_length": self._mean_duration(source),
            "average_hook": self._mean(source, "hook_score"),
            "average_humor": self._mean(source, "humor_score"),
            "average_surprise": self._mean(source, "surprise_score"),
            "average_emotion": self._mean(source, "emotion_score"),
            "average_quote": self._mean(source, "quote_score"),
            "average_viral": self._mean(source, "viral_score"),
            "average_retention": self._mean(source, "retention_estimate"),
            "preferred_title_style": title_styles.most_common(1)[0][0] if title_styles else "Not enough data",
            "preferred_caption_style": caption_styles.most_common(1)[0][0] if caption_styles else "Not enough data",
            "favorite_hashtags": [tag for tag, _ in hashtags.most_common(8)],
            "packaging_confidence": round(confidence, 1),
            "updated_at": now,
        }
        self.db.execute(
            """INSERT INTO creator_profiles(
                id,profile_version,approved_clips,rejected_clips,needs_work_clips,
                average_clip_length,average_hook,average_humor,average_surprise,
                average_emotion,average_quote,average_viral,average_retention,
                preferred_title_style,preferred_caption_style,favorite_hashtags_json,
                packaging_confidence,updated_at
            ) VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                profile_version=excluded.profile_version,
                approved_clips=excluded.approved_clips,
                rejected_clips=excluded.rejected_clips,
                needs_work_clips=excluded.needs_work_clips,
                average_clip_length=excluded.average_clip_length,
                average_hook=excluded.average_hook,
                average_humor=excluded.average_humor,
                average_surprise=excluded.average_surprise,
                average_emotion=excluded.average_emotion,
                average_quote=excluded.average_quote,
                average_viral=excluded.average_viral,
                average_retention=excluded.average_retention,
                preferred_title_style=excluded.preferred_title_style,
                preferred_caption_style=excluded.preferred_caption_style,
                favorite_hashtags_json=excluded.favorite_hashtags_json,
                packaging_confidence=excluded.packaging_confidence,
                updated_at=excluded.updated_at""",
            (
                profile["profile_version"], profile["approved_clips"],
                profile["rejected_clips"], profile["needs_work_clips"],
                profile["average_clip_length"], profile["average_hook"],
                profile["average_humor"], profile["average_surprise"],
                profile["average_emotion"], profile["average_quote"],
                profile["average_viral"], profile["average_retention"],
                profile["preferred_title_style"], profile["preferred_caption_style"],
                json.dumps(profile["favorite_hashtags"]),
                profile["packaging_confidence"], now,
            ),
        )
        self.generate_recommendations(clips)
        return profile

    def creator_dna(self, rebuild: bool = False) -> dict[str, Any]:
        frame = self.db.frame("SELECT * FROM creator_profiles WHERE id=1")
        if rebuild or frame.empty:
            return self.rebuild_profile()
        row = frame.iloc[0].to_dict()
        row["favorite_hashtags"] = self._load_json(row.pop("favorite_hashtags_json", "[]"), [])
        return row

    def generate_recommendations(self, clips: pd.DataFrame | None = None) -> pd.DataFrame:
        clips = self._clip_frame() if clips is None else clips
        now = datetime.now().isoformat()
        recommendations: list[dict[str, Any]] = []
        if not clips.empty:
            status = clips.get("review_status", pd.Series(index=clips.index, dtype=str))
            approved = clips[status == "Approved"]
            unreviewed = clips[status == "Unreviewed"]
            needs_work = clips[status == "Needs work"]
            if len(unreviewed):
                recommendations.append(self._rec(
                    "review-backlog", "Review", 80,
                    f"Review {len(unreviewed)} clip candidate(s)",
                    "These clips have not received a creator decision yet.",
                ))
            ready = approved[approved.get("sent_to_production", pd.Series(0, index=approved.index)).fillna(0).astype(int) == 0]
            if len(ready):
                top = ready.sort_values("viral_score", ascending=False, na_position="last").iloc[0]
                recommendations.append(self._rec(
                    "approved-ready", "Production", 95,
                    f"Send “{top.get('suggested_title') or top.get('title') or 'top clip'}” to production",
                    f"{len(ready)} approved clip(s) are not yet in the production queue.",
                    int(top["id"]),
                ))
            if len(needs_work):
                recommendations.append(self._rec(
                    "needs-work", "Packaging", 70,
                    f"Improve packaging on {len(needs_work)} clip(s)",
                    "Reanalyze or revise their title, caption, hook, or trim before approval.",
                ))
            high = clips[pd.to_numeric(clips.get("viral_score"), errors="coerce").fillna(0) >= 70]
            if len(high) >= 3:
                recommendations.append(self._rec(
                    "compilation", "Opportunity", 65,
                    "Build a high-potential compilation",
                    f"You have {len(high)} clips with a viral score of 70 or higher.",
                ))
        if not recommendations:
            recommendations.append(self._rec(
                "create-clips", "Foundation", 50,
                "Create and review more clip candidates",
                "Creator DNA becomes more reliable as you approve and reject clips.",
            ))

        active_keys = {item["recommendation_key"] for item in recommendations}
        for item in recommendations:
            self.db.execute(
                """INSERT INTO creator_recommendations(
                    recommendation_key,recommendation_type,priority,title,description,
                    source_clip_id,completed,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,0,?,?)
                ON CONFLICT(recommendation_key) DO UPDATE SET
                    recommendation_type=excluded.recommendation_type,
                    priority=excluded.priority,title=excluded.title,
                    description=excluded.description,
                    source_clip_id=excluded.source_clip_id,
                    completed=0,updated_at=excluded.updated_at""",
                (
                    item["recommendation_key"], item["recommendation_type"],
                    item["priority"], item["title"], item["description"],
                    item.get("source_clip_id"), now, now,
                ),
            )
        existing = self.db.frame("SELECT recommendation_key FROM creator_recommendations WHERE completed=0")
        for key in existing.get("recommendation_key", []):
            if str(key) not in active_keys:
                self.db.execute(
                    "UPDATE creator_recommendations SET completed=1,updated_at=? WHERE recommendation_key=?",
                    (now, str(key)),
                )
        return self.recommendations()

    def recommendations(self, include_completed: bool = False) -> pd.DataFrame:
        sql = "SELECT * FROM creator_recommendations"
        if not include_completed:
            sql += " WHERE completed=0"
        return self.db.frame(sql + " ORDER BY priority DESC,id DESC")

    def complete_recommendation(self, recommendation_id: int) -> None:
        self.db.execute(
            "UPDATE creator_recommendations SET completed=1,updated_at=? WHERE id=?",
            (datetime.now().isoformat(), int(recommendation_id)),
        )

    def learning_events(self, limit: int = 100) -> pd.DataFrame:
        return self.db.frame(
            "SELECT * FROM creator_learning_events ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )

    def patterns(self) -> pd.DataFrame:
        profile = self.creator_dna()
        rows = [
            {"pattern": "Preferred title style", "value": profile.get("preferred_title_style")},
            {"pattern": "Preferred caption style", "value": profile.get("preferred_caption_style")},
            {"pattern": "Top hashtags", "value": " ".join(profile.get("favorite_hashtags", [])) or "Not enough data"},
            {"pattern": "Average clip length", "value": f"{float(profile.get('average_clip_length') or 0):.1f} seconds"},
            {"pattern": "Packaging confidence", "value": f"{float(profile.get('packaging_confidence') or 0):.1f}%"},
        ]
        return pd.DataFrame(rows)

    def _clip_frame(self) -> pd.DataFrame:
        tables = self.db.frame("SELECT name FROM sqlite_master WHERE type='table'")
        if "transcript_clip_candidates" not in set(tables.get("name", [])):
            return pd.DataFrame()
        columns = set(self.db.frame("PRAGMA table_info(transcript_clip_candidates)").get("name", []))
        wanted = [
            "id", "title", "start_seconds", "end_seconds", "review_status",
            "hook_score", "humor_score", "surprise_score", "emotion_score",
            "quote_score", "viral_score", "retention_estimate", "suggested_title",
            "suggested_caption", "caption_style", "suggested_hashtags_json",
        ]
        selected = [name for name in wanted if name in columns]
        frame = self.db.frame(f"SELECT {','.join(selected)} FROM transcript_clip_candidates")
        if "production_clip_jobs" in set(tables.get("name", [])):
            sent = self.db.frame("SELECT clip_candidate_id,1 AS sent_to_production FROM production_clip_jobs")
            frame = frame.merge(sent, how="left", left_on="id", right_on="clip_candidate_id")
        if "sent_to_production" not in frame:
            frame["sent_to_production"] = 0
        return frame

    @staticmethod
    def classify_title(title: str) -> str:
        clean = title.strip()
        lowered = clean.lower()
        if "?" in clean or lowered.startswith(("what ", "why ", "how ", "did ", "can ")):
            return "Question"
        if re.search(r"\b\d+\b", clean):
            return "Number"
        if any(token in lowered for token in ("secret", "wait", "nobody", "almost", "unexpected", "coming")):
            return "Curiosity"
        if lowered.startswith(("i ", "my ", "we ")):
            return "Story"
        if any(token in lowered for token in ("challenge", "versus", "vs ", "without")):
            return "Challenge"
        return "Descriptive"

    @staticmethod
    def classify_caption(caption: str, stored_style: str = "") -> str:
        if stored_style:
            return stored_style
        lowered = caption.lower()
        if "?" in caption:
            return "Question"
        if any(token in lowered for token in ("comment", "follow", "subscribe", "tell me")):
            return "CTA"
        if any(token in caption for token in ("😂", "🤣")):
            return "Funny"
        return "Short" if len(caption) <= 120 else "Long"

    @staticmethod
    def _mean(frame: pd.DataFrame, column: str) -> float:
        if frame.empty or column not in frame:
            return 0.0
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        return round(float(values.mean()), 1) if len(values) else 0.0

    @staticmethod
    def _mean_duration(frame: pd.DataFrame) -> float:
        if frame.empty or not {"start_seconds", "end_seconds"}.issubset(frame.columns):
            return 0.0
        values = pd.to_numeric(frame["end_seconds"], errors="coerce") - pd.to_numeric(frame["start_seconds"], errors="coerce")
        values = values.dropna().clip(lower=0)
        return round(float(values.mean()), 1) if len(values) else 0.0

    @staticmethod
    def _status_count(frame: pd.DataFrame, status: str) -> int:
        if frame.empty or "review_status" not in frame:
            return 0
        return int((frame["review_status"] == status).sum())

    @staticmethod
    def _load_json(value, default):
        try:
            return json.loads(value or json.dumps(default))
        except Exception:
            return default

    @staticmethod
    def _rec(key, kind, priority, title, description, source_clip_id=None):
        return {
            "recommendation_key": key,
            "recommendation_type": kind,
            "priority": priority,
            "title": title,
            "description": description,
            "source_clip_id": source_clip_id,
        }
