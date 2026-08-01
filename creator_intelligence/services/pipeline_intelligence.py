from __future__ import annotations
from datetime import datetime
import pandas as pd

STATUSES = [
    "Ideas","Selected","Recording complete","Editing",
    "Thumbnail","Scheduled","Published","Archived"
]

class PipelineIntelligenceService:
    def __init__(self, db):
        self.db = db
        self._ensure_columns()

    def _ensure_columns(self):
        existing = {
            row[1] for row in self.db.frame("PRAGMA table_info(content_pipeline)").itertuples(index=False)
        }
        additions = {
            "priority":"TEXT DEFAULT 'Normal'",
            "assignee":"TEXT",
            "due_date":"TEXT",
            "progress_percent":"INTEGER DEFAULT 0",
            "linked_stream_id":"TEXT",
            "linked_content_id":"TEXT",
            "planned_publish_date":"TEXT",
            "actual_publish_date":"TEXT",
            "editing_hours":"REAL DEFAULT 0",
        }
        for name, definition in additions.items():
            if name not in existing:
                self.db.execute(f"ALTER TABLE content_pipeline ADD COLUMN {name} {definition}")

    def list(self, status=None):
        sql = """SELECT id,title,platform,content_type,game_topic,status,priority,assignee,
                 due_date,progress_percent,linked_stream_id,linked_content_id,
                 planned_publish_date,actual_publish_date,editing_hours,notes,
                 created_at,updated_at
                 FROM content_pipeline"""
        params = []
        if status and status != "All":
            sql += " WHERE status=?"
            params.append(status)
        sql += """ ORDER BY
            CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2
                          WHEN 'Normal' THEN 3 ELSE 4 END,
            COALESCE(due_date,'9999-12-31'), updated_at DESC"""
        df = self.db.frame(sql, params)
        if not df.empty:
            for c in ["due_date","planned_publish_date","actual_publish_date","created_at","updated_at"]:
                df[c] = pd.to_datetime(df[c], errors="coerce")
            today = pd.Timestamp.today().normalize()
            df["overdue"] = (
                df["due_date"].notna()
                & (df["due_date"] < today)
                & ~df["status"].isin(["Published","Archived"])
            )
            df["schedule_variance_days"] = (
                df["actual_publish_date"] - df["planned_publish_date"]
            ).dt.days
        return df

    def save(self, values, item_id=None):
        now = datetime.now().isoformat()
        fields = [
            "title","platform","content_type","game_topic","status","priority",
            "assignee","due_date","progress_percent","linked_stream_id",
            "linked_content_id","planned_publish_date","actual_publish_date",
            "editing_hours","notes"
        ]
        data = [values.get(k) for k in fields]
        if item_id:
            assigns = ",".join(f"{k}=?" for k in fields)
            self.db.execute(
                f"UPDATE content_pipeline SET {assigns},updated_at=? WHERE id=?",
                (*data,now,int(item_id))
            )
            return item_id
        return self.db.execute(
            f"""INSERT INTO content_pipeline(
                {",".join(fields)},created_at,updated_at
            ) VALUES({",".join("?" for _ in fields)},?,?)""",
            (*data,now,now)
        )

    def delete(self,item_id):
        self.db.execute("DELETE FROM content_pipeline WHERE id=?",(int(item_id),))

    def status_summary(self):
        return self.db.frame("""
            SELECT status,COUNT(*) AS items,
                   AVG(COALESCE(progress_percent,0)) AS average_progress,
                   SUM(COALESCE(editing_hours,0)) AS editing_hours
            FROM content_pipeline
            GROUP BY status
            ORDER BY CASE status
                WHEN 'Ideas' THEN 1 WHEN 'Selected' THEN 2
                WHEN 'Recording complete' THEN 3 WHEN 'Editing' THEN 4
                WHEN 'Thumbnail' THEN 5 WHEN 'Scheduled' THEN 6
                WHEN 'Published' THEN 7 WHEN 'Archived' THEN 8 ELSE 9 END
        """)
