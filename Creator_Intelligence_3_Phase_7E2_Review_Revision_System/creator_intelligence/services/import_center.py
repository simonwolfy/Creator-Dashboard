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
                rows_rejected INTEGER DEFAULT 0,
                warning_json TEXT DEFAULT '[]',
                error_message TEXT,
                backup_path TEXT,
                rollback_available INTEGER DEFAULT 0,
                rolled_back_at TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            )""",
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_import_jobs_hash_success
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

    def read_headers(self, path):
        path = Path(path)
        if path.suffix.lower() not in {".csv", ".tsv"}:
            raise ValueError("Only CSV and TSV files are currently supported.")
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            return next(reader, [])

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
            "comments","shares","impressions","viewer_count"
        }
        numeric_float = {"average_viewers","total_revenue","watch_time_hours","ctr"}
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
        }
        if export_type not in queries:
            return None
        sql, params = queries[export_type]
        frame = self.db.frame(sql, params)
        return frame.iloc[0].to_dict() if not frame.empty else None

    def stage(self, path, allow_duplicate_file=False):
        info = self.inspect_file(path)
        if info["duplicate_file"] and not allow_duplicate_file:
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
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        counts = {
            "rows_detected": 0, "rows_staged": 0, "rows_skipped": 0,
            "rows_rejected": 0
        }
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            for row_number, raw in enumerate(reader, start=2):
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

                key = self._record_key(info["export_type"], normalized)
                if not key:
                    errors.append("Required record key is missing.")

                existing = self._existing_record(info["export_type"], key)
                if errors:
                    disposition = "Rejected"
                    counts["rows_rejected"] += 1
                elif existing:
                    comparable = {
                        k: existing.get(k) for k in normalized
                    }
                    if self._row_hash(comparable) == self._row_hash(normalized):
                        disposition = "Duplicate"
                        counts["rows_skipped"] += 1
                    else:
                        disposition = "Update"
                        counts["rows_staged"] += 1
                else:
                    disposition = "Insert"
                    counts["rows_staged"] += 1

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
               rows_skipped=?,rows_rejected=? WHERE batch_id=?""",
            (
                status,counts["rows_detected"],counts["rows_staged"],
                counts["rows_skipped"],counts["rows_rejected"],batch_id,
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

    def _upsert(self, export_type, row, batch_id):
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
                "content_id","title","publish_time","duration_seconds","views",
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
        sql = f"""INSERT INTO {table}({','.join(available)})
                  VALUES({placeholders})
                  ON CONFLICT({conflict}) DO UPDATE SET
                  {','.join(f'{c}=excluded.{c}' for c in update_columns)}"""
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
                if staged_row["disposition"] not in {"Insert","Update"}:
                    continue
                normalized = json.loads(staged_row["normalized_json"])
                operation = self._upsert(job["detected_type"], normalized, batch_id)
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

            warning_count = int(job.get("rows_rejected") or 0)
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
               rows_skipped,rows_rejected,rollback_available,
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
            if not path.is_file() or path.suffix.lower() not in {".csv",".tsv"}:
                continue
            try:
                inspection = self.inspect_file(path)
                if inspection["duplicate_file"]:
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
