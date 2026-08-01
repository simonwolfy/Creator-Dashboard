from __future__ import annotations
from datetime import datetime
from creator_intelligence.repositories.base import BaseRepository

class SettingsRepository(BaseRepository):
    def get(self, key, default=None):
        value = self.db.scalar("SELECT value FROM app_settings WHERE key=?", (key,), default=None)
        return default if value is None else value

    def set(self, key, value):
        self.db.execute(
            """INSERT INTO app_settings(key,value,updated_at)
               VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, str(value), datetime.now().isoformat())
        )

    def all(self):
        return self.db.frame("SELECT * FROM app_settings ORDER BY key")
