from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import mimetypes
from pathlib import Path
from typing import Any

from creator_intelligence.services.asset_management import AssetManagementService


@dataclass
class ScanSummary:
    folder_id: int
    discovered: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    errors: int = 0
    error_message: str | None = None


class FolderWatcherService:
    """Polling folder scanner that reconciles local files into managed assets."""

    def __init__(self, db):
        self.db = db
        self.assets = AssetManagementService(db)

    def add_folder(
        self,
        path: str,
        *,
        name: str | None = None,
        recursive: bool = True,
        enabled: bool = True,
        include_extensions: str = "",
        exclude_extensions: str = "",
        calculate_checksums: bool = False,
        asset_role: str | None = None,
    ) -> int:
        normalized = str(Path(path).expanduser().resolve())
        now = datetime.now().isoformat()
        return int(
            self.db.execute(
                """
                INSERT INTO watched_folders(
                    name,path,recursive,enabled,include_extensions,exclude_extensions,
                    calculate_checksums,asset_role,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    name or Path(normalized).name or normalized,
                    normalized,
                    int(recursive),
                    int(enabled),
                    include_extensions,
                    exclude_extensions,
                    int(calculate_checksums),
                    asset_role,
                    now,
                    now,
                ),
            )
        )

    def list_folders(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE enabled=1" if enabled_only else ""
        return self.db.frame(
            f"SELECT * FROM watched_folders {where} ORDER BY name"
        ).to_dict("records")

    def set_enabled(self, folder_id: int, enabled: bool) -> None:
        self.db.execute(
            "UPDATE watched_folders SET enabled=?,updated_at=? WHERE id=?",
            (int(enabled), datetime.now().isoformat(), folder_id),
        )

    def scan_all(self) -> list[ScanSummary]:
        return [self.scan_folder(int(row["id"])) for row in self.list_folders(enabled_only=True)]

    def scan_folder(self, folder_id: int) -> ScanSummary:
        frame = self.db.frame("SELECT * FROM watched_folders WHERE id=?", (folder_id,))
        if frame.empty:
            raise ValueError(f"Unknown watched folder: {folder_id}")
        folder = frame.iloc[0].to_dict()
        summary = ScanSummary(folder_id=folder_id)
        started_at = datetime.now().isoformat()
        run_id = int(
            self.db.execute(
                "INSERT INTO folder_scan_runs(folder_id,started_at) VALUES(?,?)",
                (folder_id, started_at),
            )
        )

        try:
            if not int(folder["enabled"]):
                return summary
            root = Path(str(folder["path"]))
            if not root.is_dir():
                raise FileNotFoundError(f"Watched folder does not exist: {root}")

            include = self._extensions(folder.get("include_extensions"))
            exclude = self._extensions(folder.get("exclude_extensions"))
            paths = root.rglob("*") if int(folder["recursive"]) else root.glob("*")
            seen: set[str] = set()

            for path in paths:
                if not path.is_file() or not self._included(path, include, exclude):
                    continue
                summary.discovered += 1
                location = str(path.resolve())
                seen.add(location)
                try:
                    self._reconcile_file(folder, path, location, summary)
                except Exception:
                    summary.errors += 1

            tracked = self.db.frame(
                "SELECT file_path,asset_id FROM watched_folder_assets WHERE folder_id=?",
                (folder_id,),
            ).to_dict("records")
            for row in tracked:
                if row["file_path"] not in seen:
                    self.assets.mark_verified(str(row["asset_id"]), available=False)
                    summary.missing += 1

            self.db.execute(
                "UPDATE watched_folders SET last_scan_at=?,last_error=NULL,updated_at=? WHERE id=?",
                (datetime.now().isoformat(), datetime.now().isoformat(), folder_id),
            )
        except Exception as exc:
            summary.errors += 1
            summary.error_message = str(exc)
            self.db.execute(
                "UPDATE watched_folders SET last_scan_at=?,last_error=?,updated_at=? WHERE id=?",
                (datetime.now().isoformat(), str(exc), datetime.now().isoformat(), folder_id),
            )
        finally:
            self.db.execute(
                """
                UPDATE folder_scan_runs SET finished_at=?,discovered=?,created=?,updated=?,
                    unchanged=?,missing=?,errors=?,error_message=? WHERE id=?
                """,
                (
                    datetime.now().isoformat(),
                    summary.discovered,
                    summary.created,
                    summary.updated,
                    summary.unchanged,
                    summary.missing,
                    summary.errors,
                    summary.error_message,
                    run_id,
                ),
            )
        return summary

    def recent_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.frame(
            """
            SELECT run.*, folder.name AS folder_name
            FROM folder_scan_runs run
            JOIN watched_folders folder ON folder.id=run.folder_id
            ORDER BY run.started_at DESC LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).to_dict("records")

    def _reconcile_file(
        self,
        folder: dict[str, Any],
        path: Path,
        location: str,
        summary: ScanSummary,
    ) -> None:
        stat = path.stat()
        state = self.db.frame(
            "SELECT * FROM watched_folder_assets WHERE folder_id=? AND file_path=?",
            (int(folder["id"]), location),
        )
        now = datetime.now().isoformat()
        checksum = self._sha256(path) if int(folder["calculate_checksums"]) else None
        if state.empty:
            asset_id = self.assets.create_asset(
                {
                    "name": path.name,
                    "asset_type": self._asset_type(path),
                    "role": folder.get("asset_role"),
                    "storage_provider": "Local",
                    "location": location,
                    "mime_type": mimetypes.guess_type(path.name)[0],
                    "extension": path.suffix.lower(),
                    "size_bytes": stat.st_size,
                    "checksum_sha256": checksum,
                    "status": "Available",
                    "last_verified_at": now,
                }
            )
            self.db.execute(
                """
                INSERT INTO watched_folder_assets(
                    folder_id,asset_id,file_path,size_bytes,modified_ns,last_seen_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (int(folder["id"]), asset_id, location, stat.st_size, stat.st_mtime_ns, now),
            )
            summary.created += 1
            return

        row = state.iloc[0].to_dict()
        changed = int(row.get("size_bytes") or -1) != stat.st_size or int(
            row.get("modified_ns") or -1
        ) != stat.st_mtime_ns
        if changed:
            values: dict[str, Any] = {
                "size_bytes": stat.st_size,
                "status": "Available",
                "last_verified_at": now,
            }
            if checksum is not None:
                values["checksum_sha256"] = checksum
            self.assets.update_asset(str(row["asset_id"]), values)
            summary.updated += 1
        else:
            self.assets.mark_verified(str(row["asset_id"]), available=True)
            summary.unchanged += 1
        self.db.execute(
            """
            UPDATE watched_folder_assets SET size_bytes=?,modified_ns=?,last_seen_at=?
            WHERE folder_id=? AND file_path=?
            """,
            (stat.st_size, stat.st_mtime_ns, now, int(folder["id"]), location),
        )

    @staticmethod
    def _extensions(value: Any) -> set[str]:
        return {
            token.strip().lower() if token.strip().startswith(".") else f".{token.strip().lower()}"
            for token in str(value or "").split(",")
            if token.strip()
        }

    @staticmethod
    def _included(path: Path, include: set[str], exclude: set[str]) -> bool:
        suffix = path.suffix.lower()
        return (not include or suffix in include) and suffix not in exclude

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _asset_type(path: Path) -> str:
        mime = mimetypes.guess_type(path.name)[0] or ""
        if mime.startswith("video/"):
            return "Video"
        if mime.startswith("audio/"):
            return "Audio"
        if mime.startswith("image/"):
            return "Image"
        if path.suffix.lower() in {".srt", ".vtt", ".ass"}:
            return "Subtitle"
        if path.suffix.lower() in {".prproj", ".drp", ".aep", ".psd"}:
            return "Project"
        return "Other"

    @staticmethod
    def summary_dict(summary: ScanSummary) -> dict[str, Any]:
        return asdict(summary)
