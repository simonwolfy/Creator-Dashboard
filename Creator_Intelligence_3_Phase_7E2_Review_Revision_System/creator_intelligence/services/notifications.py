from __future__ import annotations
from datetime import datetime, timedelta
import json

class NotificationService:
    LEVELS = ("Info","Success","Warning","Error")
    CATEGORIES = (
        "Import","Backup","Rollback","Prediction","Model",
        "Pipeline","Calendar","Integration","System"
    )

    def __init__(self, db):
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            level TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            source_type TEXT,
            source_id TEXT,
            action_label TEXT,
            action_payload_json TEXT,
            is_read INTEGER DEFAULT 0,
            is_dismissed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            read_at TEXT,
            dismissed_at TEXT,
            UNIQUE(category,title,message,source_type,source_id)
        )""")
        self.db.execute("""CREATE INDEX IF NOT EXISTS idx_notifications_active
            ON notifications(is_dismissed,is_read,created_at)""")

    def create(
        self, category, level, title, message,
        source_type=None, source_id=None,
        action_label=None, action_payload=None,
        deduplicate=True
    ):
        if level not in self.LEVELS:
            level = "Info"
        now = datetime.now().isoformat()
        sql = """INSERT {conflict} INTO notifications(
            category,level,title,message,source_type,source_id,
            action_label,action_payload_json,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?)""".format(
            conflict="OR IGNORE" if deduplicate else ""
        )
        return self.db.execute(sql,(
            category,level,title,message,source_type,
            str(source_id) if source_id is not None else None,
            action_label,
            json.dumps(action_payload or {}),
            now
        ))

    def list(self, include_dismissed=False, unread_only=False, limit=1000):
        clauses=[]
        params=[]
        if not include_dismissed:
            clauses.append("is_dismissed=0")
        if unread_only:
            clauses.append("is_read=0")
        sql="""SELECT id,category,level,title,message,source_type,source_id,
               action_label,action_payload_json,is_read,is_dismissed,
               created_at,read_at,dismissed_at
               FROM notifications"""
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        return self.db.frame(sql,params)

    def unread_count(self):
        frame=self.db.frame(
            "SELECT COUNT(*) AS count FROM notifications WHERE is_read=0 AND is_dismissed=0"
        )
        return int(frame.iloc[0]["count"]) if not frame.empty else 0

    def mark_read(self, notification_id):
        self.db.execute("""UPDATE notifications SET is_read=1,read_at=?
            WHERE id=?""",(datetime.now().isoformat(),int(notification_id)))

    def mark_all_read(self):
        self.db.execute("""UPDATE notifications SET is_read=1,read_at=?
            WHERE is_read=0 AND is_dismissed=0""",(datetime.now().isoformat(),))

    def dismiss(self, notification_id):
        self.db.execute("""UPDATE notifications SET is_dismissed=1,dismissed_at=?
            WHERE id=?""",(datetime.now().isoformat(),int(notification_id)))

    def clear_dismissed(self):
        self.db.execute("DELETE FROM notifications WHERE is_dismissed=1")

    def emit_import_result(self, result):
        status=result.get("status","Unknown")
        file_name=result.get("file_name") or result.get("file") or "Import"
        batch_id=result.get("batch_id")
        if status=="Completed":
            self.create(
                "Import","Success","Import complete",
                f"{file_name} imported successfully.",
                "import_batch",batch_id,
                "Open import history",{"batch_id":batch_id}
            )
        elif status=="Completed with warnings":
            self.create(
                "Import","Warning","Import completed with warnings",
                f"{file_name} imported with rejected or warning rows.",
                "import_batch",batch_id,
                "Review import",{"batch_id":batch_id}
            )
        elif status=="Already imported":
            self.create(
                "Import","Info","Duplicate file ignored",
                f"{file_name} was already imported.",
                "file",file_name
            )
        elif status=="Failed":
            self.create(
                "Import","Error","Import failed",
                f"{file_name}: {result.get('error') or result.get('error_message') or 'Unknown error'}",
                "import_batch",batch_id,
                "Review error",{"batch_id":batch_id}
            )

    def generate_operational_alerts(self):
        now=datetime.now()
        today=now.date().isoformat()

        overdue=self.db.frame("""SELECT id,title,due_date,status
            FROM content_pipeline
            WHERE due_date IS NOT NULL
              AND date(due_date) < date(?)
              AND status NOT IN ('Published','Archived')""",(today,))
        for _,row in overdue.iterrows():
            self.create(
                "Pipeline","Warning","Content item overdue",
                f'{row["title"]} was due {row["due_date"]}.',
                "pipeline_item",row["id"],
                "Open pipeline",{"item_id":int(row["id"])}
            )

        upcoming=self.db.frame("""SELECT id,title,scheduled_start,item_type
            FROM content_calendar
            WHERE datetime(scheduled_start) >= datetime(?)
              AND datetime(scheduled_start) <= datetime(?)
              AND status NOT IN ('Published','Complete','Cancelled')""",
            (now.isoformat(),(now+timedelta(hours=24)).isoformat())
        )
        for _,row in upcoming.iterrows():
            self.create(
                "Calendar","Info","Scheduled item approaching",
                f'{row["title"]} is scheduled for {row["scheduled_start"]}.',
                "calendar_item",row["id"],
                "Open calendar",{"item_id":int(row["id"])}
            )

        failed=self.db.frame("""SELECT batch_id,file_name,error_message
            FROM import_jobs WHERE status='Failed'
            ORDER BY id DESC LIMIT 20""")
        for _,row in failed.iterrows():
            self.create(
                "Import","Error","Import requires attention",
                f'{row["file_name"]}: {row["error_message"] or "Import failed."}',
                "import_batch",row["batch_id"],
                "Review import",{"batch_id":row["batch_id"]}
            )
