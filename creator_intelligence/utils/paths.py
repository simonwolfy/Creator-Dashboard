import sys
from pathlib import Path

PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
DB_PATH = PROJECT_ROOT / "data" / "creator_intelligence.db"
BACKUP_DIR = PROJECT_ROOT / "backups"
IMPORT_DIR = PROJECT_ROOT / "imports"
EXPORT_DIR = PROJECT_ROOT / "exports"
LOG_DIR = PROJECT_ROOT / "logs"
CONFIG_DIR = PROJECT_ROOT / "config"

for folder in (BACKUP_DIR, IMPORT_DIR, EXPORT_DIR, LOG_DIR, CONFIG_DIR):
    folder.mkdir(parents=True, exist_ok=True)
