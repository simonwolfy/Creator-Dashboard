from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import csv
import json
import math
import os
import re
import shutil
import subprocess
import threading
import uuid

TRANSCRIPT_JOB_TYPES = (
    "Transcribe audio",
    "Import transcript",
    "Build chapters",
    "Build search index",
)

_CHAPTER_STOP_WORDS = frozenset(
    """
    a about after again all also am an and any are as at back be because been
    before being beneath beside between but by can could did didnt do does
    doesnt doing dont down during for
    from get getting go going gonna got had has have he her here him his how i
    id ill im into is it its ive just kinda know let lets like literally maybe
    inside me more my near next no not now of oh okay on one or our out outside
    over really right under underneath
    said say see she should so some sort still stuff than that thats the their
    them then there these they thing things think this those through to too uh
    um up us very want was way we well were what when where which while who why
    will with within without would yeah yep yes you your youre
    """.split()
)
_CHAPTER_FILLER_WORDS = frozenset(
    "hey hello hi hmm huh bam bruh bro dude guys meh nope ooh uh um whoa wow".split()
)
_CHAPTER_GENERIC_CONTENT = frozenset(
    "bad better chapter good guy need said stream sure thing time wait".split()
)
_CHAPTER_ACTION_ROOTS = {
    "attack": "Fighting", "attacked": "Fighting",
    "build": "Building", "built": "Building",
    "discover": "Discovering", "discovered": "Discovering",
    "escape": "Escaping", "escaped": "Escaping",
    "fight": "Fighting", "fighting": "Fighting",
    "find": "Finding", "found": "Finding",
    "loot": "Looting", "looted": "Looting", "looting": "Looting",
    "plan": "Planning", "planned": "Planning", "planning": "Planning",
    "run": "Escaping", "running": "Escaping",
    "survive": "Surviving", "survived": "Surviving",
}
_CHAPTER_ACTION_WORDS = frozenset(
    set(_CHAPTER_ACTION_ROOTS)
    | {
        "die", "died", "kill", "killed", "lose", "lost", "save", "saved",
        "shoot", "shot", "win", "won",
    }
)
_CHAPTER_TRANSITION_PATTERN = re.compile(
    r"\b(after that|back to|finally|later on|meanwhile|moving on|next up|"
    r"now (?:we|i) (?:need|want|will)|switch(?:ed|ing)? to)\b",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class TranscriptEngineStatus:
    engine: str
    available: bool
    command: str | None
    message: str

class TranscriptService:
    def __init__(self, db, video_processing=None, notifications=None):
        self.db = db
        self.video_processing = video_processing
        self.notifications = notifications
        self._cancel: dict[int, threading.Event] = {}
        self._processes: dict[int, subprocess.Popen] = {}
        self._ensure_schema()
        self.recover_interrupted_jobs()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS transcripts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER,
                content_source_id INTEGER,
                title TEXT NOT NULL,
                language TEXT DEFAULT 'en',
                engine TEXT,
                model_name TEXT,
                status TEXT DEFAULT 'Draft',
                duration_seconds REAL,
                word_count INTEGER DEFAULT 0,
                segment_count INTEGER DEFAULT 0,
                source_path TEXT,
                confidence REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(media_asset_id) REFERENCES media_assets(id)
            )""",
            """CREATE TABLE IF NOT EXISTS transcript_segments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id INTEGER NOT NULL,
                segment_index INTEGER NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                text TEXT NOT NULL,
                speaker TEXT,
                confidence REAL,
                words_json TEXT,
                tags_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(transcript_id,segment_index),
                FOREIGN KEY(transcript_id) REFERENCES transcripts(id)
            )""",
            """CREATE TABLE IF NOT EXISTS transcript_words(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id INTEGER NOT NULL,
                segment_id INTEGER,
                word_index INTEGER NOT NULL,
                start_seconds REAL,
                end_seconds REAL,
                word TEXT NOT NULL,
                probability REAL,
                speaker TEXT,
                FOREIGN KEY(transcript_id) REFERENCES transcripts(id),
                FOREIGN KEY(segment_id) REFERENCES transcript_segments(id)
            )""",
            """CREATE TABLE IF NOT EXISTS transcript_chapters(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id INTEGER NOT NULL,
                chapter_index INTEGER NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                keywords_json TEXT,
                confidence REAL DEFAULT 0.5,
                source TEXT DEFAULT 'heuristic',
                review_status TEXT DEFAULT 'Unreviewed',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(transcript_id,chapter_index),
                FOREIGN KEY(transcript_id) REFERENCES transcripts(id)
            )""",
            """CREATE TABLE IF NOT EXISTS transcript_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id INTEGER,
                media_asset_id INTEGER,
                job_type TEXT NOT NULL,
                status TEXT DEFAULT 'Queued',
                priority INTEGER DEFAULT 100,
                progress_percent REAL DEFAULT 0,
                settings_json TEXT,
                input_path TEXT,
                output_path TEXT,
                engine TEXT,
                model_name TEXT,
                error_message TEXT,
                attempt_count INTEGER DEFAULT 0,
                queued_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                cancelled_at TEXT,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS transcript_search_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                result_count INTEGER DEFAULT 0,
                searched_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_transcript_segments_time
               ON transcript_segments(transcript_id,start_seconds,end_seconds)""",
            """CREATE INDEX IF NOT EXISTS idx_transcript_chapters_time
               ON transcript_chapters(transcript_id,start_seconds)""",
            """CREATE INDEX IF NOT EXISTS idx_transcript_jobs_queue
               ON transcript_jobs(status,priority,queued_at)""",
        ]
        for statement in statements:
            self.db.execute(statement)

        # FTS5 may not exist in every SQLite build. Keep a normal-table fallback.
        try:
            self.db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts
                USING fts5(
                    text,
                    transcript_id UNINDEXED,
                    segment_id UNINDEXED,
                    start_seconds UNINDEXED,
                    end_seconds UNINDEXED,
                    title UNINDEXED,
                    tokenize='porter unicode61'
                )""")
        except Exception:
            self.db.execute("""CREATE TABLE IF NOT EXISTS transcript_fts(
                text TEXT,
                transcript_id INTEGER,
                segment_id INTEGER,
                start_seconds REAL,
                end_seconds REAL,
                title TEXT
            )""")

    def engine_status(self):
        custom = os.getenv("CREATOR_INTELLIGENCE_WHISPER")
        commands = [
            ("whisper.cpp", custom),
            ("faster-whisper", shutil.which("faster-whisper")),
            ("openai-whisper", shutil.which("whisper")),
        ]
        for engine, command in commands:
            if command:
                return TranscriptEngineStatus(
                    engine, True, command,
                    f"{engine} is available at {command}."
                )
        return TranscriptEngineStatus(
            "none", False, None,
            "No supported local Whisper command was found. "
            "Transcript import, search, chapters, and testing remain available."
        )

    def create_transcript(
        self, title, media_asset_id=None, content_source_id=None,
        language="en", engine=None, model_name=None, source_path=None,
        status="Draft"
    ):
        now = datetime.now().isoformat()
        return int(self.db.execute(
            """INSERT INTO transcripts(
                media_asset_id,content_source_id,title,language,engine,
                model_name,status,source_path,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                media_asset_id,content_source_id,title,language,engine,
                model_name,status,source_path,now,now
            )
        ))

    def transcript(self, transcript_id):
        frame = self.db.frame(
            """SELECT t.*,a.display_name AS media_name,a.source_path AS media_path
               FROM transcripts t
               LEFT JOIN media_assets a ON a.id=t.media_asset_id
               WHERE t.id=?""",(int(transcript_id),)
        )
        if frame.empty:
            raise KeyError(transcript_id)
        return frame.iloc[0].to_dict()

    def transcripts(self):
        return self.db.frame(
            """SELECT t.id,t.title,t.language,t.engine,t.model_name,t.status,
               t.duration_seconds,t.word_count,t.segment_count,t.confidence,
               a.display_name AS media_asset,t.created_at,t.updated_at
               FROM transcripts t
               LEFT JOIN media_assets a ON a.id=t.media_asset_id
               ORDER BY t.updated_at DESC"""
        )

    def segments(self, transcript_id, start=None, end=None):
        clauses = ["transcript_id=?"]
        params: list[Any] = [int(transcript_id)]
        if start is not None:
            clauses.append("end_seconds>=?")
            params.append(float(start))
        if end is not None:
            clauses.append("start_seconds<=?")
            params.append(float(end))
        return self.db.frame(
            """SELECT id,segment_index,start_seconds,end_seconds,text,
               speaker,confidence,tags_json
               FROM transcript_segments WHERE """ +
            " AND ".join(clauses) +
            " ORDER BY segment_index",
            params
        )

    def add_segments(self, transcript_id, segments, replace=True):
        transcript = self.transcript(transcript_id)
        if replace:
            self.db.execute(
                "DELETE FROM transcript_words WHERE transcript_id=?",
                (int(transcript_id),)
            )
            self.db.execute(
                "DELETE FROM transcript_segments WHERE transcript_id=?",
                (int(transcript_id),)
            )
        now = datetime.now().isoformat()
        word_count = 0
        confidences = []
        max_end = 0.0
        for index, segment in enumerate(segments):
            start = float(segment.get("start", segment.get("start_seconds", 0)) or 0)
            end = float(segment.get("end", segment.get("end_seconds", start)) or start)
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            confidence = segment.get("confidence")
            if confidence is not None:
                confidences.append(float(confidence))
            words = segment.get("words") or []
            segment_id = int(self.db.execute(
                """INSERT INTO transcript_segments(
                    transcript_id,segment_index,start_seconds,end_seconds,text,
                    speaker,confidence,words_json,tags_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(transcript_id),index,start,end,text,
                    segment.get("speaker"),confidence,
                    json.dumps(words,default=str),
                    json.dumps(segment.get("tags") or []),
                    now,now
                )
            ))
            if words:
                for word_index, word in enumerate(words):
                    token = str(word.get("word") or word.get("text") or "").strip()
                    if not token:
                        continue
                    self.db.execute(
                        """INSERT INTO transcript_words(
                            transcript_id,segment_id,word_index,start_seconds,
                            end_seconds,word,probability,speaker
                        ) VALUES(?,?,?,?,?,?,?,?)""",
                        (
                            int(transcript_id),segment_id,word_index,
                            word.get("start"),word.get("end"),token,
                            word.get("probability"),word.get("speaker")
                        )
                    )
                    word_count += 1
            else:
                word_count += len(re.findall(r"\b[\w'-]+\b", text))
            max_end = max(max_end,end)

        segment_count = len(self.segments(transcript_id))
        confidence_value = (
            sum(confidences)/len(confidences) if confidences else None
        )
        self.db.execute(
            """UPDATE transcripts SET status='Ready',duration_seconds=?,
               word_count=?,segment_count=?,confidence=?,updated_at=?
               WHERE id=?""",
            (
                max_end,word_count,segment_count,confidence_value,
                datetime.now().isoformat(),int(transcript_id)
            )
        )
        self.build_search_index(transcript_id)
        return self.transcript(transcript_id)

    def import_file(self, path, media_asset_id=None, title=None, language="en"):
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        transcript_id = self.create_transcript(
            title or path.stem,
            media_asset_id=media_asset_id,
            language=language,
            engine="import",
            source_path=str(path),
            status="Importing"
        )
        suffix = path.suffix.lower()
        if suffix == ".srt":
            segments = self._parse_srt(path.read_text(encoding="utf-8-sig"))
        elif suffix == ".vtt":
            segments = self._parse_vtt(path.read_text(encoding="utf-8-sig"))
        elif suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                segments = payload.get("segments") or payload.get("transcript") or []
            elif isinstance(payload, list):
                segments = payload
            else:
                raise ValueError("Unsupported JSON transcript structure.")
        elif suffix in {".txt",".md"}:
            segments = self._text_to_segments(
                path.read_text(encoding="utf-8-sig")
            )
        else:
            raise ValueError("Supported transcript formats: SRT, VTT, JSON, TXT.")
        return self.add_segments(transcript_id,segments)

    def _parse_timestamp(self, value):
        clean = value.strip().replace(",",".")
        parts = clean.split(":")
        if len(parts) == 3:
            h,m,s = parts
        elif len(parts) == 2:
            h = 0
            m,s = parts
        else:
            return float(parts[0])
        return float(h)*3600 + float(m)*60 + float(s)

    def _parse_srt(self, text):
        blocks = re.split(r"\n\s*\n", text.strip())
        segments = []
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            time_index = next((i for i,line in enumerate(lines) if "-->" in line),None)
            if time_index is None:
                continue
            left,right = [part.strip() for part in lines[time_index].split("-->",1)]
            content = " ".join(lines[time_index+1:]).strip()
            if content:
                segments.append({
                    "start":self._parse_timestamp(left),
                    "end":self._parse_timestamp(right.split()[0]),
                    "text":re.sub(r"<[^>]+>","",content)
                })
        return segments

    def _parse_vtt(self, text):
        text = re.sub(r"^\ufeff?WEBVTT.*?\n","",text,flags=re.S)
        return self._parse_srt(text)

    def _text_to_segments(self, text, seconds_per_paragraph=20):
        paragraphs = [
            " ".join(chunk.split())
            for chunk in re.split(r"\n\s*\n",text)
            if chunk.strip()
        ]
        return [
            {
                "start":index*seconds_per_paragraph,
                "end":(index+1)*seconds_per_paragraph,
                "text":paragraph
            }
            for index,paragraph in enumerate(paragraphs)
        ]

    def export_srt(self, transcript_id, output_path):
        segments = self.segments(transcript_id)
        path = Path(output_path)
        lines = []
        for row_index,(_,row) in enumerate(segments.iterrows(),start=1):
            lines.extend([
                str(row_index),
                f'{self._srt_time(row["start_seconds"])} --> {self._srt_time(row["end_seconds"])}',
                str(row["text"]),
                ""
            ])
        path.write_text("\n".join(lines),encoding="utf-8")
        return path

    def export_json(self, transcript_id, output_path):
        transcript = self.transcript(transcript_id)
        segments = self.segments(transcript_id).to_dict("records")
        payload = {"transcript":transcript,"segments":segments}
        path = Path(output_path)
        path.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")
        return path

    def _srt_time(self, seconds):
        total_ms = int(round(float(seconds)*1000))
        h,rem = divmod(total_ms,3600000)
        m,rem = divmod(rem,60000)
        s,ms = divmod(rem,1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def build_search_index(self, transcript_id=None):
        if transcript_id is None:
            self.db.execute("DELETE FROM transcript_fts")
            ids = self.transcripts()["id"].tolist()
            for tid in ids:
                self._index_one(int(tid))
            return len(ids)
        self._index_one(int(transcript_id))
        return 1

    def _index_one(self, transcript_id):
        transcript = self.transcript(transcript_id)
        try:
            self.db.execute(
                "DELETE FROM transcript_fts WHERE transcript_id=?",
                (int(transcript_id),)
            )
        except Exception:
            pass
        for _,row in self.segments(transcript_id).iterrows():
            self.db.execute(
                """INSERT INTO transcript_fts(
                    text,transcript_id,segment_id,start_seconds,end_seconds,title
                ) VALUES(?,?,?,?,?,?)""",
                (
                    row["text"],int(transcript_id),int(row["id"]),
                    float(row["start_seconds"]),float(row["end_seconds"]),
                    transcript["title"]
                )
            )

    def search(self, query, transcript_id=None, limit=200):
        query = str(query).strip()
        if not query:
            return self.db.frame(
                """SELECT s.id AS segment_id,s.transcript_id,t.title,
                   s.start_seconds,s.end_seconds,s.text,s.speaker,s.confidence
                   FROM transcript_segments s
                   JOIN transcripts t ON t.id=s.transcript_id
                   ORDER BY t.updated_at DESC,s.start_seconds LIMIT ?""",
                (int(limit),)
            )

        params: list[Any] = []
        # Try FTS MATCH first.
        try:
            sql = """SELECT segment_id,transcript_id,title,start_seconds,
                     end_seconds,text,bm25(transcript_fts) AS rank
                     FROM transcript_fts WHERE transcript_fts MATCH ?"""
            params.append(query)
            if transcript_id:
                sql += " AND transcript_id=?"
                params.append(int(transcript_id))
            sql += " ORDER BY rank LIMIT ?"
            params.append(int(limit))
            results = self.db.frame(sql,params)
        except Exception:
            sql = """SELECT segment_id,transcript_id,title,start_seconds,
                     end_seconds,text,0 AS rank
                     FROM transcript_fts WHERE lower(text) LIKE ?"""
            params = [f"%{query.lower()}%"]
            if transcript_id:
                sql += " AND transcript_id=?"
                params.append(int(transcript_id))
            sql += " ORDER BY transcript_id,start_seconds LIMIT ?"
            params.append(int(limit))
            results = self.db.frame(sql,params)

        self.db.execute(
            """INSERT INTO transcript_search_log(query,result_count,searched_at)
               VALUES(?,?,?)""",
            (query,len(results),datetime.now().isoformat())
        )
        return results

    def build_chapters(
        self, transcript_id, target_minutes=10,
        minimum_minutes=3, maximum_minutes=30
    ):
        segments = self.segments(transcript_id)
        if segments.empty:
            return self.chapters(transcript_id)
        target = max(60.0, float(target_minutes) * 60.0)
        minimum = max(30.0, min(float(minimum_minutes) * 60.0, target))
        maximum = max(target, float(maximum_minutes) * 60.0)
        manual = self.db.frame(
            """SELECT * FROM transcript_chapters
               WHERE transcript_id=? AND source='manual'
               ORDER BY start_seconds,id""",
            (int(transcript_id),),
        )
        manual_ranges = [
            (float(row["start_seconds"]), float(row["end_seconds"]))
            for _, row in manual.iterrows()
        ]
        groups = self._semantic_chapter_groups(
            segments,
            manual_ranges,
            target_seconds=target,
            minimum_seconds=minimum,
            maximum_seconds=maximum,
        )
        documents = [
            Counter(self._chapter_terms(self._chapter_group_text(group)))
            for group in groups
        ]
        document_frequency = Counter(
            term for document in documents for term in document
        )
        metadata = [
            self._semantic_chapter_metadata(
                group,
                document_frequency=document_frequency,
                document_count=max(1, len(documents)),
                fallback_index=index,
            )
            for index, group in enumerate(groups)
        ]

        now = datetime.now().isoformat()
        try:
            self.db.execute(
                """UPDATE transcript_chapters SET chapter_index=(-100000-id)
                   WHERE transcript_id=? AND source='manual'""",
                (int(transcript_id),),
            )
            self.db.execute(
                """DELETE FROM transcript_chapters
                   WHERE transcript_id=? AND COALESCE(source,'')<>'manual'""",
                (int(transcript_id),),
            )
            for index, (group, details) in enumerate(zip(groups, metadata)):
                self.db.execute(
                    """INSERT INTO transcript_chapters(
                        transcript_id,chapter_index,start_seconds,end_seconds,
                        title,summary,keywords_json,confidence,source,
                        created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        int(transcript_id), 100000 + index,
                        float(group[0]["start_seconds"]),
                        float(group[-1]["end_seconds"]),
                        details["title"], details["summary"],
                        json.dumps(details["keywords"]), details["confidence"],
                        "semantic-v2", now, now,
                    ),
                )
        finally:
            self._reindex_chapters_safely(int(transcript_id))
        return self.chapters(transcript_id)

    def _semantic_chapter_groups(
        self, segments, manual_ranges, *, target_seconds,
        minimum_seconds, maximum_seconds
    ):
        rows = [
            row.to_dict()
            for _, row in segments.sort_values(
                ["start_seconds", "end_seconds", "segment_index"]
            ).iterrows()
        ]
        prepared = [
            {**row, "_terms": self._chapter_terms(str(row.get("text") or ""))}
            for row in rows
        ]
        zoned_groups = []
        current = []
        zone = 0

        def flush():
            nonlocal current
            if current:
                zoned_groups.append((zone, current))
                current = []

        for index, row in enumerate(prepared):
            start = float(row["start_seconds"])
            end = float(row["end_seconds"])
            if any(
                start < manual_end and end > manual_start
                for manual_start, manual_end in manual_ranges
            ):
                flush()
                zone += 1
                continue
            if current and self._is_semantic_chapter_boundary(
                current,
                row,
                prepared[index:index + 3],
                target_seconds=target_seconds,
                minimum_seconds=minimum_seconds,
                maximum_seconds=maximum_seconds,
            ):
                flush()
            current.append(row)
        flush()

        merged = []
        for current_zone, group in zoned_groups:
            duration = (
                float(group[-1]["end_seconds"])
                - float(group[0]["start_seconds"])
            )
            if (
                merged
                and merged[-1][0] == current_zone
                and duration < minimum_seconds
            ):
                merged[-1][1].extend(group)
            else:
                merged.append((current_zone, group))
        return [group for _, group in merged]

    def _is_semantic_chapter_boundary(
        self, current, incoming, incoming_context, *, target_seconds,
        minimum_seconds, maximum_seconds
    ):
        start = float(current[0]["start_seconds"])
        duration = float(current[-1]["end_seconds"]) - start
        gap = max(
            0.0,
            float(incoming["start_seconds"])
            - float(current[-1]["end_seconds"]),
        )
        if duration >= maximum_seconds:
            return True
        if duration < minimum_seconds:
            return False
        recent = Counter(
            term for row in current[-6:] for term in row.get("_terms", [])
        )
        upcoming = Counter(
            term for row in incoming_context for term in row.get("_terms", [])
        )
        similarity = self._counter_cosine(recent, upcoming)
        enough_terms = sum(recent.values()) >= 6 and sum(upcoming.values()) >= 4
        topic_shift = enough_terms and similarity < 0.16
        transition = bool(
            _CHAPTER_TRANSITION_PATTERN.search(str(incoming.get("text") or ""))
        )
        long_gap = gap >= max(20.0, min(90.0, target_seconds * 0.12))
        return bool(
            long_gap
            or transition
            or (
                duration >= target_seconds * 0.70
                and topic_shift
                and gap >= 4.0
            )
            or (duration >= target_seconds and topic_shift)
            or duration >= target_seconds * 1.25
        )

    @staticmethod
    def _counter_cosine(first, second):
        if not first or not second:
            return 0.0
        shared = set(first) & set(second)
        numerator = sum(first[token] * second[token] for token in shared)
        left = math.sqrt(sum(value * value for value in first.values()))
        right = math.sqrt(sum(value * value for value in second.values()))
        return numerator / (left * right) if left and right else 0.0

    @staticmethod
    def _chapter_terms(text):
        terms = []
        previous = None
        for raw in re.findall(
            r"\b[A-Za-z][A-Za-z'-]{2,}\b", str(text).lower()
        ):
            token = raw.replace("'", "")
            if token == previous:
                continue
            previous = token
            if token in _CHAPTER_STOP_WORDS or token in _CHAPTER_FILLER_WORDS:
                continue
            terms.append(token)
        return terms

    @staticmethod
    def _chapter_group_text(group):
        return " ".join(
            str(row.get("text") or "").strip() for row in group
        ).strip()

    def _semantic_chapter_metadata(
        self, group, *, document_frequency, document_count, fallback_index
    ):
        counts = Counter(
            term for row in group for term in row.get("_terms", [])
        )
        term_scores = {}
        for term, count in counts.items():
            inverse_frequency = math.log(
                (1.0 + document_count)
                / (1.0 + document_frequency.get(term, 0))
            ) + 1.0
            repetition_safe_tf = 1.0 + math.log(min(3, count))
            action_penalty = 0.78 if term in _CHAPTER_ACTION_WORDS else 1.0
            term_scores[term] = (
                repetition_safe_tf * inverse_frequency * action_penalty
            )
        ranked_terms = sorted(
            term_scores,
            key=lambda term: (
                term in _CHAPTER_GENERIC_CONTENT,
                -term_scores[term],
                term,
            ),
        )
        keywords = [
            term for term in ranked_terms
            if term not in _CHAPTER_GENERIC_CONTENT
        ][:8]
        representatives = self._representative_chapter_segments(
            group, term_scores
        )
        title = self._semantic_chapter_title(
            group, representatives, keywords, term_scores, fallback_index
        )
        summary = self._representative_chapter_summary(representatives, group)
        confidences = []
        for row in group:
            try:
                value = float(row.get("confidence"))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                confidences.append(max(0.0, min(1.0, value)))
        transcript_confidence = (
            sum(confidences) / len(confidences) if confidences else 0.5
        )
        semantic_support = min(
            1.0,
            sum(term_scores.get(term, 0.0) for term in keywords[:3]) / 8.0,
        )
        confidence = round(
            min(
                0.95,
                transcript_confidence * 0.65
                + semantic_support * 0.20
                + 0.15,
            ),
            2,
        )
        return {
            "title": title,
            "summary": summary,
            "keywords": keywords[:6],
            "confidence": confidence,
        }

    def _representative_chapter_segments(self, group, term_scores):
        scored = []
        for index, row in enumerate(group):
            text = self._clean_spoken_text(str(row.get("text") or ""))
            terms = list(dict.fromkeys(row.get("_terms", [])))
            specific_terms = [
                term for term in terms
                if term not in _CHAPTER_GENERIC_CONTENT
                and term not in _CHAPTER_ACTION_WORDS
            ]
            if not text or not specific_terms:
                continue
            score = sum(
                term_scores.get(term, 0.0) for term in terms
            ) / math.sqrt(len(terms))
            if any(term in _CHAPTER_ACTION_WORDS for term in terms):
                score += 0.8
            if "?" in text or "!" in text:
                score += 0.25
            scored.append((score, index, text, row))
        selected = []
        seen = set()
        for _, index, text, row in sorted(
            scored, key=lambda item: (-item[0], item[1])
        ):
            signature = " ".join(self._chapter_terms(text)[:8])
            if not signature or signature in seen:
                continue
            seen.add(signature)
            selected.append((index, text, row))
            if len(selected) >= 3:
                break
        return sorted(selected, key=lambda item: item[0])

    def _semantic_chapter_title(
        self, group, representatives, keywords, term_scores, fallback_index
    ):
        ranked_representatives = sorted(
            representatives,
            key=lambda item: -sum(
                term_scores.get(term, 0.0)
                for term in set(item[2].get("_terms", []))
            ),
        )
        for _, text, _ in ranked_representatives:
            candidate = self._event_chapter_title(text, term_scores)
            if candidate and not self._is_generic_chapter_title(candidate):
                return candidate
        phrase = self._best_chapter_phrase(group, term_scores)
        if phrase and not self._is_generic_chapter_title(phrase):
            return phrase
        specific = [
            term for term in keywords if term not in _CHAPTER_ACTION_WORDS
        ]
        if specific:
            candidate = " & ".join(term.title() for term in specific[:2])
            if not self._is_generic_chapter_title(candidate):
                return candidate
        return f"Chapter {fallback_index + 1} — Needs Review"

    def _event_chapter_title(self, text, term_scores):
        clean = self._clean_spoken_text(text)
        if re.search(
            r"\bout (?:of )?(?:ammo|ammunition)\b", clean, re.IGNORECASE
        ):
            noun = (
                "Ammunition"
                if re.search(r"\bammunition\b", clean, re.IGNORECASE)
                else "Ammo"
            )
            return f"Running Out of {noun}"
        raw_words = re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", clean)
        lowered = [word.lower().replace("'", "") for word in raw_words]
        for action_index, action in enumerate(lowered):
            label = _CHAPTER_ACTION_ROOTS.get(action)
            if not label:
                continue
            nearby = []
            for offset in range(
                max(0, action_index - 4),
                min(len(lowered), action_index + 9),
            ):
                token = lowered[offset]
                if (
                    token in _CHAPTER_STOP_WORDS
                    or token in _CHAPTER_FILLER_WORDS
                    or token in _CHAPTER_GENERIC_CONTENT
                    or token in _CHAPTER_ACTION_WORDS
                    or len(token) < 3
                ):
                    continue
                nearby.append(
                    (term_scores.get(token, 0.0), offset, raw_words[offset])
                )
            if not nearby:
                continue
            ordered_nearby = sorted(nearby, key=lambda item: item[1])
            before_action = [
                item for item in ordered_nearby if item[1] < action_index
            ]
            after_action = [
                item for item in ordered_nearby if item[1] > action_index
            ]
            if action in {"attack", "attacked"} and before_action:
                attacker = before_action[-1][2].title()
                target_words = [item[2].title() for item in after_action[:2]]
                if target_words:
                    return f"{attacker} Attack on {' '.join(target_words)}"
                return f"{attacker} Attack"
            if action in {
                "build", "built", "discover", "discovered", "find", "found",
                "loot", "looted", "looting", "plan", "planned", "planning",
            } and after_action:
                subject_words = [item[2].title() for item in after_action[:2]]
                subject = " ".join(subject_words)
                if label == "Finding" and not subject_words[-1].lower().endswith("s"):
                    subject = f"the {subject}"
                return f"{label} {subject}"
            nearby.sort(
                key=lambda item: (
                    -item[0], abs(item[1] - action_index), item[1]
                )
            )
            best_score = nearby[0][0]
            objects = [(nearby[0][1], nearby[0][2])]
            for score, offset, word in nearby[1:]:
                if (
                    score >= best_score * 0.88
                    and word.lower() != objects[0][1].lower()
                ):
                    objects.append((offset, word))
                    break
            ordered_objects = sorted(objects)
            if (
                len(ordered_objects) == 2
                and ordered_objects[1][0] == ordered_objects[0][0] + 1
            ):
                subject = " ".join(
                    word.title() for _, word in ordered_objects
                )
            else:
                subject = " and ".join(
                    word.title() for _, word in ordered_objects
                )
            return f"{label} {subject}"
        if ("?" in clean or "!" in clean) and 4 <= len(raw_words) <= 11:
            quote = clean.strip(" .!?")
            if not self._is_generic_chapter_title(quote):
                return quote.title()
        return None

    def _best_chapter_phrase(self, group, term_scores):
        phrases = Counter()
        displays = {}
        for row in group:
            text = self._clean_spoken_text(str(row.get("text") or ""))
            raw = re.findall(r"\b[A-Za-z][A-Za-z'-]{2,}\b", text)
            content = [
                (word.lower().replace("'", ""), word)
                for word in raw
                if word.lower().replace("'", "") not in _CHAPTER_STOP_WORDS
                and word.lower().replace("'", "") not in _CHAPTER_FILLER_WORDS
                and word.lower().replace("'", "") not in _CHAPTER_GENERIC_CONTENT
                and word.lower().replace("'", "") not in _CHAPTER_ACTION_WORDS
            ]
            for offset in range(max(0, len(content) - 1)):
                key = (content[offset][0], content[offset + 1][0])
                if key[0] == key[1]:
                    continue
                phrases[key] += 1
                displays.setdefault(
                    key, (content[offset][1], content[offset + 1][1])
                )
        if not phrases:
            return None
        best = max(
            phrases,
            key=lambda phrase: (
                sum(term_scores.get(term, 0.0) for term in phrase)
                + math.log1p(min(3, phrases[phrase])),
                phrase,
            ),
        )
        return " ".join(word.title() for word in displays[best])

    def _is_generic_chapter_title(self, title):
        words = [
            word.lower().replace("'", "")
            for word in re.findall(r"[A-Za-z']+", title)
        ]
        if not words:
            return True
        content = [
            word for word in words
            if word not in _CHAPTER_STOP_WORDS
            and word not in _CHAPTER_FILLER_WORDS
        ]
        if not content or all(
            word in _CHAPTER_GENERIC_CONTENT for word in content
        ):
            return True
        repeated_ratio = 1.0 - len(set(words)) / max(1, len(words))
        if repeated_ratio >= 0.34:
            return True
        generic_phrases = {
            "hey hey hey", "you guys", "its the", "im not sure",
            "wait wait wait", "run run run", "said the stream", "not need",
            "its not bad",
        }
        return " ".join(words) in generic_phrases

    @staticmethod
    def _clean_spoken_text(text):
        clean = re.sub(r"\s+", " ", str(text)).strip()
        clean = re.sub(
            r"\b([A-Za-z][A-Za-z'-]*)\b(?:[\s,]+\1\b)+",
            r"\1",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(
            r"^(?:(?:hey|hello|hi|hmm|huh|meh|oh|okay|uh|um|well|yeah|yep)"
            r"\b[,.!?]?\s*)+",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        return clean.strip()

    def _representative_chapter_summary(
        self, representatives, group, max_chars=320
    ):
        texts = [text for _, text, _ in representatives]
        if not texts:
            texts = []
            for row in group:
                clean = self._clean_spoken_text(str(row.get("text") or ""))
                specific = [
                    term for term in self._chapter_terms(clean)
                    if term not in _CHAPTER_GENERIC_CONTENT
                    and term not in _CHAPTER_ACTION_WORDS
                ]
                if clean and specific:
                    texts.append(clean)
                if len(texts) >= 2:
                    break
        if not texts:
            return "Insufficient semantic context; review this chapter manually."
        summary = " ".join(
            text if text.endswith((".", "!", "?")) else f"{text}."
            for text in texts
        )
        summary = re.sub(r"\s+", " ", summary).strip()
        if len(summary) <= max_chars:
            return summary
        cut = summary[:max_chars].rsplit(" ", 1)[0]
        return cut.rstrip(" ,.;:") + "…"

    def _reindex_chapters_safely(self, transcript_id):
        self.db.execute(
            """UPDATE transcript_chapters SET chapter_index=(300000+id)
               WHERE transcript_id=?""",
            (int(transcript_id),),
        )
        rows = self.db.frame(
            """SELECT id FROM transcript_chapters WHERE transcript_id=?
               ORDER BY start_seconds,end_seconds,id""",
            (int(transcript_id),),
        )
        for index, row in rows.iterrows():
            self.db.execute(
                "UPDATE transcript_chapters SET chapter_index=? WHERE id=?",
                (int(index), int(row["id"])),
            )

    def chapters(self, transcript_id):
        return self.db.frame(
            """SELECT * FROM transcript_chapters
               WHERE transcript_id=? ORDER BY chapter_index""",
            (int(transcript_id),)
        )

    def queue_transcription(
        self, media_asset_id, model_name="base",
        language="en", priority=100, settings=None
    ):
        if not self.video_processing:
            raise RuntimeError("Video processing service is unavailable.")
        asset = self.video_processing.asset(media_asset_id)
        audio = self.video_processing.artifacts(media_asset_id)
        audio = audio[audio["artifact_type"]=="Audio"] if not audio.empty else audio
        input_path = (
            str(audio.iloc[0]["file_path"])
            if not audio.empty else asset["source_path"]
        )
        transcript_id = self.create_transcript(
            asset["display_name"],
            media_asset_id=int(media_asset_id),
            language=language,
            engine=self.engine_status().engine,
            model_name=model_name,
            source_path=input_path,
            status="Queued"
        )
        now = datetime.now().isoformat()
        job_id = int(self.db.execute(
            """INSERT INTO transcript_jobs(
                transcript_id,media_asset_id,job_type,status,priority,
                settings_json,input_path,engine,model_name,queued_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                transcript_id,int(media_asset_id),"Transcribe audio","Queued",
                int(priority),json.dumps(settings or {}),
                input_path,self.engine_status().engine,model_name,now,now
            )
        ))
        return job_id

    def jobs(self, status=None):
        sql = """SELECT j.id,j.transcript_id,j.media_asset_id,t.title,
                 j.job_type,j.status,j.priority,j.progress_percent,j.engine,
                 j.model_name,j.error_message,j.attempt_count,j.queued_at,
                 j.started_at,j.completed_at
                 FROM transcript_jobs j
                 LEFT JOIN transcripts t ON t.id=j.transcript_id"""
        params = []
        if status and status!="All":
            sql += " WHERE j.status=?"
            params.append(status)
        return self.db.frame(
            sql + """ ORDER BY CASE j.status
                     WHEN 'Running' THEN 1 WHEN 'Queued' THEN 2 ELSE 3 END,
                     j.priority,j.queued_at""",
            params
        )

    def recover_interrupted_jobs(self):
        self.db.execute(
            """UPDATE transcript_jobs SET status='Queued',
               error_message='Recovered after application interruption.',
               updated_at=? WHERE status='Running'""",
            (datetime.now().isoformat(),)
        )

    def cancel_job(self, job_id):
        event = self._cancel.setdefault(int(job_id),threading.Event())
        event.set()
        process = self._processes.get(int(job_id))
        if process and process.poll() is None:
            process.terminate()
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE transcript_jobs SET status='Cancelled',
               cancelled_at=?,updated_at=? WHERE id=?
               AND status IN('Queued','Running')""",
            (now,now,int(job_id))
        )

    def retry_job(self, job_id):
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE transcript_jobs SET status='Queued',
               progress_percent=0,error_message=NULL,started_at=NULL,
               completed_at=NULL,cancelled_at=NULL,updated_at=? WHERE id=?""",
            (now,int(job_id))
        )

    def run_next(self, progress_callback=None):
        frame = self.db.frame(
            """SELECT id FROM transcript_jobs WHERE status='Queued'
               ORDER BY priority,queued_at LIMIT 1"""
        )
        if frame.empty:
            return None
        job_id = int(frame.iloc[0]["id"])
        self.run_job(job_id,progress_callback)
        return job_id

    def run_job(self, job_id, progress_callback=None):
        frame = self.db.frame(
            "SELECT * FROM transcript_jobs WHERE id=?",(int(job_id),)
        )
        if frame.empty:
            raise KeyError(job_id)
        job = frame.iloc[0].to_dict()
        status = self.engine_status()
        if not status.available:
            self._fail_job(job_id,status.message)
            raise RuntimeError(status.message)

        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE transcript_jobs SET status='Running',started_at=?,
               attempt_count=attempt_count+1,error_message=NULL,updated_at=?
               WHERE id=?""",(now,now,int(job_id))
        )
        cancel = threading.Event()
        self._cancel[int(job_id)] = cancel
        try:
            segments = self._run_engine(job,status,cancel,progress_callback)
            if cancel.is_set():
                return
            self.add_segments(int(job["transcript_id"]),segments)
            now = datetime.now().isoformat()
            self.db.execute(
                """UPDATE transcript_jobs SET status='Completed',
                   progress_percent=100,completed_at=?,updated_at=? WHERE id=?""",
                (now,now,int(job_id))
            )
            if self.notifications:
                self.notifications.create(
                    "System","Success","Transcription complete",
                    f'{self.transcript(job["transcript_id"])["title"]} is searchable.',
                    "transcript",job["transcript_id"]
                )
        except Exception as exc:
            if cancel.is_set():
                self.cancel_job(job_id)
            else:
                self._fail_job(job_id,str(exc))
            raise
        finally:
            self._cancel.pop(int(job_id),None)
            self._processes.pop(int(job_id),None)

    def _run_engine(self, job, status, cancel, progress_callback):
        output_dir = Path(self.db.path).parent/"transcripts"/f'job_{job["id"]}'
        output_dir.mkdir(parents=True,exist_ok=True)
        input_path = str(job["input_path"])
        model = str(job.get("model_name") or "base")
        transcript = self.transcript(job["transcript_id"])
        language = transcript.get("language") or "en"

        if status.engine == "openai-whisper":
            command = [
                status.command,input_path,
                "--model",model,
                "--language",language,
                "--output_format","json",
                "--output_dir",str(output_dir),
                "--word_timestamps","True",
                "--verbose","False",
            ]
            process = subprocess.Popen(
                command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,bufsize=1
            )
            self._processes[int(job["id"])] = process
            for line in process.stdout or []:
                if cancel.is_set():
                    process.terminate()
                    break
                match = re.search(r"(\d{1,3})%",line)
                if match:
                    percent = min(99,float(match.group(1)))
                    self.db.execute(
                        """UPDATE transcript_jobs SET progress_percent=?,
                           updated_at=? WHERE id=?""",
                        (percent,datetime.now().isoformat(),int(job["id"]))
                    )
                    if progress_callback:
                        progress_callback(int(job["id"]),percent,line.strip())
            return_code = process.wait()
            if cancel.is_set():
                return []
            if return_code:
                raise RuntimeError(f"Whisper exited with code {return_code}.")
            output_file = output_dir/(Path(input_path).stem+".json")
            payload = json.loads(output_file.read_text(encoding="utf-8"))
            return payload.get("segments") or []

        # The exact command interface differs among faster-whisper and
        # whisper.cpp distributions. Users may configure a wrapper command
        # that writes JSON to this requested location.
        output_file = output_dir/"transcript.json"
        command = [
            status.command,
            "--input",input_path,
            "--model",model,
            "--language",language,
            "--output",str(output_file)
        ]
        process = subprocess.Popen(
            command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,bufsize=1
        )
        self._processes[int(job["id"])] = process
        for line in process.stdout or []:
            if cancel.is_set():
                process.terminate()
                break
            match = re.search(r"(\d{1,3}(?:\.\d+)?)%",line)
            if match:
                percent = min(99,float(match.group(1)))
                self.db.execute(
                    """UPDATE transcript_jobs SET progress_percent=?,
                       updated_at=? WHERE id=?""",
                    (percent,datetime.now().isoformat(),int(job["id"]))
                )
                if progress_callback:
                    progress_callback(int(job["id"]),percent,line.strip())
        return_code = process.wait()
        if cancel.is_set():
            return []
        if return_code:
            raise RuntimeError(
                f"{status.engine} wrapper exited with code {return_code}."
            )
        payload = json.loads(output_file.read_text(encoding="utf-8"))
        return payload.get("segments") if isinstance(payload,dict) else payload

    def _fail_job(self, job_id, message):
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE transcript_jobs SET status='Failed',
               error_message=?,updated_at=? WHERE id=?""",
            (message,now,int(job_id))
        )
        if self.notifications:
            self.notifications.create(
                "System","Error","Transcription failed",message,
                "transcript_job",job_id
            )
