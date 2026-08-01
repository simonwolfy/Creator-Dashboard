from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any
import json
import math

@dataclass
class HighlightRules:
    grouping_window_seconds: int = 150
    default_pre_roll_seconds: int = 20
    default_post_roll_seconds: int = 45
    short_max_seconds: int = 60
    highlight_max_seconds: int = 180
    minimum_score: float = 35.0

class HighlightDetectionService:
    def __init__(self, db, live_service, pipeline_service=None, notifications=None):
        self.db = db
        self.live_service = live_service
        self.pipeline_service = pipeline_service
        self.notifications = notifications
        self._ensure_schema()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS highlight_candidates(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                candidate_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                classification TEXT NOT NULL,
                start_seconds INTEGER NOT NULL,
                end_seconds INTEGER NOT NULL,
                short_start_seconds INTEGER,
                short_end_seconds INTEGER,
                score REAL NOT NULL,
                confidence REAL NOT NULL,
                suggested_format TEXT,
                suggested_title TEXT,
                supporting_signals_json TEXT,
                source_marker_ids_json TEXT,
                source_event_ids_json TEXT,
                review_status TEXT DEFAULT 'Unreviewed',
                export_status TEXT DEFAULT 'Not exported',
                linked_pipeline_id INTEGER,
                reviewer_notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES live_sessions(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_highlight_candidates_session
               ON highlight_candidates(session_id,score DESC)""",
            """CREATE TABLE IF NOT EXISTS highlight_candidate_actions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                action_payload_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES highlight_candidates(id)
            )""",
            """CREATE TABLE IF NOT EXISTS highlight_settings(
                id INTEGER PRIMARY KEY CHECK(id=1),
                grouping_window_seconds INTEGER DEFAULT 150,
                default_pre_roll_seconds INTEGER DEFAULT 20,
                default_post_roll_seconds INTEGER DEFAULT 45,
                short_max_seconds INTEGER DEFAULT 60,
                highlight_max_seconds INTEGER DEFAULT 180,
                minimum_score REAL DEFAULT 35,
                updated_at TEXT
            )""",
            """INSERT OR IGNORE INTO highlight_settings(
                id,updated_at
            ) VALUES(1,datetime('now'))"""
        ]
        for sql in statements:
            self.db.execute(sql)

    def settings(self):
        frame = self.db.frame("SELECT * FROM highlight_settings WHERE id=1")
        row = frame.iloc[0]
        return HighlightRules(
            grouping_window_seconds=int(row["grouping_window_seconds"]),
            default_pre_roll_seconds=int(row["default_pre_roll_seconds"]),
            default_post_roll_seconds=int(row["default_post_roll_seconds"]),
            short_max_seconds=int(row["short_max_seconds"]),
            highlight_max_seconds=int(row["highlight_max_seconds"]),
            minimum_score=float(row["minimum_score"])
        )

    def update_settings(self, **kwargs):
        allowed = {
            "grouping_window_seconds","default_pre_roll_seconds",
            "default_post_roll_seconds","short_max_seconds",
            "highlight_max_seconds","minimum_score"
        }
        values = {k:v for k,v in kwargs.items() if k in allowed}
        if not values:
            return
        values["updated_at"] = datetime.now().isoformat()
        columns = list(values)
        self.db.execute(
            "UPDATE highlight_settings SET " +
            ",".join(f"{c}=?" for c in columns) +
            " WHERE id=1",
            [values[c] for c in columns]
        )

    def generate_candidates(self, session_id, replace_unreviewed=True):
        rules = self.settings()
        signals = self._collect_signals(session_id)
        groups = self._group_signals(signals, rules.grouping_window_seconds)

        if replace_unreviewed:
            self.db.execute(
                """DELETE FROM highlight_candidates
                   WHERE session_id=? AND review_status='Unreviewed'
                   AND export_status='Not exported'""",
                (int(session_id),)
            )

        created = []
        for group_index, group in enumerate(groups, start=1):
            candidate = self._build_candidate(session_id, group, group_index, rules)
            if candidate["score"] < rules.minimum_score:
                continue
            self._insert_candidate(candidate)
            created.append(candidate)

        if self.notifications and created:
            self.notifications.create(
                "System","Success","Highlight candidates generated",
                f"{len(created)} candidates were generated for live session {session_id}.",
                "live_session",session_id
            )
        return self.candidates(session_id)

    def _collect_signals(self, session_id):
        markers = self.db.frame(
            """SELECT id,occurred_at,elapsed_seconds,marker_type AS signal_type,
               label AS title,strength_score,confidence,
               supporting_metrics_json,'marker' AS source_kind
               FROM stream_markers WHERE session_id=?""",
            (int(session_id),)
        )
        events = self.db.frame(
            """SELECT id,occurred_at,elapsed_seconds,event_type AS signal_type,
               title,0 AS strength_score,0.65 AS confidence,
               payload_json AS supporting_metrics_json,
               'event' AS source_kind
               FROM live_events
               WHERE session_id=? AND event_type IN(
                   'raid','new_peak','follow','game_change','manual_marker',
                   'scene_change','record_state'
               )""",
            (int(session_id),)
        )
        rows = []
        for frame in (markers, events):
            if frame.empty:
                continue
            for _, row in frame.iterrows():
                data = row.to_dict()
                try:
                    data["metrics"] = json.loads(
                        data.get("supporting_metrics_json") or "{}"
                    )
                except Exception:
                    data["metrics"] = {}
                rows.append(data)
        rows.sort(key=lambda x: (int(x["elapsed_seconds"]), x["source_kind"]))
        return rows

    def _group_signals(self, signals, window_seconds):
        if not signals:
            return []
        groups = [[signals[0]]]
        for signal in signals[1:]:
            last = groups[-1][-1]
            if int(signal["elapsed_seconds"]) - int(last["elapsed_seconds"]) <= window_seconds:
                groups[-1].append(signal)
            else:
                groups.append([signal])
        return groups

    def _build_candidate(self, session_id, group, index, rules):
        times = [int(s["elapsed_seconds"]) for s in group]
        first = min(times)
        last = max(times)
        score, confidence, classification = self._score_group(group)
        start = max(0, first - rules.default_pre_roll_seconds)
        end = last + rules.default_post_roll_seconds
        if end - start > rules.highlight_max_seconds:
            end = start + rules.highlight_max_seconds

        strongest = max(
            group,
            key=lambda s: float(s.get("strength_score") or 0)
        )
        short_center = int(strongest["elapsed_seconds"])
        short_start = max(0, short_center - 15)
        short_end = short_start + rules.short_max_seconds
        if short_end > end:
            short_end = end
            short_start = max(start, short_end - rules.short_max_seconds)

        formats = self._suggest_formats(group, classification, score)
        suggested_title = self._suggest_title(group, classification)
        marker_ids = [
            int(s["id"]) for s in group if s["source_kind"] == "marker"
        ]
        event_ids = [
            int(s["id"]) for s in group if s["source_kind"] == "event"
        ]
        key = f"{session_id}:{first}:{last}:{index}"
        return {
            "session_id": int(session_id),
            "candidate_key": key,
            "title": suggested_title,
            "classification": classification,
            "start_seconds": start,
            "end_seconds": end,
            "short_start_seconds": short_start,
            "short_end_seconds": short_end,
            "score": round(score, 2),
            "confidence": round(confidence, 3),
            "suggested_format": formats,
            "suggested_title": suggested_title,
            "supporting_signals_json": json.dumps(group, default=str),
            "source_marker_ids_json": json.dumps(marker_ids),
            "source_event_ids_json": json.dumps(event_ids),
            "review_status": "Unreviewed",
            "export_status": "Not exported",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

    def _score_group(self, group):
        type_weights = {
            "Raid": 34, "raid": 30,
            "Viewer spike": 28, "new_peak": 14,
            "Chat spike": 24,
            "Follow spike": 20, "follow": 5,
            "Manual": 26, "manual_marker": 22,
            "Game change": 5, "game_change": 4,
            "scene_change": 3, "record_state": 2
        }
        score = 0.0
        confidence_values = []
        types = []
        for signal in group:
            signal_type = str(signal["signal_type"])
            types.append(signal_type)
            strength = float(signal.get("strength_score") or 0)
            weight = type_weights.get(signal_type, 4)
            score += weight + strength * 0.22
            confidence_values.append(float(signal.get("confidence") or 0.6))

            metrics = signal.get("metrics") or {}
            if "raid_viewers" in metrics:
                score += min(20, math.log10(max(int(metrics["raid_viewers"]),1))*8)
            if "multiplier" in metrics:
                score += min(18, float(metrics["multiplier"])*4)
            if "follows" in metrics:
                score += min(15, float(metrics["follows"])*2.5)

        density_bonus = min(20, max(0, len(group)-1)*4)
        score += density_bonus
        score = min(100, score)
        confidence = min(
            0.99,
            (sum(confidence_values)/len(confidence_values)) +
            min(0.15, len(group)*0.02)
        )
        classification = self._classify(types)
        return score, confidence, classification

    def _classify(self, types):
        normalized = {str(t).lower() for t in types}
        if "raid" in normalized:
            return "Raid reaction"
        if "manual" in normalized or "manual_marker" in normalized:
            return "Strong reaction or manual moment"
        if "viewer spike" in normalized and "chat spike" in normalized:
            return "High-engagement moment"
        if "follow spike" in normalized:
            return "Community growth moment"
        if "chat spike" in normalized:
            return "Community interaction"
        if "viewer spike" in normalized or "new_peak" in normalized:
            return "Viewer milestone"
        if "game change" in normalized or "game_change" in normalized:
            return "Game transition"
        return "General highlight"

    def _suggest_formats(self, group, classification, score):
        if classification == "Game transition":
            return "Chapter boundary"
        if score >= 85:
            return "Short + full highlight"
        if score >= 65:
            return "Short or highlight"
        return "Review candidate"

    def _suggest_title(self, group, classification):
        if classification == "Raid reaction":
            raid = next(
                (s for s in group if str(s["signal_type"]).lower() == "raid"),
                None
            )
            if raid:
                channel = (raid.get("metrics") or {}).get("source_channel")
                if channel:
                    return f"Raid reaction: {channel}"
            return "Raid reaction"
        if classification == "Viewer milestone":
            return "The stream suddenly took off"
        if classification == "Community interaction":
            return "Chat went wild"
        if classification == "Community growth moment":
            return "A sudden wave of new followers"
        if classification == "Game transition":
            return "Stream chapter transition"
        if classification == "Strong reaction or manual moment":
            manual = next(
                (s for s in group if str(s["signal_type"]).lower() in {"manual","manual_marker"}),
                None
            )
            return manual["title"] if manual else "Strong stream moment"
        return "Potential stream highlight"

    def _insert_candidate(self, candidate):
        columns = list(candidate)
        self.db.execute(
            f"""INSERT OR REPLACE INTO highlight_candidates(
                {",".join(columns)}
            ) VALUES({",".join("?" for _ in columns)})""",
            [candidate[c] for c in columns]
        )

    def candidates(self, session_id=None, status=None):
        clauses = []
        params = []
        if session_id is not None:
            clauses.append("session_id=?")
            params.append(int(session_id))
        if status:
            clauses.append("review_status=?")
            params.append(status)
        sql = """SELECT * FROM highlight_candidates"""
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY score DESC,start_seconds"
        return self.db.frame(sql, params)

    def candidate(self, candidate_id):
        frame = self.db.frame(
            "SELECT * FROM highlight_candidates WHERE id=?",
            (int(candidate_id),)
        )
        if frame.empty:
            raise KeyError(candidate_id)
        return frame.iloc[0].to_dict()

    def set_review_status(self, candidate_id, status, notes=None):
        allowed = {"Unreviewed","Approved","Rejected","Needs changes"}
        if status not in allowed:
            raise ValueError(status)
        self.db.execute(
            """UPDATE highlight_candidates SET review_status=?,
               reviewer_notes=COALESCE(?,reviewer_notes),updated_at=?
               WHERE id=?""",
            (status,notes,datetime.now().isoformat(),int(candidate_id))
        )
        self._log_action(candidate_id,"review_status",{
            "status":status,"notes":notes
        })
        return self.candidate(candidate_id)

    def update_boundaries(
        self, candidate_id, start_seconds, end_seconds,
        short_start_seconds=None, short_end_seconds=None
    ):
        if int(end_seconds) <= int(start_seconds):
            raise ValueError("End time must be after start time.")
        self.db.execute(
            """UPDATE highlight_candidates SET start_seconds=?,
               end_seconds=?,short_start_seconds=COALESCE(?,short_start_seconds),
               short_end_seconds=COALESCE(?,short_end_seconds),
               updated_at=? WHERE id=?""",
            (
                int(start_seconds),int(end_seconds),
                short_start_seconds,short_end_seconds,
                datetime.now().isoformat(),int(candidate_id)
            )
        )
        self._log_action(candidate_id,"update_boundaries",{
            "start_seconds":start_seconds,"end_seconds":end_seconds,
            "short_start_seconds":short_start_seconds,
            "short_end_seconds":short_end_seconds
        })
        return self.candidate(candidate_id)

    def merge_candidates(self, candidate_ids):
        ids = [int(i) for i in candidate_ids]
        if len(ids) < 2:
            raise ValueError("At least two candidates are required.")
        frames = self.db.frame(
            f"""SELECT * FROM highlight_candidates
                WHERE id IN ({",".join("?" for _ in ids)})""", ids
        )
        if len(frames) != len(ids):
            raise KeyError("One or more candidates were not found.")
        if frames["session_id"].nunique() != 1:
            raise ValueError("Candidates must belong to the same session.")

        session_id = int(frames.iloc[0]["session_id"])
        start = int(frames["start_seconds"].min())
        end = int(frames["end_seconds"].max())
        score = min(100, float(frames["score"].max()) + 8)
        confidence = min(0.99, float(frames["confidence"].mean()) + 0.05)
        title = " + ".join(frames["title"].astype(str).tolist()[:2])
        key = f"merge:{session_id}:{start}:{end}:{datetime.now().timestamp()}"
        now = datetime.now().isoformat()

        merged = {
            "session_id":session_id,
            "candidate_key":key,
            "title":title,
            "classification":"Merged highlight",
            "start_seconds":start,
            "end_seconds":end,
            "short_start_seconds":start,
            "short_end_seconds":min(end,start+60),
            "score":score,
            "confidence":confidence,
            "suggested_format":"Short + full highlight",
            "suggested_title":title,
            "supporting_signals_json":json.dumps({
                "merged_candidate_ids":ids
            }),
            "source_marker_ids_json":"[]",
            "source_event_ids_json":"[]",
            "review_status":"Needs changes",
            "export_status":"Not exported",
            "created_at":now,
            "updated_at":now
        }
        self._insert_candidate(merged)
        merged_row = self.db.frame(
            "SELECT * FROM highlight_candidates WHERE candidate_key=?",(key,)
        ).iloc[0].to_dict()
        for candidate_id in ids:
            self.set_review_status(candidate_id,"Rejected","Merged into another candidate.")
        self._log_action(merged_row["id"],"merge",{"candidate_ids":ids})
        return merged_row

    def split_candidate(self, candidate_id, split_seconds):
        original = self.candidate(candidate_id)
        split_seconds = int(split_seconds)
        if not (
            int(original["start_seconds"]) < split_seconds <
            int(original["end_seconds"])
        ):
            raise ValueError("Split point must fall inside the candidate.")
        now = datetime.now().isoformat()
        created = []
        for suffix,start,end in (
            ("A",int(original["start_seconds"]),split_seconds),
            ("B",split_seconds,int(original["end_seconds"]))
        ):
            key = f"split:{candidate_id}:{suffix}:{datetime.now().timestamp()}"
            candidate = {
                "session_id":int(original["session_id"]),
                "candidate_key":key,
                "title":f'{original["title"]} — Part {suffix}',
                "classification":original["classification"],
                "start_seconds":start,
                "end_seconds":end,
                "short_start_seconds":start,
                "short_end_seconds":min(end,start+60),
                "score":max(0,float(original["score"])-5),
                "confidence":max(0,float(original["confidence"])-0.05),
                "suggested_format":original["suggested_format"],
                "suggested_title":f'{original["suggested_title"]} — Part {suffix}',
                "supporting_signals_json":original["supporting_signals_json"],
                "source_marker_ids_json":original["source_marker_ids_json"],
                "source_event_ids_json":original["source_event_ids_json"],
                "review_status":"Needs changes",
                "export_status":"Not exported",
                "created_at":now,
                "updated_at":now
            }
            self._insert_candidate(candidate)
            created.append(
                self.db.frame(
                    "SELECT * FROM highlight_candidates WHERE candidate_key=?",(key,)
                ).iloc[0].to_dict()
            )
        self.set_review_status(candidate_id,"Rejected","Split into two candidates.")
        self._log_action(candidate_id,"split",{"split_seconds":split_seconds})
        return created

    def export_to_pipeline(self, candidate_id, content_type="YouTube Short"):
        candidate = self.candidate(candidate_id)
        if candidate["review_status"] != "Approved":
            raise ValueError("Candidate must be approved before export.")
        now = datetime.now().isoformat()
        notes = (
            f'Highlight candidate #{candidate_id}\n'
            f'Session: {candidate["session_id"]}\n'
            f'Full boundary: {self.format_time(candidate["start_seconds"])}–'
            f'{self.format_time(candidate["end_seconds"])}\n'
            f'Short boundary: {self.format_time(candidate["short_start_seconds"])}–'
            f'{self.format_time(candidate["short_end_seconds"])}\n'
            f'Score: {candidate["score"]:.1f}/100\n'
            f'Confidence: {candidate["confidence"]:.0%}\n'
            f'Classification: {candidate["classification"]}\n'
            f'Notes: {candidate["reviewer_notes"] or ""}'
        )
        pipeline_id = int(self.db.execute(
            """INSERT INTO content_pipeline(
                title,platform,content_type,status,notes,created_at,updated_at,
                priority,progress_percent,linked_stream_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                candidate["suggested_title"] or candidate["title"],
                "YouTube" if "YouTube" in content_type else "Multi-platform",
                content_type,"Selected",notes,now,now,
                "High" if float(candidate["score"])>=80 else "Normal",
                0,str(candidate["session_id"])
            )
        ))
        self.db.execute(
            """UPDATE highlight_candidates SET export_status='Exported',
               linked_pipeline_id=?,updated_at=? WHERE id=?""",
            (pipeline_id,now,int(candidate_id))
        )
        self._log_action(candidate_id,"export_to_pipeline",{
            "pipeline_id":pipeline_id,"content_type":content_type
        })
        if self.notifications:
            self.notifications.create(
                "Pipeline","Success","Highlight exported",
                f'{candidate["title"]} was added to the content pipeline.',
                "pipeline_item",pipeline_id
            )
        return self.candidate(candidate_id)

    def _log_action(self, candidate_id, action_type, payload=None):
        self.db.execute(
            """INSERT INTO highlight_candidate_actions(
                candidate_id,action_type,action_payload_json,created_at
            ) VALUES(?,?,?,?)""",
            (
                int(candidate_id),action_type,
                json.dumps(payload or {},default=str),
                datetime.now().isoformat()
            )
        )

    @staticmethod
    def format_time(seconds):
        seconds = int(seconds or 0)
        hours, remainder = divmod(seconds,3600)
        minutes, secs = divmod(remainder,60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
