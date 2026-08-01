from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

class BackupService:
    def __init__(self, database_path: Path, backup_dir: Path, retention=30):
        self.database_path = Path(database_path)
        self.backup_dir = Path(backup_dir)
        self.retention = max(1, int(retention))
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create(self, reason="manual") -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_reason = "".join(c if c.isalnum() or c in "-_" else "_" for c in reason)
        target = self.backup_dir / f"creator_intelligence_{stamp}_{safe_reason}.db"
        source = sqlite3.connect(self.database_path)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        self.prune()
        return target

    def prune(self):
        backups = sorted(
            self.backup_dir.glob("creator_intelligence_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        for old in backups[self.retention:]:
            old.unlink(missing_ok=True)

    def list(self):
        return sorted(
            self.backup_dir.glob("creator_intelligence_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
