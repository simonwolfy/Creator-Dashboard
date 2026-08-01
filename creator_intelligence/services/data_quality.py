from datetime import datetime
import pandas as pd

class DataQualityService:
    def __init__(self, db):
        self.db = db

    def scan(self):
        now = datetime.now().isoformat()
        self.db.execute("DELETE FROM data_quality_issues WHERE resolved=0")
        issues = []

        checks = [
            ("warning", "missing_game", "game_segments",
             "SELECT COUNT(*) FROM game_segments WHERE game IS NULL OR TRIM(game)=''",
             "Game timeline segments are missing a game/category."),
            ("warning", "missing_publish_time", "youtube_content",
             "SELECT COUNT(*) FROM youtube_content WHERE publish_time IS NULL OR TRIM(publish_time)=''",
             "YouTube records are missing publish timestamps."),
            ("info", "unlinked_youtube", "youtube_content",
             """SELECT COUNT(*) FROM youtube_content y
                WHERE NOT EXISTS (SELECT 1 FROM content_links l WHERE l.youtube_content_id=y.content_id)""",
             "YouTube records are not yet linked to a Twitch source stream."),
            ("warning", "duplicate_twitch_dates", "twitch_daily",
             """SELECT COUNT(*) FROM (
                SELECT date, COUNT(*) c FROM twitch_daily GROUP BY date HAVING c > 1
             )""",
             "Duplicate Twitch daily dates were detected."),
        ]
        for severity, category, table, sql, description in checks:
            count = int(self.db.scalar(sql))
            if count:
                issues.append((now, severity, category, table, None, f"{description} Count: {count}", 0))

        if issues:
            for item in issues:
                self.db.execute("""INSERT INTO data_quality_issues
                    (detected_at,severity,category,table_name,record_key,description,resolved)
                    VALUES(?,?,?,?,?,?,?)""", item)
        return self.db.frame("SELECT * FROM data_quality_issues WHERE resolved=0 ORDER BY severity DESC, id DESC")
