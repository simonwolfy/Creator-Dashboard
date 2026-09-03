from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import UTC, datetime
from difflib import SequenceMatcher

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
            """CREATE TABLE IF NOT EXISTS package_provenance(
                id INTEGER PRIMARY KEY AUTOINCREMENT,package_id TEXT NOT NULL,
                source_type TEXT NOT NULL,source_id TEXT,payload_json TEXT NOT NULL DEFAULT '{}',
                confidence REAL,provider TEXT,model TEXT,intelligence_version TEXT NOT NULL,
                created_at TEXT NOT NULL,FOREIGN KEY(package_id) REFERENCES publishing_packages(id)
            )""",
            """CREATE TABLE IF NOT EXISTS platform_outcome_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,package_id TEXT NOT NULL,
                content_item_id TEXT,variant_id TEXT,platform TEXT NOT NULL,
                external_id TEXT NOT NULL,captured_at TEXT NOT NULL,milestone_hours INTEGER,
                views REAL,reach REAL,watch_time REAL,retention_rate REAL,ctr REAL,
                likes REAL,comments REAL,shares REAL,raw_payload_json TEXT NOT NULL,
                schema_version TEXT NOT NULL DEFAULT 'outcome-v1',
                UNIQUE(platform,external_id,captured_at),
                FOREIGN KEY(package_id) REFERENCES publishing_packages(id)
            )""",
            """CREATE TABLE IF NOT EXISTS intelligence_metric_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,
                package_id TEXT,clip_candidate_id INTEGER,duration_seconds REAL,
                value REAL,payload_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS intelligence_provider_usage(
                id INTEGER PRIMARY KEY AUTOINCREMENT,provider TEXT NOT NULL,model TEXT,
                operation TEXT NOT NULL,package_id TEXT,input_units REAL,output_units REAL,
                estimated_cost REAL,status TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL
            )""",
        ):
            self.db.execute(statement)
        self._ensure_package_columns()

    def _ensure_package_columns(self):
        existing = {str(row["name"]) for _, row in self.db.frame(
            "PRAGMA table_info(publishing_packages)"
        ).iterrows()}
        for name, sql_type in {
            "content_item_id": "TEXT", "intelligence_version": "TEXT",
            "review_started_at": "TEXT", "decision_at": "TEXT",
        }.items():
            if name not in existing:
                self.db.execute(f"ALTER TABLE publishing_packages ADD COLUMN {name} {sql_type}")

    def snapshot_packages(self, clip_id, packages, context=None, prediction=None, predicted_score=None):
        context = context or {}
        created = {}
        now = datetime.now(UTC).isoformat()
        for package_key, package in packages.items():
            platform = PLATFORM_KEYS.get(package_key, package_key)
            package_id = str(uuid.uuid4())
            self.db.execute(
                """INSERT INTO publishing_packages(
                   id,clip_candidate_id,platform,generated_title,generated_description,
                   generated_caption,generated_hook,generated_hashtags_json,
                   predicted_performance,predicted_score,clip_type,topic,package_json,created_at,
                   intelligence_version)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (package_id, int(clip_id), platform, package.get("title"),
                 package.get("description"), package.get("caption"), package.get("hook"),
                 json.dumps(package.get("hashtags") or []), prediction, predicted_score,
                 context.get("clip_type"), context.get("topic"),
                 json.dumps(package, default=str), now, "creator-packaging-v6"),
            )
            created[package_key] = package_id
            self.record_metric("package_generated", package_id=package_id,
                               clip_candidate_id=int(clip_id))
        return created

    def record_decision(self, package_id, status, used=None):
        if status not in {"Generated", "Approved", "Rejected", "Published"}:
            raise ValueError("Unsupported package decision status.")
        from creator_intelligence.services.creator_dna import CreatorDNAService
        dna = CreatorDNAService(self.db)
        dna.ensure_event_history()
        row = self.package(package_id)
        supplied = used or {}
        generated = {
            "title": row.get("generated_title"), "description": row.get("generated_description"),
            "caption": row.get("generated_caption"), "hook": row.get("generated_hook"),
            "hashtags": self._json(row.get("generated_hashtags_json"), []),
        }
        current = {
            "title": self._coalesce(row.get("used_title"), generated["title"]),
            "description": self._coalesce(row.get("used_description"), generated["description"]),
            "caption": self._coalesce(row.get("used_caption"), generated["caption"]),
            "hook": self._coalesce(row.get("used_hook"), generated["hook"]),
            "hashtags": self._json(row.get("used_hashtags_json"), generated["hashtags"])
            if self._present(row.get("used_hashtags_json")) else generated["hashtags"],
        }
        final = dict(current)
        for key in ("title", "description", "caption", "hook", "hashtags"):
            if key in supplied:
                final[key] = supplied[key]
        edit_status = "Edited" if any(
            final.get(key) != generated.get(key)
            for key in ("title", "description", "caption", "hook", "hashtags")
        ) else "Unchanged"
        now = datetime.now(UTC).isoformat()
        self.db.execute(
            """UPDATE publishing_packages SET decision_status=?,edit_status=?,
               used_title=?,used_description=?,used_caption=?,used_hook=?,used_hashtags_json=?,
               approved_at=CASE
                 WHEN ? IN ('Approved','Published') THEN COALESCE(approved_at,?)
                 WHEN ? IN ('Generated','Rejected') THEN NULL ELSE approved_at END
               ,decision_at=?
               WHERE id=?""",
            (status, edit_status, final["title"], final["description"],
             final["caption"], final["hook"], json.dumps(final["hashtags"]),
             status, now, status, now, package_id),
        )
        self.record_metric(
            "package_decision", package_id=package_id,
            clip_candidate_id=int(row["clip_candidate_id"]),
            value=1.0 if edit_status == "Edited" else 0.0,
            payload={"status": status, "edit_status": edit_status},
        )
        updated = self.package(package_id)
        metadata = {
            "copy": final,
            "generated_copy": generated,
            "clip": dna._clip_snapshot(int(row["clip_candidate_id"])),
            "decision_status": status,
        }
        for field in ("title", "description", "caption", "hook", "hashtags"):
            if current.get(field) == final.get(field):
                continue
            edit_event = (
                f"{field}_edited"
                if field in {"title", "caption"}
                else "package_field_edited"
            )
            dna.record_event(
                edit_event,
                clip_id=int(row["clip_candidate_id"]),
                package_id=str(package_id),
                subject_type="package",
                subject_id=str(package_id),
                platform=row.get("platform"),
                field_name=field,
                old_value=current.get(field),
                new_value=final.get(field),
                metadata=metadata,
                source="publishing_outcomes",
            )
        event_type = {
            "Approved": "package_approved",
            "Rejected": "package_rejected",
            "Published": "package_published",
        }.get(status)
        if (
            status == "Generated"
            and str(row.get("decision_status")) in {"Approved", "Published"}
        ):
            event_type = "package_approval_invalidated"
        if event_type and str(row.get("decision_status")) != status:
            dna.record_event(
                event_type,
                clip_id=int(row["clip_candidate_id"]),
                package_id=str(package_id),
                subject_type="package",
                subject_id=str(package_id),
                platform=row.get("platform"),
                field_name="decision",
                old_value=row.get("decision_status"),
                new_value=status,
                metadata=metadata,
                source="publishing_outcomes",
            )
        return updated

    def begin_review(self, package_id):
        row = self.package(package_id)
        if not row.get("review_started_at"):
            now = datetime.now(UTC).isoformat()
            self.db.execute("UPDATE publishing_packages SET review_started_at=? WHERE id=?", (now, package_id))
            self.record_metric("review_started", package_id=package_id,
                               clip_candidate_id=int(row["clip_candidate_id"]))
        return self.package(package_id)

    def ensure_content_link(self, package_id):
        package = self.package(package_id)
        if package.get("content_item_id"):
            return str(package["content_item_id"])
        from creator_intelligence.services.content_library import ContentLibraryService
        library = ContentLibraryService(self.db)
        title = package.get("used_title") or package.get("used_caption") or package.get("generated_title") or package.get("generated_caption") or "Untitled clip"
        content_id = library.create_item({
            "platform": package["platform"].title(), "content_type": "Short",
            "title": title, "game_topic": package.get("topic"), "status": "Needs review",
            "tags": ["content-intelligence", package.get("clip_type") or "clip"],
            "notes": json.dumps({"package_id": package_id,
                                  "clip_candidate_id": package["clip_candidate_id"]}),
        })
        self.db.execute("UPDATE publishing_packages SET content_item_id=? WHERE id=?", (content_id, package_id))
        return content_id

    def record_provenance(self, package_id, source_type, *, source_id=None, payload=None,
                          confidence=None, provider=None, model=None,
                          intelligence_version="creator-packaging-v6"):
        self.package(package_id)
        return int(self.db.execute(
            """INSERT INTO package_provenance(package_id,source_type,source_id,payload_json,
               confidence,provider,model,intelligence_version,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (package_id, source_type, source_id, json.dumps(payload or {}, default=str),
             confidence, provider, model, intelligence_version,
             datetime.now(UTC).isoformat()),
        ))

    def provenance(self, package_id):
        return self.db.frame(
            "SELECT * FROM package_provenance WHERE package_id=? ORDER BY id", (package_id,)
        )

    def record_normalized_outcome(self, package_id, external_id, metrics, *,
                                  captured_at=None, milestone_hours=None,
                                  variant_id=None, raw_payload=None):
        package = self.package(package_id)
        platform = str(package["platform"]).lower()
        if platform not in {"youtube", "twitch", "tiktok", "instagram"}:
            raise ValueError("Unsupported outcome platform.")
        content_id = self.ensure_content_link(package_id)
        captured = captured_at or datetime.now(UTC).isoformat()
        fields = ("views", "reach", "watch_time", "retention_rate", "ctr",
                  "likes", "comments", "shares")
        values = [None if metrics.get(name) in (None, "") else float(metrics[name]) for name in fields]
        row_id = int(self.db.execute(
            """INSERT INTO platform_outcome_snapshots(
               package_id,content_item_id,variant_id,platform,external_id,captured_at,
               milestone_hours,views,reach,watch_time,retention_rate,ctr,likes,comments,
               shares,raw_payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (package_id, content_id, variant_id, platform, str(external_id), captured,
             milestone_hours, *values, json.dumps(raw_payload or metrics, default=str)),
        ))
        self.record_metric("outcome_captured", package_id=package_id,
                           clip_candidate_id=int(package["clip_candidate_id"]),
                           payload={"platform": platform, "external_id": str(external_id)})
        return row_id

    def import_platform_outcomes(self, platform, records):
        """Import connector-neutral metrics while preserving unavailable values as null."""
        platform = str(platform).lower()
        if platform not in {"youtube", "twitch", "tiktok", "instagram"}:
            raise ValueError("Unsupported outcome platform.")
        imported, failed = [], {}
        metric_names = (
            "views", "reach", "watch_time", "retention_rate", "ctr",
            "likes", "comments", "shares",
        )
        for index, record in enumerate(records):
            try:
                package_id = str(record["package_id"])
                package = self.package(package_id)
                if str(package["platform"]).lower() != platform:
                    raise ValueError("Package platform does not match the imported platform.")
                external_id = record.get("external_id") or record.get("source_video_id")
                if not external_id:
                    raise ValueError("An external platform identifier is required.")
                metrics = record.get("metrics") or {
                    name: record.get(name) for name in metric_names
                }
                imported.append(self.record_normalized_outcome(
                    package_id, external_id, metrics,
                    captured_at=record.get("captured_at"),
                    milestone_hours=record.get("milestone_hours"),
                    variant_id=record.get("variant_id"), raw_payload=record,
                ))
            except Exception as exc:
                failed[str(index)] = str(exc)
        return {"imported": imported, "failed": failed}

    def record_provider_usage(self, provider, operation, *, model=None, package_id=None,
                              input_units=None, output_units=None, estimated_cost=None,
                              status="Completed", error=None):
        return int(self.db.execute(
            """INSERT INTO intelligence_provider_usage(provider,model,operation,package_id,
               input_units,output_units,estimated_cost,status,error,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (provider, model, operation, package_id, input_units, output_units,
             estimated_cost, status, error, datetime.now(UTC).isoformat()),
        ))

    def record_metric(self, event_type, *, package_id=None, clip_candidate_id=None,
                      duration_seconds=None, value=None, payload=None):
        return int(self.db.execute(
            """INSERT INTO intelligence_metric_events(event_type,package_id,clip_candidate_id,
               duration_seconds,value,payload_json,created_at) VALUES(?,?,?,?,?,?,?)""",
            (event_type, package_id, clip_candidate_id, duration_seconds, value,
             json.dumps(payload or {}, default=str), datetime.now(UTC).isoformat()),
        ))

    def quality_summary(self):
        packages = self.db.frame("SELECT * FROM publishing_packages")
        metrics = self.db.frame("SELECT * FROM intelligence_metric_events")
        usage = self.db.frame("SELECT * FROM intelligence_provider_usage")
        decisions = packages[packages["decision_status"].isin(["Approved", "Rejected", "Published"])] if not packages.empty else packages
        approved = decisions[decisions["decision_status"].isin(["Approved", "Published"])] if not decisions.empty else decisions
        processing = metrics[metrics["event_type"] == "analysis_completed"] if not metrics.empty else metrics
        review_seconds = []
        if not decisions.empty:
            for _, row in decisions.iterrows():
                started = self._dt(row.get("review_started_at"))
                finished = self._dt(row.get("decision_at"))
                if started and finished and finished >= started:
                    review_seconds.append((finished - started).total_seconds())
        outcomes = self.db.frame("SELECT * FROM platform_outcome_snapshots")
        return {
            "packages": len(packages), "decisions": len(decisions),
            "approval_rate": round(len(approved) / len(decisions), 3) if len(decisions) else None,
            "edit_rate": round(float((decisions["edit_status"] == "Edited").mean()), 3) if len(decisions) else None,
            "average_processing_seconds": round(float(processing["duration_seconds"].dropna().mean()), 2) if not processing.empty and not processing["duration_seconds"].dropna().empty else None,
            "average_review_seconds": round(sum(review_seconds) / len(review_seconds), 2) if review_seconds else None,
            "outcome_snapshots": len(outcomes),
            "failed_analyses": int((metrics["event_type"] == "analysis_failed").sum()) if not metrics.empty else 0,
            "estimated_provider_cost": round(float(usage["estimated_cost"].dropna().sum()), 4) if not usage.empty else 0.0,
        }

    def link(self, package_id, source_video_id, method="manual", confidence=1.0, manually_confirmed=True):
        from creator_intelligence.services.creator_dna import CreatorDNAService
        dna = CreatorDNAService(self.db)
        dna.ensure_event_history()
        package = self.package(package_id)
        source = self.db.frame(
            "SELECT * FROM creator_published_titles WHERE platform=? AND source_video_id=?",
            (package["platform"], str(source_video_id)),
        )
        if source.empty:
            raise ValueError("That published platform post has not been synced yet.")
        published_at = source.iloc[0].get("published_at")
        now = datetime.now(UTC).isoformat()
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
        updated = self.package(package_id)
        if str(package.get("decision_status")) != "Published":
            copy = dna._package_copy(dna._json_safe(updated))
            fingerprint = hashlib.sha256(
                f"{package_id}:{source_video_id}".encode()
            ).hexdigest()
            dna.record_event(
                "package_published",
                clip_id=int(package["clip_candidate_id"]),
                package_id=str(package_id),
                subject_type="package",
                subject_id=str(package_id),
                platform=package.get("platform"),
                field_name="decision",
                old_value=package.get("decision_status"),
                new_value="Published",
                metadata={
                    "copy": copy,
                    "clip": dna._clip_snapshot(int(package["clip_candidate_id"])),
                    "published_record": dna._json_safe(source.iloc[0].to_dict()),
                    "match_method": method,
                    "match_confidence": float(confidence),
                },
                source="publishing_outcomes",
                event_key=f"package-published:{fingerprint}",
            )
        return updated

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
        from creator_intelligence.services.creator_dna import CreatorDNAService
        dna = CreatorDNAService(self.db)
        dna.ensure_event_history()
        now = self._dt(now) if now else datetime.now(UTC)
        rows = self.db.frame(
            """SELECT p.id AS package_id,p.clip_candidate_id,
               p.platform AS package_platform,p.published_at AS package_published_at,t.*
               FROM publishing_packages p
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
                dna.record_event(
                    "package_outcome_observed",
                    clip_id=int(row["clip_candidate_id"]),
                    package_id=str(row["package_id"]),
                    subject_type="package_outcome",
                    subject_id=f"{row['package_id']}:{milestone}",
                    platform=row.get("package_platform"),
                    evidence_polarity="neutral",
                    evidence_weight=0,
                    field_name="performance",
                    new_value=score,
                    metadata={
                        "milestone_hours": milestone,
                        "age_hours": age,
                        "metrics": metrics,
                        "actual_score": score,
                    },
                    source="publishing_outcomes",
                    event_key=f"package-outcome:{row['package_id']}:{milestone}",
                )
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
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    @classmethod
    def _days_between(cls, left, right):
        a, b = cls._dt(left), cls._dt(right)
        return abs((b - a).total_seconds()) / 86400 if a and b else None

    @staticmethod
    def _present(value):
        if value is None:
            return False
        try:
            return not pd.isna(value)
        except (TypeError, ValueError):
            return True

    @classmethod
    def _coalesce(cls, value, fallback):
        return value if cls._present(value) else fallback

    @staticmethod
    def _json(value, default):
        try:
            return json.loads(value) if value else default
        except (TypeError, ValueError):
            return default
