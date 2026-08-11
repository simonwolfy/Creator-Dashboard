from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any
import json
import math
import re

from creator_intelligence.core.processes import windowless_run

class SceneIntelligenceService:
    def __init__(
        self, db, transcript_service=None, video_processing=None,
        live_service=None, notifications=None
    ):
        self.db = db
        self.transcript_service = transcript_service
        self.video_processing = video_processing
        self.live_service = live_service
        self.notifications = notifications
        self._ensure_schema()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS scene_analysis_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER,
                transcript_id INTEGER,
                status TEXT DEFAULT 'Queued',
                progress_percent REAL DEFAULT 0,
                settings_json TEXT,
                error_message TEXT,
                queued_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS scene_segments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER,
                transcript_id INTEGER,
                segment_index INTEGER NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                segment_type TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                topic_keywords_json TEXT,
                transcript_density REAL DEFAULT 0,
                speech_ratio REAL DEFAULT 0,
                silence_ratio REAL DEFAULT 0,
                activity_score REAL DEFAULT 0,
                content_value_score REAL DEFAULT 0,
                confidence REAL DEFAULT 0.5,
                source TEXT DEFAULT 'heuristic',
                review_status TEXT DEFAULT 'Unreviewed',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS silence_intervals(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                duration_seconds REAL NOT NULL,
                mean_volume_db REAL,
                source TEXT DEFAULT 'ffmpeg',
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS low_value_intervals(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER,
                transcript_id INTEGER,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                reason TEXT NOT NULL,
                score REAL NOT NULL,
                supporting_metrics_json TEXT,
                review_status TEXT DEFAULT 'Unreviewed',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS vod_timeline_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER,
                transcript_id INTEGER,
                occurred_at_seconds REAL NOT NULL,
                end_seconds REAL,
                item_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                score REAL,
                confidence REAL,
                source_record_type TEXT,
                source_record_id INTEGER,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_scene_segments_time
               ON scene_segments(media_asset_id,transcript_id,start_seconds)""",
            """CREATE INDEX IF NOT EXISTS idx_silence_intervals_time
               ON silence_intervals(media_asset_id,start_seconds)""",
            """CREATE INDEX IF NOT EXISTS idx_low_value_intervals_time
               ON low_value_intervals(media_asset_id,transcript_id,start_seconds)""",
            """CREATE INDEX IF NOT EXISTS idx_vod_timeline_time
               ON vod_timeline_items(media_asset_id,transcript_id,occurred_at_seconds)"""
        ]
        for statement in statements:
            self.db.execute(statement)

    def create_job(self, media_asset_id=None, transcript_id=None, settings=None):
        now = datetime.now().isoformat()
        return int(self.db.execute(
            """INSERT INTO scene_analysis_jobs(
                media_asset_id,transcript_id,status,settings_json,
                queued_at,updated_at
            ) VALUES(?,?,?,?,?,?)""",
            (
                media_asset_id,transcript_id,"Queued",
                json.dumps(settings or {}),now,now
            )
        ))

    def jobs(self):
        return self.db.frame(
            """SELECT * FROM scene_analysis_jobs
               ORDER BY CASE status WHEN 'Running' THEN 1
                                    WHEN 'Queued' THEN 2 ELSE 3 END,
                        queued_at DESC"""
        )

    def analyze(
        self, transcript_id, media_asset_id=None,
        target_segment_minutes=12,
        silence_intervals=None,
        replace=True
    ):
        if not self.transcript_service:
            raise RuntimeError("Transcript service is unavailable.")
        transcript = self.transcript_service.transcript(transcript_id)
        if media_asset_id is None:
            media_asset_id = transcript.get("media_asset_id")
        segments = self.transcript_service.segments(transcript_id)
        if segments.empty:
            raise ValueError("Transcript has no segments.")

        job_id = self.create_job(
            media_asset_id,transcript_id,
            {
                "target_segment_minutes":target_segment_minutes,
                "replace":replace
            }
        )
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE scene_analysis_jobs SET status='Running',
               started_at=?,updated_at=? WHERE id=?""",
            (now,now,job_id)
        )
        try:
            if replace:
                self.db.execute(
                    "DELETE FROM scene_segments WHERE transcript_id=?",
                    (int(transcript_id),)
                )
                self.db.execute(
                    "DELETE FROM low_value_intervals WHERE transcript_id=?",
                    (int(transcript_id),)
                )
                self.db.execute(
                    "DELETE FROM vod_timeline_items WHERE transcript_id=?",
                    (int(transcript_id),)
                )

            silences = silence_intervals
            if silences is None and media_asset_id:
                silences = self.silence_intervals(media_asset_id).to_dict("records")
            silences = silences or []

            groups = self._group_by_topic(
                segments.to_dict("records"),
                target_seconds=max(300,int(target_segment_minutes)*60)
            )
            created = []
            for index, group in enumerate(groups):
                result = self._score_group(
                    group, silences, transcript.get("duration_seconds") or 0
                )
                result.update({
                    "media_asset_id":media_asset_id,
                    "transcript_id":int(transcript_id),
                    "segment_index":index,
                })
                scene_id = self._insert_scene(result)
                result["id"] = scene_id
                created.append(result)

            self._detect_low_value_intervals(
                transcript_id,media_asset_id,created,silences
            )
            self.rebuild_timeline(transcript_id,media_asset_id)

            now = datetime.now().isoformat()
            self.db.execute(
                """UPDATE scene_analysis_jobs SET status='Completed',
                   progress_percent=100,completed_at=?,updated_at=?
                   WHERE id=?""",
                (now,now,job_id)
            )
            if self.notifications:
                self.notifications.create(
                    "System","Success","Scene analysis complete",
                    f"{len(created)} VOD sections were created.",
                    "transcript",transcript_id
                )
            return self.scene_segments(transcript_id)
        except Exception as exc:
            now = datetime.now().isoformat()
            self.db.execute(
                """UPDATE scene_analysis_jobs SET status='Failed',
                   error_message=?,updated_at=? WHERE id=?""",
                (str(exc),now,job_id)
            )
            raise

    def _group_by_topic(self, segments, target_seconds=720):
        if not segments:
            return []
        groups = []
        current = [segments[0]]
        current_start = float(segments[0]["start_seconds"])
        previous_tokens = self._tokens(segments[0]["text"])

        for segment in segments[1:]:
            tokens = self._tokens(segment["text"])
            similarity = self._jaccard(previous_tokens,tokens)
            elapsed = float(segment["end_seconds"]) - current_start
            text = str(segment["text"]).lower()
            transition = bool(re.search(
                r"\b(now|next|after that|later|moving on|we switched|switching to|"
                r"finally|meanwhile|back to|started playing|changed the game)\b",
                text
            ))
            hard_boundary = elapsed >= target_seconds*1.75
            soft_boundary = elapsed >= target_seconds and (
                transition or similarity < 0.08
            )
            if hard_boundary or soft_boundary:
                groups.append(current)
                current = [segment]
                current_start = float(segment["start_seconds"])
            else:
                current.append(segment)
            previous_tokens = (
                previous_tokens | tokens
                if len(current) < 5
                else self._tokens(" ".join(x["text"] for x in current[-5:]))
            )
        if current:
            groups.append(current)
        return groups

    def _tokens(self,text):
        stop = {
            "the","and","that","this","with","from","have","just","were","they",
            "your","youre","about","there","what","when","then","into","really",
            "going","because","would","could","should","some","more","like",
            "okay","yeah","well","right","here","where","while","been","also",
            "dont","cant","wont","im","its","was","are","for","but","not","you"
        }
        return {
            word for word in re.findall(r"\b[a-zA-Z][a-zA-Z'-]{2,}\b",str(text).lower())
            if word not in stop
        }

    def _jaccard(self,a,b):
        if not a or not b:
            return 0
        return len(a & b)/len(a | b)

    def _score_group(self,group,silences,total_duration):
        start = float(group[0]["start_seconds"])
        end = float(group[-1]["end_seconds"])
        duration = max(1,end-start)
        text = " ".join(str(row["text"]) for row in group)
        words = re.findall(r"\b[\w'-]+\b",text)
        speech_seconds = sum(
            max(0,float(row["end_seconds"])-float(row["start_seconds"]))
            for row in group
        )
        silence_seconds = self._overlap_duration(start,end,silences)
        transcript_density = len(words)/(duration/60)
        speech_ratio = min(1,speech_seconds/duration)
        silence_ratio = min(1,silence_seconds/duration)

        excitement = len(re.findall(
            r"\b(oh|wow|no way|holy|clutch|crazy|insane|died|death|boss|raid|"
            r"rare|legendary|shiny|explosion|scream|scared|funny|laugh|win|won)\b",
            text.lower()
        ))
        progression = len(re.findall(
            r"\b(built|finished|completed|found|caught|beat|defeated|unlocked|"
            r"upgraded|crafted|escaped|survived|started|expanded)\b",
            text.lower()
        ))
        low_value_terms = len(re.findall(
            r"\b(inventory|menu|settings|afk|bathroom|brb|waiting|loading|"
            r"organizing|sorting|traveling|walking|grinding)\b",
            text.lower()
        ))

        activity = min(
            100,
            transcript_density*1.4 +
            excitement*8 +
            progression*4 +
            speech_ratio*25 -
            silence_ratio*40 -
            low_value_terms*3
        )
        value = max(0,min(100,
            activity*0.65 +
            min(25,excitement*5) +
            min(20,progression*3) -
            min(25,low_value_terms*4)
        ))
        segment_type = self._classify(text,value,silence_ratio,low_value_terms)
        keywords = self._keywords(text)
        title = self._title(text,keywords,segment_type)
        summary = self._summary(text)
        confidence = min(0.95,0.55 + min(0.25,len(group)/30) + min(0.15,len(words)/500))

        return {
            "start_seconds":start,
            "end_seconds":end,
            "segment_type":segment_type,
            "title":title,
            "summary":summary,
            "topic_keywords_json":json.dumps(keywords),
            "transcript_density":round(transcript_density,3),
            "speech_ratio":round(speech_ratio,3),
            "silence_ratio":round(silence_ratio,3),
            "activity_score":round(activity,2),
            "content_value_score":round(value,2),
            "confidence":round(confidence,3),
            "source":"transcript+silence heuristic",
            "review_status":"Unreviewed",
            "notes":None
        }

    def _classify(self,text,value,silence_ratio,low_value_terms):
        lower = text.lower()
        if silence_ratio >= 0.65:
            return "Dead air / AFK"
        if low_value_terms >= 3 and value < 40:
            return "Low-value maintenance"
        if re.search(r"\b(raid|raided)\b",lower):
            return "Raid / community event"
        if re.search(r"\b(boss|clutch|fight|battle|escaped|survived|died|death)\b",lower):
            return "Action / gameplay event"
        if re.search(r"\b(built|building|crafted|expanded|base|house)\b",lower):
            return "Building / progression"
        if re.search(r"\b(explain|tutorial|guide|how to|tip|strategy)\b",lower):
            return "Explanation / tutorial"
        if value >= 70:
            return "High-value gameplay"
        if value <= 25:
            return "Low-value gameplay"
        return "General gameplay"

    def _keywords(self,text,limit=8):
        tokens = list(self._tokens(text))
        counts = {}
        lower = text.lower()
        for token in tokens:
            counts[token] = len(re.findall(rf"\b{re.escape(token)}\b",lower))
        return [
            token for token,_ in sorted(
                counts.items(),key=lambda item:(-item[1],item[0])
            )[:limit]
        ]

    def _title(self,text,keywords,segment_type):
        sentences = re.split(r"(?<=[.!?])\s+",re.sub(r"\s+"," ",text).strip())
        first = sentences[0] if sentences else ""
        if 8 <= len(first) <= 90:
            return first.rstrip(".!?")
        if keywords:
            return f'{segment_type}: ' + " / ".join(x.title() for x in keywords[:3])
        return segment_type

    def _summary(self,text,max_chars=360):
        clean = re.sub(r"\s+"," ",text).strip()
        if len(clean) <= max_chars:
            return clean
        return clean[:max_chars].rsplit(" ",1)[0] + "…"

    def _overlap_duration(self,start,end,intervals):
        total = 0.0
        for interval in intervals:
            left = max(start,float(interval.get("start_seconds",0)))
            right = min(end,float(interval.get("end_seconds",0)))
            if right > left:
                total += right-left
        return total

    def _insert_scene(self,result):
        now = datetime.now().isoformat()
        columns = [
            "media_asset_id","transcript_id","segment_index",
            "start_seconds","end_seconds","segment_type","title","summary",
            "topic_keywords_json","transcript_density","speech_ratio",
            "silence_ratio","activity_score","content_value_score",
            "confidence","source","review_status","notes"
        ]
        return int(self.db.execute(
            f"""INSERT INTO scene_segments(
                {",".join(columns)},created_at,updated_at
            ) VALUES({",".join("?" for _ in columns)},?,?)""",
            [result.get(c) for c in columns] + [now,now]
        ))

    def detect_silence(
        self, media_asset_id, noise_db=-35, minimum_duration=2.0,
        input_path=None
    ):
        if not self.video_processing:
            raise RuntimeError("Video processing service is unavailable.")
        asset = self.video_processing.asset(media_asset_id)
        source = input_path or asset["source_path"]
        ffmpeg = self.video_processing.ffmpeg_status()
        if not ffmpeg.available:
            raise RuntimeError(ffmpeg.message)

        command = [
            ffmpeg.ffmpeg_path,"-hide_banner","-i",str(source),
            "-af",f"silencedetect=noise={float(noise_db)}dB:d={float(minimum_duration)}",
            "-f","null","-"
        ]
        process = windowless_run(
            command,capture_output=True,text=True,check=False
        )
        output = (process.stderr or "") + "\n" + (process.stdout or "")
        starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)",output)]
        ends = [
            (float(a),float(b))
            for a,b in re.findall(
                r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)",
                output
            )
        ]
        self.db.execute(
            "DELETE FROM silence_intervals WHERE media_asset_id=?",
            (int(media_asset_id),)
        )
        now = datetime.now().isoformat()
        intervals = []
        for index,(end,duration) in enumerate(ends):
            start = starts[index] if index < len(starts) else max(0,end-duration)
            interval = {
                "media_asset_id":int(media_asset_id),
                "start_seconds":start,
                "end_seconds":end,
                "duration_seconds":duration,
                "mean_volume_db":float(noise_db),
                "source":"ffmpeg silencedetect"
            }
            self.db.execute(
                """INSERT INTO silence_intervals(
                    media_asset_id,start_seconds,end_seconds,duration_seconds,
                    mean_volume_db,source,created_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    interval["media_asset_id"],start,end,duration,
                    interval["mean_volume_db"],interval["source"],now
                )
            )
            intervals.append(interval)
        return intervals

    def import_silence_intervals(self,media_asset_id,intervals,replace=True):
        if replace:
            self.db.execute(
                "DELETE FROM silence_intervals WHERE media_asset_id=?",
                (int(media_asset_id),)
            )
        now = datetime.now().isoformat()
        for interval in intervals:
            start=float(interval["start_seconds"])
            end=float(interval["end_seconds"])
            self.db.execute(
                """INSERT INTO silence_intervals(
                    media_asset_id,start_seconds,end_seconds,duration_seconds,
                    mean_volume_db,source,created_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    int(media_asset_id),start,end,max(0,end-start),
                    interval.get("mean_volume_db"),
                    interval.get("source","import"),now
                )
            )

    def silence_intervals(self,media_asset_id):
        return self.db.frame(
            """SELECT * FROM silence_intervals
               WHERE media_asset_id=? ORDER BY start_seconds""",
            (int(media_asset_id),)
        )

    def _detect_low_value_intervals(
        self,transcript_id,media_asset_id,scenes,silences
    ):
        now = datetime.now().isoformat()
        for scene in scenes:
            reasons = []
            score = 0.0
            if scene["silence_ratio"] >= 0.45:
                reasons.append("High silence ratio")
                score += scene["silence_ratio"]*55
            if scene["transcript_density"] < 8:
                reasons.append("Low speech density")
                score += 20
            if scene["content_value_score"] < 30:
                reasons.append("Low content-value score")
                score += 35-scene["content_value_score"]
            if scene["segment_type"] in ("Dead air / AFK","Low-value maintenance"):
                reasons.append(scene["segment_type"])
                score += 30
            if not reasons:
                continue
            self.db.execute(
                """INSERT INTO low_value_intervals(
                    media_asset_id,transcript_id,start_seconds,end_seconds,
                    reason,score,supporting_metrics_json,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    media_asset_id,int(transcript_id),
                    scene["start_seconds"],scene["end_seconds"],
                    "; ".join(reasons),min(100,score),
                    json.dumps({
                        "silence_ratio":scene["silence_ratio"],
                        "transcript_density":scene["transcript_density"],
                        "content_value_score":scene["content_value_score"],
                        "segment_type":scene["segment_type"]
                    }),
                    now,now
                )
            )

        # Add long standalone silence windows even if they span scene boundaries.
        for interval in silences:
            duration = float(interval.get("end_seconds",0))-float(interval.get("start_seconds",0))
            if duration < 30:
                continue
            self.db.execute(
                """INSERT INTO low_value_intervals(
                    media_asset_id,transcript_id,start_seconds,end_seconds,
                    reason,score,supporting_metrics_json,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    media_asset_id,int(transcript_id),
                    float(interval["start_seconds"]),float(interval["end_seconds"]),
                    "Extended silence / possible AFK",
                    min(100,45+duration/10),
                    json.dumps({"duration_seconds":duration}),
                    now,now
                )
            )

    def scene_segments(self,transcript_id=None,media_asset_id=None):
        clauses,params=[],[]
        if transcript_id is not None:
            clauses.append("transcript_id=?")
            params.append(int(transcript_id))
        if media_asset_id is not None:
            clauses.append("media_asset_id=?")
            params.append(int(media_asset_id))
        sql = "SELECT * FROM scene_segments"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY start_seconds"
        return self.db.frame(sql,params)

    def low_value_intervals(self,transcript_id=None,media_asset_id=None):
        clauses,params=[],[]
        if transcript_id is not None:
            clauses.append("transcript_id=?")
            params.append(int(transcript_id))
        if media_asset_id is not None:
            clauses.append("media_asset_id=?")
            params.append(int(media_asset_id))
        sql = "SELECT * FROM low_value_intervals"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY score DESC,start_seconds"
        return self.db.frame(sql,params)

    def rebuild_timeline(self,transcript_id,media_asset_id=None):
        self.db.execute(
            "DELETE FROM vod_timeline_items WHERE transcript_id=?",
            (int(transcript_id),)
        )
        now = datetime.now().isoformat()

        for _,row in self.scene_segments(transcript_id).iterrows():
            self._timeline_insert(
                media_asset_id,transcript_id,
                row["start_seconds"],row["end_seconds"],
                "Scene",row["title"],row["summary"],
                row["content_value_score"],row["confidence"],
                "scene_segment",int(row["id"]),
                {"segment_type":row["segment_type"]},now
            )

        for _,row in self.low_value_intervals(transcript_id,media_asset_id).iterrows():
            self._timeline_insert(
                media_asset_id,transcript_id,
                row["start_seconds"],row["end_seconds"],
                "Low value",row["reason"],None,
                100-float(row["score"]),0.75,
                "low_value_interval",int(row["id"]),{},now
            )

        # Include transcript chapters.
        if self.transcript_service:
            for _,row in self.transcript_service.chapters(transcript_id).iterrows():
                self._timeline_insert(
                    media_asset_id,transcript_id,
                    row["start_seconds"],row["end_seconds"],
                    "Chapter",row["title"],row["summary"],
                    60,row["confidence"],
                    "transcript_chapter",int(row["id"]),{},now
                )

        # Include stream markers when the transcript is tied to a media source
        # connected to a live session by matching source IDs where available.
        if self.live_service:
            try:
                active = self.live_service.active_session()
                if active:
                    markers = self.live_service.markers(active["id"])
                    for _,row in markers.iterrows():
                        self._timeline_insert(
                            media_asset_id,transcript_id,
                            row["elapsed_seconds"],None,
                            "Highlight marker",row["label"],row["notes"],
                            row["strength_score"],row["confidence"],
                            "stream_marker",int(row["id"]),
                            {"marker_type":row["marker_type"]},now
                        )
            except Exception:
                pass

        return self.timeline(transcript_id)

    def _timeline_insert(
        self,media_asset_id,transcript_id,start,end,item_type,title,
        description,score,confidence,source_type,source_id,payload,created_at
    ):
        self.db.execute(
            """INSERT INTO vod_timeline_items(
                media_asset_id,transcript_id,occurred_at_seconds,end_seconds,
                item_type,title,description,score,confidence,
                source_record_type,source_record_id,payload_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                media_asset_id,int(transcript_id),float(start),
                float(end) if end is not None else None,
                item_type,title,description,score,confidence,
                source_type,source_id,json.dumps(payload or {}),created_at
            )
        )

    def timeline(self,transcript_id):
        return self.db.frame(
            """SELECT * FROM vod_timeline_items
               WHERE transcript_id=?
               ORDER BY occurred_at_seconds,
               CASE item_type WHEN 'Highlight marker' THEN 1
                              WHEN 'Scene' THEN 2
                              WHEN 'Chapter' THEN 3 ELSE 4 END""",
            (int(transcript_id),)
        )

    def editor_summary(self,transcript_id):
        scenes = self.scene_segments(transcript_id)
        low = self.low_value_intervals(transcript_id=transcript_id)
        if scenes.empty:
            return {}
        high = scenes.sort_values(
            "content_value_score",ascending=False
        ).head(10)
        total_duration = float(scenes["end_seconds"].max())
        low_seconds = 0.0
        if not low.empty:
            intervals = sorted(
                [
                    (
                        max(0.0,float(row["start_seconds"])),
                        min(total_duration,float(row["end_seconds"]))
                    )
                    for _,row in low.iterrows()
                    if float(row["end_seconds"]) > float(row["start_seconds"])
                ],
                key=lambda pair: pair[0]
            )
            merged = []
            for start,end in intervals:
                if end <= start:
                    continue
                if not merged or start > merged[-1][1]:
                    merged.append([start,end])
                else:
                    merged[-1][1] = max(merged[-1][1],end)
            low_seconds = sum(end-start for start,end in merged)
        return {
            "total_duration_seconds":total_duration,
            "scene_count":len(scenes),
            "high_value_scene_count":int(
                (scenes["content_value_score"]>=70).sum()
            ),
            "low_value_interval_count":len(low),
            "estimated_low_value_seconds":low_seconds,
            "estimated_low_value_percent":(
                low_seconds/total_duration*100 if total_duration else 0
            ),
            "top_scenes":high[
                [
                    "id","start_seconds","end_seconds","title",
                    "segment_type","content_value_score","confidence"
                ]
            ].to_dict("records")
        }
