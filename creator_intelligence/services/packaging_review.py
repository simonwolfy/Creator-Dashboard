from __future__ import annotations

from datetime import datetime, timezone
import json

import pandas as pd


LIMITS = {
    "youtube": {"title": 100, "description": 5000},
    "tiktok": {"caption": 2200},
    "instagram": {"caption": 2200},
    "twitch": {"title": 100},
}


class PackagingReviewService:
    """Creator-facing review and publishing handoff for generated packages."""

    def __init__(self, db, planner, transcripts=None):
        self.db = db
        self.planner = planner
        self.transcripts = transcripts
        self.outcomes = planner.outcomes
        self.experiments = planner.experiments

    def queue(self, status="All", platform="All"):
        clauses, params = [], []
        if status != "All":
            clauses.append("p.decision_status=?"); params.append(status)
        if platform != "All":
            clauses.append("p.platform=?"); params.append(platform.lower())
        sql = """SELECT p.id,p.created_at,p.clip_candidate_id,p.platform,p.decision_status,
                 p.edit_status,p.predicted_performance,p.predicted_score,p.topic,p.clip_type,
                 COALESCE(p.used_title,p.used_caption,p.generated_title,p.generated_caption) AS review_copy,
                 e.status AS experiment_status,e.recommendation_confidence,
                 v.label AS recommended_variant,v.recommendation_reason
                 FROM publishing_packages p
                 LEFT JOIN packaging_experiments e ON e.package_id=p.id
                 LEFT JOIN packaging_experiment_variants v ON v.id=e.recommended_variant_id"""
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY p.created_at DESC,p.clip_candidate_id,p.platform"
        return self.db.frame(sql, params)

    def detail(self, package_id):
        package = self.outcomes.package(package_id)
        experiment = self.db.frame("SELECT * FROM packaging_experiments WHERE package_id=?", (package_id,))
        variants = pd.DataFrame()
        if not experiment.empty:
            variants = self.experiments.variants(str(experiment.iloc[0]["id"]))
        clip = self.db.frame("SELECT * FROM transcript_clip_candidates WHERE id=?", (int(package["clip_candidate_id"]),))
        transcript_text, source_path = "", None
        if not clip.empty:
            row = clip.iloc[0]
            segments = self.db.frame(
                """SELECT text FROM transcript_segments WHERE transcript_id=?
                   AND end_seconds>=? AND start_seconds<=? ORDER BY start_seconds""",
                (int(row["transcript_id"]), float(row["start_seconds"]), float(row["end_seconds"])))
            transcript_text = " ".join(str(value) for value in segments.get("text", []) if str(value).strip())
            transcript = self.db.frame("SELECT * FROM transcripts WHERE id=?", (int(row["transcript_id"]),))
            if not transcript.empty:
                source_path = transcript.iloc[0].get("source_path") if "source_path" in transcript else None
        return {"package": package, "clip": clip.iloc[0].to_dict() if not clip.empty else {},
                "variants": variants, "transcript": transcript_text,
                "source_path": source_path, "validation": self.validate(package_id)}

    def validate(self, package_id, edits=None):
        package = self.outcomes.package(package_id)
        edits = edits or {}
        fields = {
            "title": edits.get("title", package.get("used_title") or package.get("generated_title") or ""),
            "description": edits.get("description", package.get("used_description") or package.get("generated_description") or ""),
            "caption": edits.get("caption", package.get("used_caption") or package.get("generated_caption") or ""),
            "hook": edits.get("hook", package.get("used_hook") or package.get("generated_hook") or ""),
        }
        issues = []
        primary = fields["title"] or fields["caption"]
        if not primary.strip(): issues.append("Add a title or caption before approval.")
        for field, limit in LIMITS.get(package["platform"], {}).items():
            length = len(fields[field])
            if length > limit: issues.append(f"{field.title()} is {length - limit} characters over the {limit}-character limit.")
        hashtags = edits.get("hashtags")
        if hashtags is None:
            hashtags = self._json(package.get("used_hashtags_json") or package.get("generated_hashtags_json"), [])
        if any(not str(tag).startswith("#") for tag in hashtags):
            issues.append("Every hashtag must begin with #.")
        return {"valid": not issues, "issues": issues, "fields": fields,
                "characters": {key: len(value) for key, value in fields.items()},
                "limits": LIMITS.get(package["platform"], {})}

    def save_edits(self, package_id, edits):
        package = self.outcomes.package(package_id)
        status = package["decision_status"] if package["decision_status"] in {"Approved", "Published"} else "Generated"
        return self.outcomes.record_decision(package_id, status, edits)

    def approve(self, package_id, edits=None):
        validation = self.validate(package_id, edits)
        if not validation["valid"]:
            raise ValueError(" ".join(validation["issues"]))
        return self.outcomes.record_decision(package_id, "Approved", edits or {})

    def reject(self, package_id):
        return self.outcomes.record_decision(package_id, "Rejected")

    def bulk_approve(self, package_ids):
        approved, failed = [], {}
        for package_id in package_ids:
            try: self.approve(str(package_id)); approved.append(str(package_id))
            except Exception as exc: failed[str(package_id)] = str(exc)
        return {"approved": approved, "failed": failed}

    def regenerate(self, package_id):
        if not self.transcripts:
            raise RuntimeError("Transcript intelligence is unavailable.")
        package = self.outcomes.package(package_id)
        self.reject(package_id)
        return self.transcripts.analyze_clip_candidate(int(package["clip_candidate_id"]))

    def send_to_publishing(self, package_id, planned_publish_at=None):
        package = self.outcomes.package(package_id)
        if package["decision_status"] != "Approved":
            raise ValueError("Approve the package before sending it to Publishing.")
        existing = self.db.frame(
            "SELECT id FROM publishing_items WHERE pipeline_item_id=? AND platform=?",
            (int(package["clip_candidate_id"]), self._platform_label(package["platform"])))
        if not existing.empty: return int(existing.iloc[0]["id"])
        title = package.get("used_title") or package.get("generated_title") or package.get("used_caption") or package.get("generated_caption")
        return self.planner.create_item({
            "title": title, "platform": self._platform_label(package["platform"]),
            "content_type": "Short", "status": "Ready",
            "pipeline_item_id": int(package["clip_candidate_id"]),
            "planned_publish_at": planned_publish_at,
            "score": float(package.get("predicted_score") or 0), "confidence": .7,
            "rationale": f"Approved packaging review {package_id}",
            "description_status": "Ready" if package.get("used_description") or package.get("generated_description") else "Missing",
            "thumbnail_status": "Missing", "metadata_status": "Ready", "upload_status": "Not uploaded",
            "notes": json.dumps({"package_id": package_id})})

    def export_payload(self, package_ids):
        payload = []
        for package_id in package_ids:
            package = self.outcomes.package(str(package_id))
            payload.append({
                "package_id": package["id"], "clip_candidate_id": package["clip_candidate_id"],
                "platform": package["platform"], "status": package["decision_status"],
                "title": package.get("used_title") or package.get("generated_title"),
                "description": package.get("used_description") or package.get("generated_description"),
                "caption": package.get("used_caption") or package.get("generated_caption"),
                "hook": package.get("used_hook") or package.get("generated_hook"),
                "hashtags": self._json(package.get("used_hashtags_json") or package.get("generated_hashtags_json"), []),
            })
        return payload

    @staticmethod
    def _platform_label(platform):
        return {"youtube":"YouTube Shorts","tiktok":"TikTok","instagram":"Instagram","twitch":"Twitch"}.get(platform, platform.title())

    @staticmethod
    def _json(value, default):
        try: return json.loads(value) if value else default
        except (TypeError, ValueError): return default
