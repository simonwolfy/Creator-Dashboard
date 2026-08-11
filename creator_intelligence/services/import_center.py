from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
import csv
import hashlib
import json
import shutil
import sqlite3
import uuid

import pandas as pd

@dataclass
class DetectionResult:
    export_type: str
    platform: str
    confidence: float
    destination_table: str | None
    header_map: dict[str, str]
    warnings: list[str]

class ImportCenterService:
    DETECTORS = {
        "twitch_game_history": {
            "platform": "Twitch",
            "required_any": [
                {
                    "date",
                    "canonical game sequence",
                    "mapping confidence",
                    "mapping source",
                },
                {
                    "date",
                    "starting game",
                    "ending game",
                    "games played",
                },
            ],
            "destination": "historical_stream_days",
            "aliases": {
                "stream day id": "stream_day_id",
                "date": "date",
                "minutes streamed": "minutes_streamed",
                "minutes watched": "minutes_watched",
                "average viewers": "average_viewers",
                "peak viewers": "peak_viewers",
                "maximum viewers": "peak_viewers",
                "unique viewers": "unique_viewers",
                "follows": "follows",
                "chatters": "chatters",
                "live views": "live_views",
                "raid viewers %": "raid_viewers_pct",
                "chat messages": "chat_messages",
                "clips created": "clips_created",
                "clip views": "clip_views",
                "new engaged viewers": "new_engaged_viewers",
                "returning engaged viewers": "returning_engaged_viewers",
                "prime subs": "prime_subs",
                "total paid subs": "total_paid_subs",
                "total gifted subs": "total_gifted_subs",
                "canonical game sequence": "canonical_game_sequence",
                "games played": "canonical_game_sequence",
                "first observed game": "first_observed_game",
                "starting game": "first_observed_game",
                "last observed game": "last_observed_game",
                "ending game": "last_observed_game",
                "game count": "game_count",
                "observed category changes": "observed_category_changes",
                "category changes": "observed_category_changes",
                "mapping status": "mapping_status",
                "mapping confidence": "mapping_confidence",
                "confidence": "mapping_confidence",
                "evidence coverage": "evidence_coverage",
                "mapping source": "mapping_source",
                "source": "mapping_source",
                "original game sequence": "original_game_sequence",
                "original mapping status": "original_mapping_status",
                "original confidence": "original_confidence",
                "data quality flags": "quality_flags",
                "quality flags": "quality_flags",
            },
        },
        "twitch_game_events": {
            "platform": "Twitch",
            "required_any": [
                {"event timestamp", "event type", "game"},
                {"date", "time", "event type", "game"},
            ],
            "destination": "historical_game_events",
            "aliases": {
                "date": "stream_day_date",
                "event timestamp": "event_ts",
                "event type": "event_type",
                "game": "game",
                "changed by": "changed_by",
                "parse method": "parse_method",
                "next distinct game timestamp": "next_distinct_game_ts",
                "source line": "source_line",
                "raw source text": "raw_source_text",
                "matches stream day": "matches_stream_day",
            },
        },
        "twitch_daily": {
            "platform": "Twitch",
            "required_any": [
                {"date", "average viewers", "maximum viewers"},
                {"date", "minutes streamed", "minutes watched"},
                {"date", "follows", "unique viewers"},
            ],
            "destination": "twitch_daily",
            "aliases": {
                "date": "date",
                "average viewers": "average_viewers",
                "avg viewers": "average_viewers",
                "maximum viewers": "max_viewers",
                "max viewers": "max_viewers",
                "unique viewers": "unique_viewers",
                "follows": "follows",
                "minutes streamed": "minutes_streamed",
                "minutes watched": "minutes_watched",
                "chat messages": "chat_messages",
                "total revenue": "total_revenue",
                "revenue": "total_revenue",
            },
        },
        "youtube_content": {
            "platform": "YouTube",
            "required_any": [
                {"content id", "video title", "views"},
                {"video id", "title", "views"},
                {"content id", "title", "watch time (hours)"},
            ],
            "destination": "youtube_content",
            "aliases": {
                "content id": "content_id",
                "video id": "content_id",
                "title": "title",
                "video title": "title",
                "description": "description",
                "video description": "description",
                "publish time": "publish_time",
                "published at": "publish_time",
                "duration": "duration_seconds",
                "duration seconds": "duration_seconds",
                "views": "views",
                "engaged views": "engaged_views",
                "watch time (hours)": "watch_time_hours",
                "watch time hours": "watch_time_hours",
                "subscribers gained": "subscribers_gained",
                "subscribers lost": "subscribers_lost",
                "likes": "likes",
                "comments": "comments",
                "shares": "shares",
                "impressions": "impressions",
                "impressions click-through rate (%)": "ctr",
                "ctr": "ctr",
            },
        },
        "twitch_raids": {
            "platform": "Twitch",
            "required_any": [
                {"date", "raider", "viewers"},
                {"timestamp", "from channel", "viewer count"},
            ],
            "destination": "raid_events",
            "aliases": {
                "date": "occurred_at",
                "timestamp": "occurred_at",
                "raider": "source_channel",
                "from channel": "source_channel",
                "viewers": "viewer_count",
                "viewer count": "viewer_count",
                "notes": "notes",
            },
        },
    }

    def __init__(self, db, registry=None):
        self.db = db
        self.registry = registry
        self.data_dir = Path(getattr(db, "path", "data/creator_intelligence.db")).resolve().parent
        self.backup_dir = self.data_dir / "backups"
        self.archive_dir = self.data_dir / "import_archive"
        self.staging_dir = self.data_dir / "import_staging"
        for directory in (self.backup_dir, self.archive_dir, self.staging_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS import_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                archived_path TEXT,
                file_name TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                importer_id TEXT,
                platform TEXT,
                detected_type TEXT,
                destination_table TEXT,
                status TEXT NOT NULL,
                rows_detected INTEGER DEFAULT 0,
                rows_staged INTEGER DEFAULT 0,
                rows_inserted INTEGER DEFAULT 0,
                rows_updated INTEGER DEFAULT 0,
                rows_skipped INTEGER DEFAULT 0,
                rows_unchanged INTEGER DEFAULT 0,
                rows_review INTEGER DEFAULT 0,
                rows_rejected INTEGER DEFAULT 0,
                warning_json TEXT DEFAULT '[]',
                error_message TEXT,
                backup_path TEXT,
                rollback_available INTEGER DEFAULT 0,
                rolled_back_at TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            )""",
            """CREATE INDEX IF NOT EXISTS idx_import_jobs_hash_success
               ON import_jobs(file_hash)
               WHERE status IN ('Completed','Completed with warnings')""",
            """CREATE TABLE IF NOT EXISTS import_staging_rows(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                row_number INTEGER NOT NULL,
                raw_json TEXT NOT NULL,
                normalized_json TEXT,
                row_key TEXT,
                disposition TEXT NOT NULL,
                warning_json TEXT DEFAULT '[]',
                error_json TEXT DEFAULT '[]'
            )""",
            """CREATE INDEX IF NOT EXISTS idx_staging_batch
               ON import_staging_rows(batch_id,row_number)""",
            """CREATE TABLE IF NOT EXISTS import_change_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                destination_table TEXT NOT NULL,
                operation TEXT NOT NULL,
                record_key TEXT NOT NULL,
                before_json TEXT,
                after_json TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_change_batch
               ON import_change_log(batch_id)""",
            """CREATE TABLE IF NOT EXISTS import_watch_folders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                enabled INTEGER DEFAULT 1,
                recursive INTEGER DEFAULT 1,
                archive_after_import INTEGER DEFAULT 1,
                last_scanned_at TEXT,
                last_result_json TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS raid_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                source_channel TEXT NOT NULL,
                viewer_count INTEGER DEFAULT 0,
                notes TEXT,
                import_batch_id TEXT,
                UNIQUE(occurred_at,source_channel,viewer_count)
            )""",
        ]
        for statement in statements:
            self.db.execute(statement)
        import_job_columns = {
            str(row["name"])
            for _, row in self.db.frame("PRAGMA table_info(import_jobs)").iterrows()
        }
        for name in ("rows_unchanged", "rows_review"):
            if name not in import_job_columns:
                self.db.execute(
                    f"ALTER TABLE import_jobs ADD COLUMN {name} INTEGER DEFAULT 0"
                )
        # Older workspaces used a unique successful-file hash index. Historical
        # imports intentionally allow re-import so idempotence can be audited.
        self.db.execute("DROP INDEX IF EXISTS idx_import_jobs_hash_success")
        self.db.execute(
            """CREATE INDEX IF NOT EXISTS idx_import_jobs_hash_success
               ON import_jobs(file_hash)
               WHERE status IN ('Completed','Completed with warnings')"""
        )
        youtube_columns = {
            str(row["name"])
            for _, row in self.db.frame("PRAGMA table_info(youtube_content)").iterrows()
        }
        if youtube_columns and "description" not in youtube_columns:
            self.db.execute("ALTER TABLE youtube_content ADD COLUMN description TEXT")

    @staticmethod
    def _normalize_header(value: str) -> str:
        return " ".join(str(value).strip().lower().replace("_", " ").split())

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _row_hash(data: dict[str, Any]) -> str:
        canonical = json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _rows_equal(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
        """Compare SQL values without treating NULL/NaN or 1/1.0 as changes."""
        for key, incoming_value in incoming.items():
            existing_value = existing.get(key)
            existing_blank = existing_value is None or (
                not isinstance(existing_value, (list, dict, str))
                and pd.isna(existing_value)
            )
            incoming_blank = incoming_value is None or (
                not isinstance(incoming_value, (list, dict, str))
                and pd.isna(incoming_value)
            )
            if existing_blank and incoming_blank:
                continue
            if existing_blank != incoming_blank:
                return False
            if isinstance(existing_value, (int, float)) and isinstance(
                incoming_value, (int, float)
            ):
                if float(existing_value) != float(incoming_value):
                    return False
            elif str(existing_value) != str(incoming_value):
                return False
        return True

    def _header_match_score(self, headers) -> float:
        header_set = {self._normalize_header(header) for header in headers}
        return max(
            (
                max(
                    len(signature & header_set) / max(len(signature), 1)
                    for signature in definition["required_any"]
                )
                for definition in self.DETECTORS.values()
            ),
            default=0.0,
        )

    def _xlsx_sheet(self, path: Path) -> str:
        workbook = pd.ExcelFile(path)
        ranked = []
        for index, sheet in enumerate(workbook.sheet_names):
            try:
                headers = list(pd.read_excel(path, sheet_name=sheet, nrows=0).columns)
            except Exception:
                continue
            ranked.append((self._header_match_score(headers), -index, sheet))
        if not ranked or max(ranked)[0] < 0.35:
            raise ValueError("No supported analytics table was found in the workbook.")
        return max(ranked)[2]

    def read_headers(self, path):
        path = Path(path)
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            return list(
                pd.read_excel(
                    path,
                    sheet_name=self._xlsx_sheet(path),
                    nrows=0,
                ).columns
            )
        if path.suffix.lower() not in {".csv", ".tsv"}:
            raise ValueError("Only CSV, TSV, XLSX, and XLSM files are supported.")
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            return next(reader, [])

    def _source_rows(self, path: Path):
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            frame = pd.read_excel(
                path,
                sheet_name=self._xlsx_sheet(path),
                dtype=object,
            )
            frame = frame.where(pd.notna(frame), None)
            return frame.to_dict(orient="records")
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle, delimiter=delimiter))

    def detect(self, path) -> DetectionResult:
        path = Path(path)
        headers = self.read_headers(path)
        normalized = {self._normalize_header(header): header for header in headers}
        header_set = set(normalized)
        candidates = []
        for export_type, definition in self.DETECTORS.items():
            best_match = 0
            for signature in definition["required_any"]:
                matched = len(signature & header_set)
                score = matched / max(len(signature), 1)
                best_match = max(best_match, score)
            aliases = definition["aliases"]
            mapped = {
                normalized[source]: destination
                for source, destination in aliases.items()
                if source in normalized
            }
            coverage = len(mapped) / max(len(headers), 1)
            confidence = min(1.0, best_match * 0.8 + coverage * 0.2)
            candidates.append((confidence, export_type, definition, mapped))
        confidence, export_type, definition, mapped = max(candidates, key=lambda item: item[0])
        warnings = []
        if confidence < 0.65:
            warnings.append("File structure was not recognized with high confidence.")
        if not mapped:
            warnings.append("No supported columns were mapped.")
        return DetectionResult(
            export_type=export_type if confidence >= 0.35 else "unknown",
            platform=definition["platform"] if confidence >= 0.35 else "Unknown",
            confidence=confidence,
            destination_table=definition["destination"] if confidence >= 0.35 else None,
            header_map=mapped,
            warnings=warnings,
        )

    def inspect_file(self, path):
        path = Path(path).resolve()
        detection = self.detect(path)
        file_hash = self._file_hash(path)
        prior = self.db.frame(
            """SELECT id,status,finished_at FROM import_jobs
               WHERE file_hash=? AND status IN ('Completed','Completed with warnings')
               ORDER BY id DESC LIMIT 1""",
            (file_hash,),
        )
        return {
            "path": str(path),
            "name": path.name,
            "hash": file_hash,
            "size_bytes": path.stat().st_size,
            "duplicate_file": not prior.empty,
            "previous_import_id": int(prior.iloc[0]["id"]) if not prior.empty else None,
            **asdict(detection),
        }

    def _coerce_value(self, column, value):
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        numeric_int = {
            "max_viewers","unique_viewers","follows","minutes_streamed",
            "minutes_watched","chat_messages","duration_seconds","views",
            "engaged_views","subscribers_gained","subscribers_lost","likes",
            "comments","shares","impressions","viewer_count","peak_viewers",
            "chatters","live_views","clips_created","clip_views",
            "new_engaged_viewers","returning_engaged_viewers","prime_subs",
            "total_paid_subs","total_gifted_subs","game_count",
            "observed_category_changes","source_line",
        }
        numeric_float = {
            "average_viewers","total_revenue","watch_time_hours","ctr",
            "raid_viewers_pct",
        }
        if column in numeric_int:
            return int(float(text.replace(",", "").replace("%", "")))
        if column in numeric_float:
            return float(text.replace(",", "").replace("$", "").replace("%", ""))
        return text

    def _record_key(self, export_type, row):
        if export_type == "twitch_daily":
            return str(row.get("date") or "")
        if export_type == "youtube_content":
            return str(row.get("content_id") or "")
        if export_type == "twitch_raids":
            return "|".join(str(row.get(k) or "") for k in (
                "occurred_at","source_channel","viewer_count"
            ))
        if export_type == "twitch_game_history":
            return str(row.get("date") or "")
        if export_type == "twitch_game_events":
            return "|".join(
                str(row.get(column) or "")
                for column in ("event_ts", "event_type", "game", "source_file")
            )
        return self._row_hash(row)

    def _existing_record(self, export_type, key):
        if not key:
            return None
        queries = {
            "twitch_daily": ("SELECT * FROM twitch_daily WHERE date=?", (key,)),
            "youtube_content": ("SELECT * FROM youtube_content WHERE content_id=?", (key,)),
            "twitch_raids": (
                """SELECT * FROM raid_events
                   WHERE occurred_at=? AND source_channel=? AND viewer_count=?""",
                tuple(key.split("|", 2)),
            ),
            "twitch_game_history": (
                "SELECT * FROM historical_stream_days WHERE date=?",
                (key,),
            ),
            "twitch_game_events": (
                """SELECT * FROM historical_game_events
                   WHERE event_ts=? AND event_type=? AND game=? AND source_file=?""",
                tuple(key.split("|", 3)),
            ),
        }
        if export_type not in queries:
            return None
        sql, params = queries[export_type]
        frame = self.db.frame(sql, params)
        if not frame.empty:
            return frame.iloc[0].to_dict()
        if export_type == "twitch_game_events":
            review = self.db.frame(
                """SELECT * FROM historical_game_event_review
                   WHERE event_ts=? AND event_type=? AND game=? AND source_file=?""",
                tuple(key.split("|", 3)),
            )
            if not review.empty:
                return review.iloc[0].to_dict()
        return None

    @staticmethod
    def _iso_date(value) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.strftime("%Y-%m-%d")

    @staticmethod
    def _sequence_games(value) -> list[str]:
        text = str(value or "").strip()
        if not text:
            return []
        for delimiter in (" → ", "→", " -> ", "->", " | ", "|", ";"):
            if delimiter in text:
                return [part.strip() for part in text.split(delimiter) if part.strip()]
        return [text]

    @staticmethod
    def _iso_timestamp(value) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return str(value).strip()
        rendered = parsed.strftime("%Y-%m-%dT%H:%M:%S")
        return rendered[:-3] if rendered.endswith(":00") else rendered

    def _prepare_historical_row(self, row: dict[str, Any], source_file: str):
        row["date"] = self._iso_date(row.get("date"))
        games = self._sequence_games(row.get("canonical_game_sequence"))
        row["canonical_game_sequence"] = " → ".join(games) or None
        row["stream_day_id"] = row.get("stream_day_id") or (
            f"day-{row['date']}" if row.get("date") else None
        )
        row["first_observed_game"] = row.get("first_observed_game") or (
            games[0] if games else None
        )
        row["last_observed_game"] = row.get("last_observed_game") or (
            games[-1] if games else None
        )
        row["game_count"] = int(row.get("game_count") or len(games))
        row["mapping_status"] = row.get("mapping_status") or (
            "Source-backed" if games else "Unresolved"
        )
        row["mapping_confidence"] = row.get("mapping_confidence") or (
            "None" if not games else None
        )
        # An explicitly blank original mapping is meaningful historical evidence:
        # it says the workbook did not know the game before later source evidence
        # established the canonical sequence. Only synthesize legacy fallbacks when
        # the source shape did not contain the original fields at all.
        if "original_game_sequence" not in row:
            row["original_game_sequence"] = row.get("canonical_game_sequence")
        if "original_mapping_status" not in row:
            row["original_mapping_status"] = row.get("mapping_status")
        if "original_confidence" not in row:
            row["original_confidence"] = row.get("mapping_confidence")
        if (
            row.get("raid_viewers_pct") is not None
            and float(row["raid_viewers_pct"]) > 100
            and "raid" not in str(row.get("quality_flags") or "").lower()
        ):
            flag = "Raid viewers percentage exceeds 100"
            row["quality_flags"] = "; ".join(
                value for value in (row.get("quality_flags"), flag) if value
            )
        row["source_file"] = source_file
        return row

    def _prepare_event_row(self, row: dict[str, Any], source_file: str):
        row["stream_day_date"] = self._iso_date(row.get("stream_day_date"))
        row["event_ts"] = self._iso_timestamp(row.get("event_ts"))
        row["next_distinct_game_ts"] = self._iso_timestamp(
            row.get("next_distinct_game_ts")
        )
        declared_match = str(row.pop("matches_stream_day", "") or "").strip().lower()
        row["_matches_stream_day"] = (
            True if declared_match in {"yes", "true", "1"}
            else False if declared_match in {"no", "false", "0"}
            else None
        )
        row["source_file"] = source_file
        return row

    def stage(self, path, allow_duplicate_file=False):
        info = self.inspect_file(path)
        historical_type = info["export_type"] in {
            "twitch_game_history",
            "twitch_game_events",
        }
        if info["duplicate_file"] and not allow_duplicate_file and not historical_type:
            raise ValueError(
                f"This exact file was already imported in job {info['previous_import_id']}."
            )
        if info["export_type"] == "unknown" or not info["destination_table"]:
            raise ValueError("The file type could not be identified.")

        batch_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        self.db.execute(
            """INSERT INTO import_jobs(
                batch_id,source_path,file_name,file_hash,importer_id,platform,
                detected_type,destination_table,status,warning_json,started_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                batch_id,info["path"],info["name"],info["hash"],
                info["export_type"],info["platform"],info["export_type"],
                info["destination_table"],"Staging",
                json.dumps(info["warnings"]),now,
            ),
        )

        path = Path(path)
        counts = {
            "rows_detected": 0, "rows_staged": 0, "rows_skipped": 0,
            "rows_unchanged": 0, "rows_review": 0, "rows_rejected": 0,
        }
        seen_keys = set()
        for row_number, raw in enumerate(self._source_rows(path), start=2):
            counts["rows_detected"] += 1
            normalized = {}
            warnings, errors = [], []
            for source, destination in info["header_map"].items():
                try:
                    normalized[destination] = self._coerce_value(
                        destination, raw.get(source)
                    )
                except Exception as exc:
                    errors.append(f"{source}: {exc}")

            if info["export_type"] == "twitch_game_history":
                normalized = self._prepare_historical_row(normalized, path.name)
                required = ("date", "stream_day_id")
            elif info["export_type"] == "twitch_game_events":
                normalized = self._prepare_event_row(normalized, path.name)
                required = ("stream_day_date", "event_ts", "event_type", "game")
            else:
                required = ()
            for field in required:
                if normalized.get(field) in {None, ""}:
                    errors.append(f"Required field is missing: {field}.")

            key = self._record_key(info["export_type"], normalized)
            if not key:
                errors.append("Required record key is missing.")

            persistent_normalized = {
                key_name: value
                for key_name, value in normalized.items()
                if not key_name.startswith("_")
            }
            existing = self._existing_record(info["export_type"], key)
            needs_review = False
            if info["export_type"] == "twitch_game_events" and not errors:
                day_exists = bool(
                    self.db.scalar(
                        "SELECT COUNT(*) FROM historical_stream_days WHERE date=?",
                        (normalized.get("stream_day_date"),),
                    )
                )
                needs_review = (
                    normalized.get("_matches_stream_day") is False or not day_exists
                )
                if needs_review:
                    warnings.append(
                        "Event has no committed matching historical stream-day and was staged for review."
                    )

            if errors:
                disposition = "Rejected"
                counts["rows_rejected"] += 1
            elif key in seen_keys:
                disposition = "Duplicate"
                counts["rows_skipped"] += 1
                counts["rows_unchanged"] += 1
            elif existing:
                comparable = {
                    field: existing.get(field) for field in persistent_normalized
                }
                if self._rows_equal(comparable, persistent_normalized):
                    disposition = "Duplicate"
                    counts["rows_skipped"] += 1
                    counts["rows_unchanged"] += 1
                else:
                    disposition = "Review" if needs_review else "Update"
                    counts["rows_staged"] += 1
                    counts["rows_review"] += int(needs_review)
            else:
                disposition = "Review" if needs_review else "Insert"
                counts["rows_staged"] += 1
                counts["rows_review"] += int(needs_review)
            seen_keys.add(key)

            self.db.execute(
                """INSERT INTO import_staging_rows(
                    batch_id,row_number,raw_json,normalized_json,row_key,
                    disposition,warning_json,error_json
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    batch_id,row_number,json.dumps(raw,default=str),
                    json.dumps(normalized,default=str),key,disposition,
                    json.dumps(warnings),json.dumps(errors),
                ),
            )

        status = "Ready" if counts["rows_staged"] else "No changes"
        self.db.execute(
            """UPDATE import_jobs SET status=?,rows_detected=?,rows_staged=?,
               rows_skipped=?,rows_unchanged=?,rows_review=?,rows_rejected=?
               WHERE batch_id=?""",
            (
                status,counts["rows_detected"],counts["rows_staged"],
                counts["rows_skipped"],counts["rows_unchanged"],
                counts["rows_review"],counts["rows_rejected"],batch_id,
            ),
        )
        return self.batch_summary(batch_id)

    def staging_rows(self, batch_id):
        return self.db.frame(
            """SELECT id,row_number,row_key,disposition,normalized_json,
               warning_json,error_json FROM import_staging_rows
               WHERE batch_id=? ORDER BY row_number""",
            (batch_id,),
        )

    def batch_summary(self, batch_id):
        job = self.db.frame(
            "SELECT * FROM import_jobs WHERE batch_id=? ORDER BY id DESC LIMIT 1",
            (batch_id,),
        )
        if job.empty:
            raise KeyError(batch_id)
        row = job.iloc[0].to_dict()
        row["warnings"] = json.loads(row.get("warning_json") or "[]")
        return row

    def _backup_database(self, batch_id):
        source = Path(self.db.path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = self.backup_dir / f"pre_import_{timestamp}_{batch_id[:8]}.db"
        source_connection = sqlite3.connect(source)
        backup_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(backup_connection)
        finally:
            backup_connection.close()
            source_connection.close()
        return destination

    def _upsert(self, export_type, row, batch_id, disposition="Insert"):
        key = self._record_key(export_type, row)
        before = self._existing_record(export_type, key)

        if export_type == "twitch_daily":
            columns = [
                "date","average_viewers","max_viewers","unique_viewers","follows",
                "minutes_streamed","minutes_watched","chat_messages","total_revenue"
            ]
            required = ["date"]
            table = "twitch_daily"
            conflict = "date"
        elif export_type == "youtube_content":
            columns = [
                "content_id","title","description","publish_time","duration_seconds","views",
                "engaged_views","watch_time_hours","subscribers_gained",
                "subscribers_lost","likes","comments","shares","impressions","ctr"
            ]
            required = ["content_id"]
            table = "youtube_content"
            conflict = "content_id"
        elif export_type == "twitch_raids":
            columns = [
                "occurred_at","source_channel","viewer_count","notes","import_batch_id"
            ]
            row["import_batch_id"] = batch_id
            required = ["occurred_at","source_channel"]
            table = "raid_events"
            conflict = "occurred_at,source_channel,viewer_count"
        elif export_type == "twitch_game_history":
            columns = [
                "date","stream_day_id","minutes_streamed","minutes_watched",
                "average_viewers","peak_viewers","unique_viewers","follows",
                "chatters","live_views","raid_viewers_pct","chat_messages",
                "clips_created","clip_views","new_engaged_viewers",
                "returning_engaged_viewers","prime_subs","total_paid_subs",
                "total_gifted_subs","canonical_game_sequence",
                "first_observed_game","last_observed_game","game_count",
                "observed_category_changes","mapping_status","mapping_confidence",
                "evidence_coverage","mapping_source","original_game_sequence",
                "original_mapping_status","original_confidence","quality_flags",
                "source_file","import_batch_id","imported_at",
            ]
            row["import_batch_id"] = batch_id
            row["imported_at"] = datetime.now().isoformat()
            required = ["date", "stream_day_id", "source_file"]
            table = "historical_stream_days"
            conflict = "date"
        elif export_type == "twitch_game_events":
            columns = [
                "stream_day_date","event_ts","event_type","game","changed_by",
                "parse_method","next_distinct_game_ts","source_line",
                "raw_source_text","source_file","import_batch_id",
            ]
            row.pop("_matches_stream_day", None)
            row["import_batch_id"] = batch_id
            required = ["event_ts", "event_type", "game", "source_file"]
            if disposition == "Review":
                table = "historical_game_event_review"
                columns.extend(["review_reason", "reviewed_at"])
                row["review_reason"] = "No committed matching historical stream-day; retained for review."
                row["reviewed_at"] = None
            else:
                table = "historical_game_events"
            conflict = "event_ts,event_type,game,source_file"
        else:
            raise ValueError(f"Unsupported export type: {export_type}")

        for required_column in required:
            if not row.get(required_column):
                raise ValueError(f"Missing required field: {required_column}")

        available = [column for column in columns if column in row]
        values = [row[column] for column in available]
        update_columns = [
            column for column in available if column not in conflict.split(",")
        ]
        placeholders = ",".join("?" for _ in available)
        conflict_clause = (
            " DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in update_columns)
            if update_columns else " DO NOTHING"
        )
        sql = f"""INSERT INTO {table}({','.join(available)})
                  VALUES({placeholders})
                  ON CONFLICT({conflict}){conflict_clause}"""
        self.db.execute(sql, values)
        after = self._existing_record(export_type, key)
        operation = "Update" if before else "Insert"
        self.db.execute(
            """INSERT INTO import_change_log(
                batch_id,destination_table,operation,record_key,
                before_json,after_json,created_at
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                batch_id,table,operation,key,
                json.dumps(before,default=str) if before else None,
                json.dumps(after,default=str) if after else None,
                datetime.now().isoformat(),
            ),
        )
        return operation

    def commit(self, batch_id, archive_source=True):
        job = self.batch_summary(batch_id)
        if job["status"] not in {"Ready","No changes"}:
            raise ValueError(f"Batch status is {job['status']}; it cannot be committed.")
        if job["status"] == "No changes":
            self.db.execute(
                "UPDATE import_jobs SET status='Completed',finished_at=? WHERE batch_id=?",
                (datetime.now().isoformat(),batch_id),
            )
            return self.batch_summary(batch_id)

        backup = self._backup_database(batch_id)
        inserted = updated = 0
        source_path = Path(job["source_path"])
        try:
            connection = sqlite3.connect(self.db.path)
            connection.execute("BEGIN IMMEDIATE")
            connection.close()

            staged = self.staging_rows(batch_id)
            for _, staged_row in staged.iterrows():
                if staged_row["disposition"] not in {"Insert","Update","Review"}:
                    continue
                normalized = json.loads(staged_row["normalized_json"])
                operation = self._upsert(
                    job["detected_type"], normalized, batch_id,
                    disposition=staged_row["disposition"],
                )
                if operation == "Insert":
                    inserted += 1
                else:
                    updated += 1

            archived_path = None
            if archive_source and source_path.exists():
                target = self.archive_dir / datetime.now().strftime("%Y-%m")
                target.mkdir(parents=True, exist_ok=True)
                archived = target / source_path.name
                if archived.exists():
                    archived = target / f"{source_path.stem}_{batch_id[:8]}{source_path.suffix}"
                shutil.copy2(source_path, archived)
                archived_path = str(archived)

            warning_count = int(job.get("rows_rejected") or 0) + int(job.get("rows_review") or 0)
            status = "Completed with warnings" if warning_count else "Completed"
            self.db.execute(
                """UPDATE import_jobs SET status=?,rows_inserted=?,rows_updated=?,
                   backup_path=?,archived_path=?,rollback_available=1,finished_at=?
                   WHERE batch_id=?""",
                (
                    status,inserted,updated,str(backup),archived_path,
                    datetime.now().isoformat(),batch_id,
                ),
            )
        except Exception as exc:
            shutil.copy2(backup, self.db.path)
            self.db.execute(
                """UPDATE import_jobs SET status='Failed',error_message=?,
                   backup_path=?,finished_at=? WHERE batch_id=?""",
                (str(exc),str(backup),datetime.now().isoformat(),batch_id),
            )
            raise
        return self.batch_summary(batch_id)

    def rollback(self, batch_id):
        job = self.batch_summary(batch_id)
        if not job.get("rollback_available"):
            raise ValueError("Rollback is not available for this import.")
        backup = Path(job.get("backup_path") or "")
        if not backup.exists():
            raise FileNotFoundError("The import backup could not be found.")
        safety = self._backup_database(f"before_rollback_{batch_id}")
        shutil.copy2(backup, self.db.path)
        self.db.execute(
            """UPDATE import_jobs SET status='Rolled back',rollback_available=0,
               rolled_back_at=?,error_message=? WHERE batch_id=?""",
            (
                datetime.now().isoformat(),
                f"Safety backup before rollback: {safety}",
                batch_id,
            ),
        )
        return self.batch_summary(batch_id)

    def cancel_staging(self, batch_id):
        self.db.execute(
            "DELETE FROM import_staging_rows WHERE batch_id=?", (batch_id,)
        )
        self.db.execute(
            """UPDATE import_jobs SET status='Cancelled',finished_at=?
               WHERE batch_id=?""",
            (datetime.now().isoformat(),batch_id),
        )

    def history(self):
        return self.db.frame(
            """SELECT id,batch_id,file_name,platform,detected_type,status,
               rows_detected,rows_staged,rows_inserted,rows_updated,
               rows_skipped,rows_unchanged,rows_review,rows_rejected,rollback_available,
               started_at,finished_at,error_message
               FROM import_jobs ORDER BY id DESC LIMIT 1000"""
        )

    def add_watch_folder(self, path, recursive=True, archive_after_import=True):
        resolved = str(Path(path).resolve())
        self.db.execute(
            """INSERT INTO import_watch_folders(
                path,enabled,recursive,archive_after_import
            ) VALUES(?,1,?,?)
            ON CONFLICT(path) DO UPDATE SET enabled=1,
                recursive=excluded.recursive,
                archive_after_import=excluded.archive_after_import""",
            (resolved,int(bool(recursive)),int(bool(archive_after_import))),
        )

    def watch_folders(self):
        return self.db.frame(
            "SELECT * FROM import_watch_folders ORDER BY path"
        )

    def remove_watch_folder(self, folder_id):
        self.db.execute(
            "DELETE FROM import_watch_folders WHERE id=?", (int(folder_id),)
        )

    def scan_watch_folder(self, folder_id, auto_commit=False):
        frame = self.db.frame(
            "SELECT * FROM import_watch_folders WHERE id=?", (int(folder_id),)
        )
        if frame.empty:
            raise KeyError(folder_id)
        folder = frame.iloc[0]
        root = Path(folder["path"])
        if not root.exists():
            raise FileNotFoundError(root)
        pattern = "**/*" if folder["recursive"] else "*"
        results = []
        for path in root.glob(pattern):
            if not path.is_file() or path.suffix.lower() not in {".csv",".tsv",".xlsx",".xlsm"}:
                continue
            try:
                inspection = self.inspect_file(path)
                if inspection["duplicate_file"] and inspection["export_type"] not in {
                    "twitch_game_history", "twitch_game_events"
                }:
                    results.append({"file":str(path),"status":"Already imported"})
                    continue
                batch = self.stage(path)
                if auto_commit and batch["status"] in {"Ready","No changes"}:
                    batch = self.commit(
                        batch["batch_id"],
                        archive_source=bool(folder["archive_after_import"]),
                    )
                results.append({
                    "file":str(path),
                    "status":batch["status"],
                    "batch_id":batch["batch_id"],
                })
            except Exception as exc:
                results.append({"file":str(path),"status":"Failed","error":str(exc)})
        self.db.execute(
            """UPDATE import_watch_folders SET last_scanned_at=?,
               last_result_json=? WHERE id=?""",
            (datetime.now().isoformat(),json.dumps(results),int(folder_id)),
        )
        return results
