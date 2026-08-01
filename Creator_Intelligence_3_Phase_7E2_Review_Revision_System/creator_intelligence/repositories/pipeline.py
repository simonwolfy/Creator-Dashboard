from __future__ import annotations
from datetime import datetime
from creator_intelligence.repositories.base import BaseRepository

class PipelineRepository(BaseRepository):
    def add(self, title, platform, content_type, status, game_topic=None, notes=None):
        now = datetime.now().isoformat()
        return self.db.execute(
            """INSERT INTO content_pipeline
               (title,platform,content_type,status,game_topic,notes,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (title, platform, content_type, status, game_topic, notes, now, now)
        )

    def list(self):
        return self.db.frame(
            """SELECT id,title,platform,content_type,game_topic,status,
                      planned_publish_date,source_stream_date,notes,updated_at
               FROM content_pipeline ORDER BY updated_at DESC"""
        )

    def update_status(self, item_id, status):
        self.db.execute(
            "UPDATE content_pipeline SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, int(item_id))
        )
