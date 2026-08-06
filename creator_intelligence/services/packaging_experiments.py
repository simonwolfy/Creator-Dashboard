from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import math
import re
import uuid


class PackagingExperimentService:
    """Conservative, platform-specific packaging variant experiments."""

    def __init__(self, db, outcomes=None):
        self.db = db
        if outcomes is None:
            from creator_intelligence.services.publishing_outcomes import PublishingOutcomeService
            outcomes = PublishingOutcomeService(db)
        self.outcomes = outcomes
        self._ensure_schema()

    def _ensure_schema(self):
        for statement in (
            """CREATE TABLE IF NOT EXISTS packaging_experiments(
                id TEXT PRIMARY KEY, package_id TEXT NOT NULL UNIQUE,
                clip_candidate_id INTEGER NOT NULL, platform TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Draft', strategy TEXT NOT NULL,
                recommended_variant_id TEXT, recommendation_confidence TEXT,
                recommendation_reason TEXT, winner_variant_id TEXT,
                result_confidence TEXT, result_reason TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(package_id) REFERENCES publishing_packages(id)
            )""",
            """CREATE TABLE IF NOT EXISTS packaging_experiment_variants(
                id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
                label TEXT NOT NULL, title TEXT, description TEXT, caption TEXT,
                hook TEXT, hashtags_json TEXT, predicted_score REAL NOT NULL,
                recommendation_reason TEXT, decision_status TEXT NOT NULL DEFAULT 'Candidate',
                source_video_id TEXT, milestone_hours INTEGER,
                views REAL, likes REAL, comments REAL, shares REAL,
                actual_score REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(experiment_id,label),
                FOREIGN KEY(experiment_id) REFERENCES packaging_experiments(id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_experiment_platform ON packaging_experiments(platform,status)",
            "CREATE INDEX IF NOT EXISTS idx_experiment_variants ON packaging_experiment_variants(experiment_id,decision_status)",
        ):
            self.db.execute(statement)

    def ensure_for_package(self, package_id, package, alternatives=None):
        existing = self.db.frame("SELECT id FROM packaging_experiments WHERE package_id=?", (package_id,))
        if not existing.empty:
            return str(existing.iloc[0]["id"])
        base = package.get("title") or package.get("caption") or ""
        candidates = [base] + list(alternatives or package.get("title_alternatives") or [])
        candidates += self._exploration_variants(base)
        unique = []
        for value in candidates:
            clean = str(value or "").strip()
            normalized = " ".join(re.findall(r"[a-z0-9']+", clean.lower()))
            if clean and all(
                normalized != " ".join(re.findall(r"[a-z0-9']+", prior.lower()))
                for prior in unique
            ):
                unique.append(clean)
            if len(unique) == 4:
                break
        variants = []
        for index, text in enumerate(unique):
            variants.append({
                "label": ("Primary", "Alternative A", "Alternative B", "Exploration")[index],
                "title": text if package.get("title") is not None else None,
                "caption": text if package.get("caption") is not None else None,
                "description": package.get("description"), "hook": package.get("hook"),
                "hashtags": package.get("hashtags") or [],
            })
        return self.create(package_id, variants)

    def create(self, package_id, variants, strategy="creator_dna_with_exploration"):
        package = self.outcomes.package(package_id)
        if len(variants) < 2:
            raise ValueError("An experiment needs at least two distinct variants.")
        experiment_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """INSERT INTO packaging_experiments(
               id,package_id,clip_candidate_id,platform,status,strategy,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (experiment_id, package_id, int(package["clip_candidate_id"]), package["platform"],
             "Draft", strategy, now, now))
        prior = self._prior_copy(package["platform"])
        scored = []
        for index, variant in enumerate(variants):
            text = variant.get("title") or variant.get("caption") or ""
            duplicate = max((self._similarity(text, old) for old in prior), default=0)
            clarity = min(20, len(re.findall(r"\w+", text)) * 2)
            curiosity = 8 if "?" in text else 4 if re.search(r"\b(this|why|how|somehow|never)\b", text, re.I) else 0
            exploration = 6 if index == len(variants) - 1 else 0
            penalty = 35 if duplicate >= .92 else max(0, duplicate - .7) * 60
            predicted = round(max(0, min(100, float(package.get("predicted_score") or 50) + clarity / 4 + curiosity + exploration - penalty)), 1)
            reason = self._variant_reason(text, duplicate, exploration > 0)
            variant_id = str(uuid.uuid4())
            self.db.execute(
                """INSERT INTO packaging_experiment_variants(
                   id,experiment_id,label,title,description,caption,hook,hashtags_json,
                   predicted_score,recommendation_reason,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (variant_id, experiment_id, variant.get("label") or f"Variant {index + 1}",
                 variant.get("title"), variant.get("description"), variant.get("caption"),
                 variant.get("hook"), json.dumps(variant.get("hashtags") or []), predicted,
                 reason, now, now))
            scored.append((predicted, variant_id, reason))
        scored.sort(reverse=True)
        lead = scored[0][0] - scored[1][0]
        confidence = "Medium" if len(prior) >= 8 and lead >= 5 else "Low"
        reason = f"Recommended from Creator DNA fit, clarity, novelty, and duplicate risk. Score lead: {lead:.1f}."
        self.db.execute(
            """UPDATE packaging_experiments SET recommended_variant_id=?,
               recommendation_confidence=?,recommendation_reason=?,updated_at=? WHERE id=?""",
            (scored[0][1], confidence, reason, now, experiment_id))
        return experiment_id

    def select(self, variant_id):
        variant = self.variant(variant_id)
        experiment = self.experiment(variant["experiment_id"])
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute("UPDATE packaging_experiment_variants SET decision_status='Candidate',updated_at=? WHERE experiment_id=? AND decision_status='Selected'", (now, experiment["id"]))
        self.db.execute("UPDATE packaging_experiment_variants SET decision_status='Selected',updated_at=? WHERE id=?", (now, variant_id))
        used = {key: variant.get(key) for key in ("title", "description", "caption", "hook") if variant.get(key) is not None}
        used["hashtags"] = self._json(variant.get("hashtags_json"), [])
        self.outcomes.record_decision(experiment["package_id"], "Approved", used)
        self.db.execute("UPDATE packaging_experiments SET status='Active',updated_at=? WHERE id=?", (now, experiment["id"]))
        return self.variant(variant_id)

    def reject(self, variant_id):
        variant = self.variant(variant_id)
        self.db.execute("UPDATE packaging_experiment_variants SET decision_status='Rejected',updated_at=? WHERE id=?",
                        (datetime.now(timezone.utc).isoformat(), variant_id))
        return self.variant(variant_id)

    def record_result(self, variant_id, metrics, milestone_hours=24, source_video_id=None):
        variant = self.variant(variant_id)
        values = {name: float(metrics.get(name) or 0) for name in ("views", "likes", "comments", "shares")}
        score = self.outcomes._actual_score({**values, "reach": float(metrics.get("reach") or 0), "watch_time": float(metrics.get("watch_time") or 0)})
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """UPDATE packaging_experiment_variants SET decision_status='Published',
               source_video_id=?,milestone_hours=?,views=?,likes=?,comments=?,shares=?,
               actual_score=?,updated_at=? WHERE id=?""",
            (source_video_id, int(milestone_hours), values["views"], values["likes"],
             values["comments"], values["shares"], score, now, variant_id))
        self.evaluate(variant["experiment_id"])
        return self.variant(variant_id)

    def evaluate(self, experiment_id):
        measured = self.db.frame(
            """SELECT * FROM packaging_experiment_variants WHERE experiment_id=?
               AND actual_score IS NOT NULL AND milestone_hours>=24 ORDER BY actual_score DESC""",
            (experiment_id,))
        now = datetime.now(timezone.utc).isoformat()
        if len(measured) < 3:
            status, winner, confidence = "Active", None, "Insufficient"
            reason = f"Need at least 3 measured variants at 24 hours or later; currently {len(measured)}."
        else:
            lead = float(measured.iloc[0]["actual_score"]) - float(measured.iloc[1]["actual_score"])
            if lead < 5:
                status, winner, confidence = "Inconclusive", None, "Low"
                reason = f"Top variants are only {lead:.1f} points apart; keep exploring."
            else:
                status, winner = "Completed", str(measured.iloc[0]["id"])
                confidence = "High" if len(measured) >= 6 and measured["milestone_hours"].min() >= 168 else "Medium"
                reason = f"Winner leads by {lead:.1f} points across {len(measured)} measured variants."
        self.db.execute(
            """UPDATE packaging_experiments SET status=?,winner_variant_id=?,
               result_confidence=?,result_reason=?,updated_at=? WHERE id=?""",
            (status, winner, confidence, reason, now, experiment_id))
        return self.experiment(experiment_id)

    def dashboard(self):
        return self.db.frame(
            """SELECT e.id,e.created_at,e.platform,e.clip_candidate_id,e.status,
               e.recommendation_confidence,e.recommendation_reason,e.result_confidence,e.result_reason,
               COUNT(v.id) AS variants,SUM(CASE WHEN v.decision_status='Published' THEN 1 ELSE 0 END) AS measured_variants,
               MAX(CASE WHEN v.id=e.recommended_variant_id THEN COALESCE(v.title,v.caption) END) AS recommended_copy,
               MAX(CASE WHEN v.id=e.winner_variant_id THEN COALESCE(v.title,v.caption) END) AS winning_copy
               FROM packaging_experiments e JOIN packaging_experiment_variants v ON v.experiment_id=e.id
               GROUP BY e.id ORDER BY e.created_at DESC""")

    def variants(self, experiment_id):
        return self.db.frame(
            """SELECT v.*,CASE WHEN v.id=e.recommended_variant_id THEN 'Yes' ELSE '' END AS recommended,
               CASE WHEN v.id=e.winner_variant_id THEN 'Yes' ELSE '' END AS winner
               FROM packaging_experiment_variants v JOIN packaging_experiments e ON e.id=v.experiment_id
               WHERE v.experiment_id=? ORDER BY v.predicted_score DESC""", (experiment_id,))

    def winning_patterns(self, platform=None):
        sql = """SELECT e.platform,p.topic,p.clip_type,COUNT(*) AS wins,
                 AVG(v.actual_score) AS average_score,
                 AVG(LENGTH(COALESCE(v.title,v.caption))) AS average_characters
                 FROM packaging_experiments e JOIN packaging_experiment_variants v ON v.id=e.winner_variant_id
                 JOIN publishing_packages p ON p.id=e.package_id WHERE e.status='Completed'"""
        params = []
        if platform:
            sql += " AND e.platform=?"; params.append(platform)
        sql += " GROUP BY e.platform,p.topic,p.clip_type ORDER BY wins DESC,average_score DESC"
        return self.db.frame(sql, params)

    def experiment(self, experiment_id):
        frame = self.db.frame("SELECT * FROM packaging_experiments WHERE id=?", (experiment_id,))
        if frame.empty: raise KeyError(experiment_id)
        return frame.iloc[0].to_dict()

    def variant(self, variant_id):
        frame = self.db.frame("SELECT * FROM packaging_experiment_variants WHERE id=?", (variant_id,))
        if frame.empty: raise KeyError(variant_id)
        return frame.iloc[0].to_dict()

    def _prior_copy(self, platform):
        frame = self.db.frame("SELECT title FROM creator_published_titles WHERE platform=? AND example_type='published'", (platform,))
        return [str(value) for value in frame.get("title", []) if str(value).strip()]

    @staticmethod
    def _exploration_variants(text):
        clean = str(text or "").strip().rstrip("?!.")
        if not clean: return []
        return [f"Wait, {clean}?", f"This Is How {clean}", f"We Never Expected {clean}"]

    @staticmethod
    def _variant_reason(text, duplicate, exploration):
        parts = ["explores a new structure" if exploration else "stays close to the clip's strongest event"]
        parts.append("uses a curiosity question" if "?" in text else "uses a direct statement")
        parts.append("low duplicate risk" if duplicate < .7 else "some similarity to past copy")
        return "; ".join(parts).capitalize() + "."

    @staticmethod
    def _similarity(left, right):
        normalize = lambda value: " ".join(re.findall(r"[a-z0-9']+", str(value).lower()))
        return SequenceMatcher(None, normalize(left), normalize(right)).ratio()

    @staticmethod
    def _json(value, default):
        try: return json.loads(value) if value else default
        except (TypeError, ValueError): return default
