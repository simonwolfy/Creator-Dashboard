from __future__ import annotations

import json
import math
import re
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import pandas as pd


class CreatorDNAService:
    """Build a local creator profile by replaying immutable feedback events."""

    PROFILE_VERSION = "creator-dna-v2"
    EVENT_SCHEMA_VERSION = "creator-feedback-v1"
    POLARITIES = {"positive", "negative", "neutral"}
    DECISION_EVENTS = {
        "approved": "Approved",
        "rejected": "Rejected",
        "clip_approved": "Approved",
        "clip_rejected": "Rejected",
        "clip_needs_work": "Needs work",
        "clip_review_reset": "Unreviewed",
        "package_approved": "Approved",
        "package_rejected": "Rejected",
        "package_published": "Published",
        "package_approval_invalidated": "Generated",
    }

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
                positive_examples INTEGER NOT NULL DEFAULT 0,
                negative_examples INTEGER NOT NULL DEFAULT 0,
                neutral_examples INTEGER NOT NULL DEFAULT 0,
                source_event_count INTEGER NOT NULL DEFAULT 0,
                source_event_id INTEGER NOT NULL DEFAULT 0,
                title_profile_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_learning_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT,
                clip_id INTEGER,
                package_id TEXT,
                subject_type TEXT NOT NULL DEFAULT 'clip',
                subject_id TEXT,
                platform TEXT,
                event_type TEXT NOT NULL,
                schema_version TEXT NOT NULL DEFAULT 'creator-feedback-v1',
                evidence_polarity TEXT NOT NULL DEFAULT 'neutral',
                evidence_weight REAL NOT NULL DEFAULT 0,
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                source TEXT NOT NULL DEFAULT 'application',
                created_at TEXT NOT NULL
            )"""
        )
        profile_columns = {
            str(row["name"])
            for _, row in self.db.frame("PRAGMA table_info(creator_profiles)").iterrows()
        }
        for name, definition in {
            "positive_examples": "INTEGER NOT NULL DEFAULT 0",
            "negative_examples": "INTEGER NOT NULL DEFAULT 0",
            "neutral_examples": "INTEGER NOT NULL DEFAULT 0",
            "source_event_count": "INTEGER NOT NULL DEFAULT 0",
            "source_event_id": "INTEGER NOT NULL DEFAULT 0",
            "title_profile_json": "TEXT NOT NULL DEFAULT '{}'",
        }.items():
            if name not in profile_columns:
                self.db.execute(f"ALTER TABLE creator_profiles ADD COLUMN {name} {definition}")
        event_columns = {
            str(row["name"])
            for _, row in self.db.frame(
                "PRAGMA table_info(creator_learning_events)"
            ).iterrows()
        }
        for name, definition in {
            "event_key": "TEXT",
            "package_id": "TEXT",
            "subject_type": "TEXT NOT NULL DEFAULT 'clip'",
            "subject_id": "TEXT",
            "platform": "TEXT",
            "schema_version": "TEXT NOT NULL DEFAULT 'creator-feedback-v1'",
            "evidence_polarity": "TEXT NOT NULL DEFAULT 'neutral'",
            "evidence_weight": "REAL NOT NULL DEFAULT 0",
            "field_name": "TEXT",
            "source": "TEXT NOT NULL DEFAULT 'application'",
        }.items():
            if name not in event_columns:
                self.db.execute(
                    f"ALTER TABLE creator_learning_events ADD COLUMN {name} {definition}"
                )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_dna_state(
                state_key TEXT PRIMARY KEY,
                state_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
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
        self.db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_creator_events_key
               ON creator_learning_events(event_key) WHERE event_key IS NOT NULL"""
        )
        self.db.execute(
            """CREATE INDEX IF NOT EXISTS idx_creator_events_evidence
               ON creator_learning_events(evidence_polarity,field_name,platform)"""
        )
        self.db.execute(
            """CREATE TRIGGER IF NOT EXISTS creator_learning_events_no_update
               BEFORE UPDATE ON creator_learning_events
               BEGIN
                 SELECT RAISE(ABORT,'Creator learning events are immutable');
               END"""
        )
        self.db.execute(
            """CREATE TRIGGER IF NOT EXISTS creator_learning_events_no_delete
               BEFORE DELETE ON creator_learning_events
               BEGIN
                 SELECT RAISE(ABORT,'Creator learning events are immutable');
               END"""
        )

    def record_event(
        self,
        event_type: str,
        *,
        clip_id: int | None = None,
        package_id: str | None = None,
        subject_type: str | None = None,
        subject_id: str | int | None = None,
        platform: str | None = None,
        evidence_polarity: str | None = None,
        evidence_weight: float | None = None,
        field_name: str | None = None,
        old_value: Any = None,
        new_value: Any = None,
        metadata: dict[str, Any] | None = None,
        source: str = "application",
        event_key: str | None = None,
        created_at: str | None = None,
    ) -> int:
        self._bootstrap_legacy_events()
        polarity, weight = self._default_evidence(
            event_type, evidence_polarity, evidence_weight
        )
        if polarity not in self.POLARITIES:
            raise ValueError("evidence_polarity must be positive, negative, or neutral.")
        inferred_subject = subject_type or (
            "package" if package_id else "clip" if clip_id is not None else "creator"
        )
        inferred_id = subject_id
        if inferred_id is None:
            inferred_id = package_id if package_id else clip_id
        return self._insert_event(
            event_type,
            clip_id=clip_id,
            package_id=package_id,
            subject_type=inferred_subject,
            subject_id=inferred_id,
            platform=platform,
            evidence_polarity=polarity,
            evidence_weight=weight,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            metadata=metadata,
            source=source,
            event_key=event_key or str(uuid.uuid4()),
            created_at=created_at,
        )

    def ensure_event_history(self) -> None:
        """Perform the one-time conversion of pre-ledger creator data."""
        self._bootstrap_legacy_events()

    def _insert_event(
        self,
        event_type: str,
        *,
        clip_id: int | None = None,
        package_id: str | None = None,
        subject_type: str = "creator",
        subject_id: str | int | None = None,
        platform: str | None = None,
        evidence_polarity: str = "neutral",
        evidence_weight: float = 0,
        field_name: str | None = None,
        old_value: Any = None,
        new_value: Any = None,
        metadata: dict[str, Any] | None = None,
        source: str = "application",
        event_key: str | None = None,
        created_at: str | None = None,
    ) -> int:
        key = event_key or str(uuid.uuid4())
        self.db.execute(
            """INSERT OR IGNORE INTO creator_learning_events(
                event_key,clip_id,package_id,subject_type,subject_id,platform,
                event_type,schema_version,evidence_polarity,evidence_weight,field_name,
                old_value,new_value,metadata_json,source,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                key,
                int(clip_id) if clip_id is not None else None,
                str(package_id) if package_id is not None else None,
                str(subject_type or "creator"),
                str(subject_id) if subject_id is not None else None,
                str(platform).lower() if platform else None,
                event_type,
                self.EVENT_SCHEMA_VERSION,
                evidence_polarity,
                max(0.0, float(evidence_weight or 0)),
                field_name,
                self._event_value(old_value),
                self._event_value(new_value),
                json.dumps(self._json_safe(metadata or {}), sort_keys=True),
                source,
                created_at or datetime.now(UTC).isoformat(),
            ),
        )
        row = self.db.frame(
            "SELECT id FROM creator_learning_events WHERE event_key=?", (key,)
        )
        return int(row.iloc[0]["id"])

    @classmethod
    def _default_evidence(cls, event_type, polarity, weight):
        defaults = {
            "approved": ("positive", 2.0),
            "clip_approved": ("positive", 2.0),
            "package_approved": ("positive", 2.0),
            "package_published": ("positive", 3.0),
            "production_handoff": ("positive", 2.5),
            "rejected": ("negative", 2.0),
            "clip_rejected": ("negative", 2.0),
            "package_rejected": ("negative", 2.0),
            "title_alternative_rejected": ("negative", 1.0),
            "clip_needs_work": ("neutral", 0.5),
            "clip_review_reset": ("neutral", 0.0),
            "package_field_edited": ("neutral", 1.0),
            "title_edited": ("neutral", 1.0),
            "caption_edited": ("neutral", 1.0),
            "package_approval_invalidated": ("neutral", 0.0),
            "title_alternative_selected": ("neutral", 0.5),
        }
        default_polarity, default_weight = defaults.get(event_type, ("neutral", 0.0))
        return polarity or default_polarity, default_weight if weight is None else weight

    def _bootstrap_legacy_events(self) -> None:
        marker = self.db.frame(
            "SELECT state_value FROM creator_dna_state WHERE state_key=?",
            (self.EVENT_SCHEMA_VERSION,),
        )
        if not marker.empty:
            return
        if self._table_exists("transcript_clip_candidates"):
            for _, row in self.db.frame("SELECT * FROM transcript_clip_candidates").iterrows():
                item = self._json_safe(row.to_dict())
                status = str(item.get("review_status") or "")
                event_type = {
                    "Approved": "clip_approved",
                    "Rejected": "clip_rejected",
                    "Needs work": "clip_needs_work",
                }.get(status)
                if event_type:
                    polarity, weight = self._default_evidence(event_type, None, None)
                    self._insert_event(
                        event_type,
                        clip_id=int(item["id"]),
                        subject_type="clip",
                        subject_id=item["id"],
                        evidence_polarity=polarity,
                        evidence_weight=weight,
                        field_name="decision",
                        old_value="Unreviewed",
                        new_value=status,
                        metadata={"clip": item},
                        source="legacy_migration",
                        event_key=f"legacy:clip:{item['id']}:{status.lower()}",
                    )
        if self._table_exists("creator_published_titles"):
            rows = self.db.frame("SELECT * FROM creator_published_titles")
            for _, row in rows.iterrows():
                item = self._json_safe(row.to_dict())
                polarity, weight = self.historical_title_evidence(item)
                self._insert_event(
                    "historical_title_recorded",
                    subject_type="published_title",
                    subject_id=item["id"],
                    platform=item.get("platform"),
                    evidence_polarity=polarity,
                    evidence_weight=weight,
                    field_name="title",
                    new_value=item.get("title"),
                    metadata={"record": item},
                    source="legacy_migration",
                    event_key=f"legacy:title:{item['id']}",
                )
        if self._table_exists("publishing_packages"):
            for _, row in self.db.frame("SELECT * FROM publishing_packages").iterrows():
                item = self._json_safe(row.to_dict())
                package_id = str(item["id"])
                copy = self._package_copy(item)
                clip_snapshot = self._clip_snapshot(int(item["clip_candidate_id"]))
                if str(item.get("edit_status")) == "Edited":
                    generated = self._package_copy(item, generated=True)
                    for field in ("title", "description", "caption", "hook", "hashtags"):
                        if generated.get(field) != copy.get(field):
                            edit_event = (
                                f"{field}_edited"
                                if field in {"title", "caption"}
                                else "package_field_edited"
                            )
                            self._insert_event(
                                edit_event,
                                clip_id=int(item["clip_candidate_id"]),
                                package_id=package_id,
                                subject_type="package",
                                subject_id=package_id,
                                platform=item.get("platform"),
                                evidence_polarity="neutral",
                                evidence_weight=1.0,
                                field_name=field,
                                old_value=generated.get(field),
                                new_value=copy.get(field),
                                metadata={"copy": copy, "clip": clip_snapshot},
                                source="legacy_migration",
                                event_key=f"legacy:package-edit:{package_id}:{field}",
                            )
                status = str(item.get("decision_status") or "")
                event_type = {
                    "Approved": "package_approved",
                    "Rejected": "package_rejected",
                    "Published": "package_published",
                }.get(status)
                if event_type:
                    polarity, weight = self._default_evidence(event_type, None, None)
                    self._insert_event(
                        event_type,
                        clip_id=int(item["clip_candidate_id"]),
                        package_id=package_id,
                        subject_type="package",
                        subject_id=package_id,
                        platform=item.get("platform"),
                        evidence_polarity=polarity,
                        evidence_weight=weight,
                        field_name="decision",
                        old_value="Generated",
                        new_value=status,
                        metadata={"copy": copy, "clip": clip_snapshot},
                        source="legacy_migration",
                        event_key=f"legacy:package:{package_id}:{status.lower()}",
                    )
        if self._table_exists("production_clip_jobs"):
            for _, row in self.db.frame("SELECT * FROM production_clip_jobs").iterrows():
                item = self._json_safe(row.to_dict())
                self._insert_event(
                    "production_handoff",
                    clip_id=int(item["clip_candidate_id"]),
                    subject_type="production_job",
                    subject_id=item["id"],
                    evidence_polarity="positive",
                    evidence_weight=2.5,
                    field_name="title",
                    new_value=item.get("title"),
                    metadata={"copy": {"title": item.get("title")}, "job": item},
                    source="legacy_migration",
                    event_key=f"legacy:production-job:{item['id']}",
                )
        now = datetime.now(UTC).isoformat()
        self.db.execute(
            """INSERT OR IGNORE INTO creator_dna_state(state_key,state_value,updated_at)
               VALUES(?,?,?)""",
            (self.EVENT_SCHEMA_VERSION, "completed", now),
        )

    def rebuild_profile(self) -> dict[str, Any]:
        self._bootstrap_legacy_events()
        events = self._effective_events()
        clip_statuses = self._clip_statuses(events)
        approved_ids = {
            clip_id for clip_id, statuses in clip_statuses.items()
            if statuses & {"Approved", "Published"}
        }
        rejected_ids = {
            clip_id for clip_id, statuses in clip_statuses.items()
            if not statuses & {"Approved", "Published"} and "Rejected" in statuses
        }
        needs_work_ids = {
            clip_id for clip_id, statuses in clip_statuses.items()
            if not statuses & {"Approved", "Published", "Rejected"}
            and "Needs work" in statuses
        }
        snapshots = self._positive_clip_snapshots(events)
        source = pd.DataFrame(list(snapshots.values()))
        title_profile = self._style_profile(events, "title")
        title_styles = Counter()
        for example in self._evidence_examples(events, "title"):
            if example["polarity"] == "positive":
                title_styles[self.classify_title(example["text"])] += example["weight"]
        caption_styles = Counter()
        for example in self._evidence_examples(events, "caption"):
            if example["polarity"] == "positive":
                caption_styles[self.classify_caption(
                    example["text"], example.get("stored_style", "")
                )] += example["weight"]
        hashtags = Counter()
        for _, event in events.iterrows():
            if self._event_polarity(event) != "positive":
                continue
            metadata = self._load_json(event.get("metadata_json"), {})
            copy = metadata.get("copy") or metadata.get("clip") or {}
            tags = copy.get("hashtags") or self._load_json(
                copy.get("suggested_hashtags_json"), []
            )
            for tag in tags or []:
                hashtags[str(tag)] += float(event.get("evidence_weight") or 1)
        polarity_counts = Counter(
            self._event_polarity(row) for _, row in events.iterrows()
        )
        event_count = int(len(events))
        source_event_id = int(events["id"].max()) if not events.empty else 0
        confidence = min(
            100.0,
            len(approved_ids) * 12.5
            + max(0, polarity_counts["positive"] - len(approved_ids)) * 2.0
            + polarity_counts["neutral"] * 0.5,
        )
        now = datetime.now(UTC).isoformat()
        profile = {
            "profile_version": self.PROFILE_VERSION,
            "approved_clips": len(approved_ids),
            "rejected_clips": len(rejected_ids),
            "needs_work_clips": len(needs_work_ids),
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
            "positive_examples": int(polarity_counts["positive"]),
            "negative_examples": int(polarity_counts["negative"]),
            "neutral_examples": int(polarity_counts["neutral"]),
            "source_event_count": event_count,
            "source_event_id": source_event_id,
            "title_profile": title_profile,
            "updated_at": now,
        }
        self.db.execute(
            """INSERT INTO creator_profiles(
                id,profile_version,approved_clips,rejected_clips,needs_work_clips,
                average_clip_length,average_hook,average_humor,average_surprise,
                average_emotion,average_quote,average_viral,average_retention,
                preferred_title_style,preferred_caption_style,favorite_hashtags_json,
                packaging_confidence,positive_examples,negative_examples,
                neutral_examples,source_event_count,source_event_id,title_profile_json,
                updated_at
            ) VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                positive_examples=excluded.positive_examples,
                negative_examples=excluded.negative_examples,
                neutral_examples=excluded.neutral_examples,
                source_event_count=excluded.source_event_count,
                source_event_id=excluded.source_event_id,
                title_profile_json=excluded.title_profile_json,
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
                profile["packaging_confidence"], profile["positive_examples"],
                profile["negative_examples"], profile["neutral_examples"],
                profile["source_event_count"], profile["source_event_id"],
                json.dumps(profile["title_profile"]), now,
            ),
        )
        self.generate_recommendations(self._clip_frame())
        return profile

    def creator_dna(self, rebuild: bool = False) -> dict[str, Any]:
        self._bootstrap_legacy_events()
        event_state = self.db.frame(
            "SELECT COUNT(*) AS count,COALESCE(MAX(id),0) AS max_id FROM creator_learning_events"
        ).iloc[0]
        frame = self.db.frame("SELECT * FROM creator_profiles WHERE id=1")
        stale = (
            frame.empty
            or str(frame.iloc[0].get("profile_version")) != self.PROFILE_VERSION
            or int(frame.iloc[0].get("source_event_id") or 0) != int(event_state["max_id"])
        )
        if rebuild or stale:
            return self.rebuild_profile()
        row = frame.iloc[0].to_dict()
        row["favorite_hashtags"] = self._load_json(
            row.pop("favorite_hashtags_json", "[]"), []
        )
        row["title_profile"] = self._load_json(
            row.pop("title_profile_json", "{}"), {}
        )
        return row

    def title_style_profile(self) -> dict[str, Any]:
        self._bootstrap_legacy_events()
        return self._style_profile(self._effective_events(), "title")

    @classmethod
    def historical_title_evidence(cls, record: dict[str, Any]):
        kind = str(record.get("example_type") or "published").lower()
        if kind == "rejected":
            return "negative", 2.5
        weight = 1.5 if kind == "approved" else 3.0
        if kind == "published":
            views = float(record.get("views") or 0)
            interactions = float(record.get("likes") or 0) + float(
                record.get("comments") or 0
            )
            performance = min(2.0, math.log10(views + 1) / 3.0)
            if views:
                performance += min(1.0, interactions / views * 10.0)
            weight *= 1.0 + performance
        return "positive", round(weight, 4)

    def _effective_events(self) -> pd.DataFrame:
        frame = self.db.frame("SELECT * FROM creator_learning_events ORDER BY id")
        if frame.empty:
            return frame
        keep: set[int] = set()
        latest: dict[tuple[str, str], int] = {}
        for index, row in frame.iterrows():
            event_type = str(row.get("event_type") or "")
            subject = str(
                row.get("package_id")
                or row.get("subject_id")
                or row.get("clip_id")
                or row.get("id")
            )
            if event_type.startswith("historical_title_"):
                latest[("historical_title", subject)] = index
            elif event_type in self.DECISION_EVENTS:
                latest[("decision", subject)] = index
            else:
                keep.add(index)
        keep.update(latest.values())
        return frame.loc[sorted(keep)].reset_index(drop=True)

    def _clip_statuses(self, events: pd.DataFrame) -> dict[int, set[str]]:
        statuses: dict[int, set[str]] = {}
        for _, row in events.iterrows():
            clip_id = row.get("clip_id")
            if clip_id is None or pd.isna(clip_id):
                continue
            event_type = str(row.get("event_type") or "")
            status = self.DECISION_EVENTS.get(event_type)
            if event_type == "production_handoff":
                status = "Published"
            if status:
                statuses.setdefault(int(clip_id), set()).add(status)
        return statuses

    def _positive_clip_snapshots(self, events: pd.DataFrame) -> dict[int, dict[str, Any]]:
        snapshots: dict[int, dict[str, Any]] = {}
        for _, row in events.iterrows():
            clip_id = row.get("clip_id")
            if clip_id is None or pd.isna(clip_id):
                continue
            if self._event_polarity(row) != "positive":
                continue
            metadata = self._load_json(row.get("metadata_json"), {})
            snapshot = metadata.get("clip") or metadata.get("clip_snapshot")
            if isinstance(snapshot, dict) and snapshot:
                snapshots[int(clip_id)] = self._json_safe(snapshot)
        return snapshots

    def _evidence_examples(
        self, events: pd.DataFrame, field_name: str
    ) -> list[dict[str, Any]]:
        examples: list[dict[str, Any]] = []
        for _, row in events.iterrows():
            event_type = str(row.get("event_type") or "")
            event_field = str(row.get("field_name") or "")
            weight = self._event_weight(row)
            metadata = self._load_json(row.get("metadata_json"), {})
            if (
                event_type in {"package_field_edited", "title_edited", "caption_edited"}
                and event_field == field_name
            ):
                old_value = str(row.get("old_value") or "").strip()
                new_value = str(row.get("new_value") or "").strip()
                if old_value and old_value != new_value:
                    examples.append({
                        "text": old_value,
                        "polarity": "negative",
                        "weight": max(0.5, weight * 0.75),
                        "event_id": int(row["id"]),
                        "stored_style": "",
                    })
                if new_value:
                    examples.append({
                        "text": new_value,
                        "polarity": "positive",
                        "weight": max(1.0, weight * 1.25),
                        "event_id": int(row["id"]),
                        "stored_style": "",
                    })
                continue
            direct_value = ""
            if event_field == field_name:
                direct_value = str(row.get("new_value") or "").strip()
            if direct_value:
                examples.append({
                    "text": direct_value,
                    "polarity": self._event_polarity(row),
                    "weight": weight,
                    "event_id": int(row["id"]),
                    "stored_style": "",
                })
                continue
            copy = metadata.get("copy") or metadata.get("record") or metadata.get("clip") or {}
            if not isinstance(copy, dict):
                continue
            if field_name == "title":
                value = copy.get("title") or copy.get("suggested_title")
            else:
                value = copy.get("caption") or copy.get("suggested_caption")
            text = str(value or "").strip()
            if text:
                examples.append({
                    "text": text,
                    "polarity": self._event_polarity(row),
                    "weight": weight,
                    "event_id": int(row["id"]),
                    "stored_style": str(copy.get("caption_style") or ""),
                })
        return examples

    def _style_profile(self, events: pd.DataFrame, field_name: str) -> dict[str, Any]:
        examples = self._evidence_examples(events, field_name)
        positives = [item for item in examples if item["polarity"] == "positive"]
        negatives = [item for item in examples if item["polarity"] == "negative"]
        neutrals = [item for item in examples if item["polarity"] == "neutral"]
        total = sum(float(item["weight"]) for item in positives) or 1.0

        def average(fn):
            return sum(
                fn(item["text"]) * float(item["weight"]) for item in positives
            ) / total

        token_scores: dict[str, float] = {}
        for item in positives + negatives:
            direction = 1.0 if item["polarity"] == "positive" else -1.0
            for token in set(re.findall(r"[a-z0-9']+", item["text"].lower())):
                token_scores[token] = token_scores.get(token, 0.0) + (
                    direction * float(item["weight"])
                )
        preferred = [
            token for token, score in sorted(
                token_scores.items(), key=lambda item: (-item[1], item[0])
            ) if score > 0
        ][:12]
        avoided = [
            token for token, score in sorted(
                token_scores.items(), key=lambda item: (item[1], item[0])
            ) if score < 0
        ][:12]
        return {
            "example_count": len(examples),
            "positive_count": len(positives),
            "negative_count": len(negatives),
            "neutral_count": len(neutrals),
            "average_words": round(average(lambda text: len(text.split())), 1),
            "question_rate": round(average(lambda text: text.rstrip().endswith("?")), 2),
            "first_person_rate": round(average(
                lambda text: bool(re.search(r"\b(i|we|my|our)\b", text, re.I))
            ), 2),
            "exclamation_rate": round(average(lambda text: "!" in text), 2),
            "preferred_words": preferred,
            "avoided_words": avoided,
            "source_event_count": int(len(events)),
        }

    def _event_polarity(self, row) -> str:
        polarity = str(row.get("evidence_polarity") or "neutral")
        if polarity == "neutral" and str(row.get("event_type")) in self.DECISION_EVENTS:
            polarity, _ = self._default_evidence(
                str(row.get("event_type")), None, None
            )
        return polarity if polarity in self.POLARITIES else "neutral"

    def _event_weight(self, row) -> float:
        value = float(row.get("evidence_weight") or 0)
        if value:
            return value
        _, fallback = self._default_evidence(str(row.get("event_type") or ""), None, None)
        return float(fallback)

    def _clip_snapshot(self, clip_id: int) -> dict[str, Any]:
        if not self._table_exists("transcript_clip_candidates"):
            return {}
        frame = self.db.frame(
            "SELECT * FROM transcript_clip_candidates WHERE id=?", (int(clip_id),)
        )
        return self._json_safe(frame.iloc[0].to_dict()) if not frame.empty else {}

    @classmethod
    def _package_copy(cls, row: dict[str, Any], generated: bool = False):
        prefix = "generated" if generated else "used"
        result = {}
        for field in ("title", "description", "caption", "hook"):
            value = row.get(f"{prefix}_{field}")
            if value is None and not generated:
                value = row.get(f"generated_{field}")
            result[field] = value
        hashtags = row.get(f"{prefix}_hashtags_json")
        if hashtags is None and not generated:
            hashtags = row.get("generated_hashtags_json")
        result["hashtags"] = cls._load_json(hashtags, [])
        return result

    def _table_exists(self, name: str) -> bool:
        return not self.db.frame(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).empty

    @classmethod
    def _event_value(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(cls._json_safe(value), sort_keys=True)

    @classmethod
    def _json_safe(cls, value: Any):
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            if isinstance(value, float) and math.isnan(value):
                return None
            return value
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        if hasattr(value, "item"):
            try:
                return value.item()
            except Exception:
                pass
        return str(value)

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
        self._bootstrap_legacy_events()
        return self.db.frame(
            """SELECT id,created_at,event_type,schema_version,evidence_polarity,evidence_weight,
               field_name,platform,clip_id,package_id,old_value,new_value,source,
               metadata_json,event_key,subject_type,subject_id
               FROM creator_learning_events ORDER BY id DESC LIMIT ?""",
            (int(limit),),
        )

    def patterns(self) -> pd.DataFrame:
        profile = self.creator_dna()
        title_profile = profile.get("title_profile") or {}
        rows = [
            {"pattern": "Preferred title style", "value": profile.get("preferred_title_style")},
            {"pattern": "Preferred caption style", "value": profile.get("preferred_caption_style")},
            {"pattern": "Preferred title words", "value": ", ".join(title_profile.get("preferred_words", [])) or "Not enough data"},
            {"pattern": "Avoided title words", "value": ", ".join(title_profile.get("avoided_words", [])) or "None learned"},
            {"pattern": "Top hashtags", "value": " ".join(profile.get("favorite_hashtags", [])) or "Not enough data"},
            {"pattern": "Average clip length", "value": f"{float(profile.get('average_clip_length') or 0):.1f} seconds"},
            {"pattern": "Packaging confidence", "value": f"{float(profile.get('packaging_confidence') or 0):.1f}%"},
            {"pattern": "Positive evidence", "value": str(int(profile.get("positive_examples") or 0))},
            {"pattern": "Negative evidence", "value": str(int(profile.get("negative_examples") or 0))},
            {"pattern": "Neutral evidence", "value": str(int(profile.get("neutral_examples") or 0))},
            {"pattern": "Immutable source events", "value": str(int(profile.get("source_event_count") or 0))},
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
