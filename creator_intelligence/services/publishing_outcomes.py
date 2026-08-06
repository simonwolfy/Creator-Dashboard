from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import math
import re
import uuid

import pandas as pd


PLATFORM_KEYS = {
    "youtube_shorts": "youtube", "youtube": "youtube",
    "instagram_reels": "instagram", "instagram": "instagram",
    "tiktok": "tiktok", "twitch": "twitch",
}
MILESTONES = (1, 24, 168, 720)


class PublishingOutcomeService:
    """Connect generated packages to real posts without overwriting the original copy."""

    def __init__(self, db):
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self):
        for statement in (
            """CREATE TABLE IF NOT EXISTS publishing_packages(
                id TEXT PRIMARY KEY, clip_candidate_id INTEGER NOT NULL,
                platform TEXT NOT NULL, generated_title TEXT,
                generated_description TEXT, generated_caption TEXT,
                generated_hook TEXT, generated_hashtags_json TEXT,
                used_title TEXT, used_description TEXT, used_caption TEXT,
                used_hook TEXT, used_hashtags_json TEXT,
                decision_status TEXT NOT NULL DEFAULT 'Generated',
                edit_status TEXT NOT NULL DEFAULT 'Unchanged',
                predicted_performance TEXT, predicted_score REAL,
                clip_type TEXT, topic TEXT, package_json TEXT NOT NULL,
                created_at TEXT NOT NULL, approved_at TEXT, published_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS publishing_outcome_links(
                id INTEGER PRIMARY KEY AUTOINCREMENT, package_id TEXT NOT NULL UNIQUE,
                platform TEXT NOT NULL, source_video_id TEXT NOT NULL,
                match_method TEXT NOT NULL, match_confidence REAL NOT NULL,
                manually_confirmed INTEGER NOT NULL DEFAULT 0, linked_at TEXT NOT NULL,
                UNIQUE(platform,source_video_id),
                FOREIGN KEY(package_id) REFERENCES publishing_packages(id)
            )""",
            """CREATE TABLE IF NOT EXISTS publishing_performance_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT, package_id TEXT NOT NULL,
                milestone_hours INTEGER NOT NULL, captured_at TEXT NOT NULL,
                age_hours REAL NOT NULL, views REAL DEFAULT 0, likes REAL DEFAULT 0,
                comments REAL DEFAULT 0, shares REAL DEFAULT 0, reach REAL DEFAULT 0,
                watch_time REAL DEFAULT 0, actual_score REAL DEFAULT 0,
                UNIQUE(package_id,milestone_hours),
                FOREIGN KEY(package_id) REFERENCES publishing_packages(id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_outcome_packages ON publishing_packages(platform,decision_status,created_at)",
            "CREATE INDEX IF NOT EXISTS idx_outcome_snapshots ON publishing_performance_snapshots(package_id,milestone_hours)",
        ):
            self.db.execute(statement)

    def snapshot_packages(self, clip_id, packages, context=None, prediction=None, predicted_score=None):
        context = context or {}
        created = {}
        now = datetime.now(timezone.utc).isoformat()
        for package_key, package in packages.items():
            platform = PLATFORM_KEYS.get(package_key, package_key)
            package_id = str(uuid.uuid4())
            self.db.execute(
                """INSERT INTO publishing_packages(
                   id,clip_candidate_id,platform,generated_title,generated_description,
                   generated_caption,generated_hook,generated_hashtags_json,
                   predicted_performance,predicted_score,clip_type,topic,package_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (package_id, int(clip_id), platform, package.get("title"),
                 package.get("description"), package.get("caption"), package.get("hook"),
                 json.dumps(package.get("hashtags") or []), prediction, predicted_score,
                 context.get("clip_type"), context.get("topic"),
                 json.dumps(package, default=str), now),
            )
            created[package_key] = package_id
        return created

    def record_decision(self, package_id, status, used=None):
        if status not in {"Generated", "Approved", "Rejected", "Published"}:
            raise ValueError("Unsupported package decision status.")
        row = self.package(package_id)
        used = used or {}
        generated = {
            "title": row.get("generated_title"), "description": row.get("generated_description"),
            "caption": row.get("generated_caption"), "hook": row.get("generated_hook"),
            "hashtags": self._json(row.get("generated_hashtags_json"), []),
        }
        edit_status = "Edited" if any(
            key in used and used.get(key) != generated.get(key)
            for key in ("title", "description", "caption", "hook", "hashtags")
        ) else "Unchanged"
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """UPDATE publishing_packages SET decision_status=?,edit_status=?,
               used_title=?,used_description=?,used_caption=?,used_hook=?,used_hashtags_json=?,
               approved_at=CASE WHEN ? IN ('Approved','Published') THEN COALESCE(approved_at,?) ELSE approved_at END
               WHERE id=?""",
            (status, edit_status, used.get("title", generated["title"]),
             used.get("description", generated["description"]),
             used.get("caption", generated["caption"]), used.get("hook", generated["hook"]),
             json.dumps(used.get("hashtags", generated["hashtags"])), status, now, package_id),
        )
        return self.package(package_id)

    def link(self, package_id, source_video_id, method="manual", confidence=1.0, manually_confirmed=True):
        package = self.package(package_id)
        source = self.db.frame(
            "SELECT * FROM creator_published_titles WHERE platform=? AND source_video_id=?",
            (package["platform"], str(source_video_id)),
        )
        if source.empty:
            raise ValueError("That published platform post has not been synced yet.")
        published_at = source.iloc[0].get("published_at")
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """INSERT OR REPLACE INTO publishing_outcome_links(
               package_id,platform,source_video_id,match_method,match_confidence,
               manually_confirmed,linked_at) VALUES(?,?,?,?,?,?,?)""",
            (package_id, package["platform"], str(source_video_id), method,
             float(confidence), int(manually_confirmed), now),
        )
        self.db.execute(
            "UPDATE publishing_packages SET decision_status='Published',published_at=? WHERE id=?",
            (published_at or now, package_id),
        )
        return self.package(package_id)

    def auto_match(self, platform=None):
        clauses, params = ["l.package_id IS NULL", "p.decision_status<>'Rejected'"], []
        if platform:
            clauses.append("p.platform=?"); params.append(PLATFORM_KEYS.get(platform, platform))
        packages = self.db.frame(
            """SELECT p.* FROM publishing_packages p LEFT JOIN publishing_outcome_links l
               ON l.package_id=p.id WHERE """ + " AND ".join(clauses), params)
        posts = self.db.frame("SELECT * FROM creator_published_titles WHERE example_type='published'")
        matched = []
        for _, package in packages.iterrows():
            candidates = posts[posts["platform"] == package["platform"]]
            best = None
            package_text = package.get("used_title") or package.get("used_caption") or package.get("generated_title") or package.get("generated_caption") or ""
            for _, post in candidates.iterrows():
                title_score = self._similarity(package_text, post.get("title") or "")
                days = self._days_between(package.get("created_at"), post.get("published_at"))
                if days is None or days > 30:
                    continue
                score = title_score * .82 + max(0, 1 - days / 30) * .18
                if title_score >= .65 and score >= .72 and (best is None or score > best[0]):
                    best = (score, post)
            if best:
                self.link(package["id"], best[1]["source_video_id"], "title_and_time", best[0], False)
                matched.append(package["id"])
        return matched

    def capture_due_snapshots(self, now=None):
        now = self._dt(now) if now else datetime.now(timezone.utc)
        rows = self.db.frame(
            """SELECT p.id AS package_id,p.published_at AS package_published_at,t.* FROM publishing_packages p
               JOIN publishing_outcome_links l ON l.package_id=p.id
               JOIN creator_published_titles t ON t.platform=l.platform AND t.source_video_id=l.source_video_id""")
        captured = []
        for _, row in rows.iterrows():
            published = self._dt(row.get("package_published_at"))
            if not published:
                continue
            age = max(0.0, (now - published).total_seconds() / 3600)
            for milestone in MILESTONES:
                if age < milestone:
                    continue
                exists = self.db.frame(
                    "SELECT id FROM publishing_performance_snapshots WHERE package_id=? AND milestone_hours=?",
                    (row["package_id"], milestone))
                if not exists.empty:
                    continue
                metrics = {key: float(row.get(key) or 0) for key in ("views", "likes", "comments", "shares", "reach", "watch_time")}
                score = self._actual_score(metrics)
                self.db.execute(
                    """INSERT INTO publishing_performance_snapshots(
                       package_id,milestone_hours,captured_at,age_hours,views,likes,comments,
                       shares,reach,watch_time,actual_score) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (row["package_id"], milestone, now.isoformat(), age, metrics["views"], metrics["likes"],
                     metrics["comments"], metrics["shares"], metrics["reach"], metrics["watch_time"], score))
                captured.append((row["package_id"], milestone))
        return captured

    def process_sync(self, platform=None):
        matched = self.auto_match(platform)
        snapshots = self.capture_due_snapshots()
        return {"matched": len(matched), "snapshots": len(snapshots)}

    def learning_adjustments(self, platform):
        frame = self.db.frame(
            """SELECT p.*,l.match_confidence,s.actual_score,s.milestone_hours
               FROM publishing_packages p JOIN publishing_outcome_links l ON l.package_id=p.id
               JOIN publishing_performance_snapshots s ON s.package_id=p.id
               WHERE p.platform=? AND p.decision_status='Published'
               AND s.milestone_hours=(SELECT MAX(x.milestone_hours) FROM publishing_performance_snapshots x WHERE x.package_id=p.id)""",
            (PLATFORM_KEYS.get(platform, platform),))
        weights = {}
        for _, row in frame.iterrows():
            text = row.get("used_title") or row.get("used_caption") or row.get("generated_title") or row.get("generated_caption") or ""
            attribution = float(row.get("match_confidence") or 0) * (.35 if row.get("edit_status") == "Edited" else .6)
            maturity = min(1.0, float(row.get("milestone_hours") or 0) / 168)
            weight = float(row.get("actual_score") or 0) / 100 * attribution * maturity
            for token in set(re.findall(r"[a-z0-9']+", str(text).lower())):
                weights[token] = weights.get(token, 0.0) + weight
        return weights

    def dashboard(self):
        return self.db.frame(
            """SELECT p.id,p.created_at,p.platform,p.clip_candidate_id,p.decision_status,
               p.edit_status,COALESCE(p.used_title,p.used_caption,p.generated_title,p.generated_caption) AS published_copy,
               p.predicted_performance,l.source_video_id,l.match_method,l.match_confidence,
               s.milestone_hours,s.views,s.likes,s.comments,s.shares,s.actual_score
               FROM publishing_packages p LEFT JOIN publishing_outcome_links l ON l.package_id=p.id
               LEFT JOIN publishing_performance_snapshots s ON s.package_id=p.id
                 AND s.milestone_hours=(SELECT MAX(x.milestone_hours) FROM publishing_performance_snapshots x WHERE x.package_id=p.id)
               ORDER BY p.created_at DESC""")

    def summary(self):
        frame = self.dashboard()
        return {"total": len(frame),
                "pending": int(frame["source_video_id"].isna().sum()) if not frame.empty else 0,
                "matched": int(frame["source_video_id"].notna().sum()) if not frame.empty else 0,
                "measured": int(frame["milestone_hours"].notna().sum()) if not frame.empty else 0}

    def package(self, package_id):
        frame = self.db.frame("SELECT * FROM publishing_packages WHERE id=?", (str(package_id),))
        if frame.empty:
            raise KeyError(package_id)
        return frame.iloc[0].to_dict()

    @staticmethod
    def _actual_score(metrics):
        views = metrics["views"]
        engagements = metrics["likes"] + metrics["comments"] * 2 + metrics["shares"] * 3
        rate = engagements / max(views, 1)
        return round(min(100.0, math.log10(max(views, 1)) * 13 + min(rate, .25) * 160), 2)

    @staticmethod
    def _similarity(left, right):
        clean = lambda value: " ".join(re.findall(r"[a-z0-9']+", str(value).lower()))
        return SequenceMatcher(None, clean(left), clean(right)).ratio()

    @staticmethod
    def _dt(value):
        if not value or str(value) == "nan":
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

    @classmethod
    def _days_between(cls, left, right):
        a, b = cls._dt(left), cls._dt(right)
        return abs((b - a).total_seconds()) / 86400 if a and b else None

    @staticmethod
    def _json(value, default):
        try:
            return json.loads(value) if value else default
        except (TypeError, ValueError):
            return default
