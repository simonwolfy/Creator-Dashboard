from __future__ import annotations
from datetime import datetime
import json

PROJECT_STATUSES = [
    "Planning","Recorded","Assets ready","Sent to editor","Editing",
    "Ready for review","Revision requested","Final approved",
    "Thumbnail","Scheduled","Published","On hold","Cancelled"
]
ASSET_STATUSES = ["Missing","Requested","Uploading","Available","Approved"]
DELIVERY_STATUSES = ["Expected","Delivered","Reviewed","Superseded"]
REVIEW_STATUSES = ["Open","Resolved","Dismissed"]

class ProductionManagementService:
    def __init__(self, db, notifications=None):
        self.db = db
        self.notifications = notifications
        self._ensure_schema()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS editors(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                specialty TEXT,
                active INTEGER DEFAULT 1,
                target_weekly_capacity REAL DEFAULT 2,
                default_turnaround_days REAL DEFAULT 4,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS production_projects(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                series_name TEXT,
                episode_number TEXT,
                platform TEXT,
                content_type TEXT,
                game_topic TEXT,
                status TEXT NOT NULL DEFAULT 'Planning',
                priority TEXT DEFAULT 'Normal',
                editor_id INTEGER,
                recording_date TEXT,
                sent_to_editor_at TEXT,
                expected_draft_at TEXT,
                actual_draft_at TEXT,
                review_due_at TEXT,
                planned_publish_at TEXT,
                actual_publish_at TEXT,
                progress_percent INTEGER DEFAULT 0,
                revision_count INTEGER DEFAULT 0,
                source_stream_id TEXT,
                pipeline_item_id INTEGER,
                folder_url TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(editor_id) REFERENCES editors(id)
            )""",
            """CREATE TABLE IF NOT EXISTS production_assets(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                asset_type TEXT NOT NULL,
                label TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Missing',
                location TEXT,
                required INTEGER DEFAULT 1,
                delivered_at TEXT,
                approved_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES production_projects(id)
            )""",
            """CREATE TABLE IF NOT EXISTS production_deliveries(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                version_label TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Expected',
                file_location TEXT,
                delivered_at TEXT,
                reviewed_at TEXT,
                duration_seconds INTEGER,
                file_size_mb REAL,
                editor_notes TEXT,
                creator_notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES production_projects(id)
            )""",
            """CREATE TABLE IF NOT EXISTS production_review_notes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                delivery_id INTEGER,
                timestamp_seconds INTEGER,
                category TEXT,
                comment TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Open',
                created_by TEXT DEFAULT 'Creator',
                resolved_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES production_projects(id),
                FOREIGN KEY(delivery_id) REFERENCES production_deliveries(id)
            )""",
            """CREATE TABLE IF NOT EXISTS production_activity(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                activity_type TEXT NOT NULL,
                detail_json TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_production_projects_status
               ON production_projects(status,priority,expected_draft_at)""",
            """CREATE INDEX IF NOT EXISTS idx_production_projects_editor
               ON production_projects(editor_id,status)""",
            """CREATE INDEX IF NOT EXISTS idx_review_notes_project
               ON production_review_notes(project_id,status,timestamp_seconds)"""
        ]
        for statement in statements:
            self.db.execute(statement)

    def create_editor(self, name, email=None, specialty=None,
                      target_weekly_capacity=2, default_turnaround_days=4,
                      notes=None):
        now = datetime.now().isoformat()
        return self.db.execute(
            """INSERT INTO editors(
                name,email,specialty,target_weekly_capacity,
                default_turnaround_days,notes,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (name,email,specialty,float(target_weekly_capacity),
             float(default_turnaround_days),notes,now,now)
        )

    def editors(self, active_only=False):
        sql = """SELECT e.*,
                 SUM(CASE WHEN p.status IN(
                    'Sent to editor','Editing','Ready for review',
                    'Revision requested'
                 ) THEN 1 ELSE 0 END) AS active_projects
                 FROM editors e
                 LEFT JOIN production_projects p ON p.editor_id=e.id"""
        params = []
        if active_only:
            sql += " WHERE e.active=1"
        sql += " GROUP BY e.id ORDER BY e.active DESC,e.name"
        return self.db.frame(sql, params)

    def create_project(self, values):
        now = datetime.now().isoformat()
        fields = [
            "title","series_name","episode_number","platform","content_type",
            "game_topic","status","priority","editor_id","recording_date",
            "sent_to_editor_at","expected_draft_at","review_due_at",
            "planned_publish_at","source_stream_id","pipeline_item_id",
            "folder_url","notes"
        ]
        data = [values.get(k) for k in fields]
        project_id = self.db.execute(
            f"""INSERT INTO production_projects(
                {",".join(fields)},created_at,updated_at
            ) VALUES({",".join("?" for _ in fields)},?,?)""",
            (*data,now,now)
        )
        self._log(project_id,"project_created",values)
        return project_id

    def project(self, project_id):
        frame = self.db.frame(
            """SELECT p.*,e.name AS editor_name
               FROM production_projects p
               LEFT JOIN editors e ON e.id=p.editor_id
               WHERE p.id=?""",(int(project_id),)
        )
        if frame.empty:
            raise KeyError(project_id)
        return frame.iloc[0].to_dict()

    def projects(self, status=None, editor_id=None):
        clauses, params = [], []
        if status and status != "All":
            clauses.append("p.status=?"); params.append(status)
        if editor_id:
            clauses.append("p.editor_id=?"); params.append(int(editor_id))
        sql = """SELECT p.id,p.title,p.series_name,p.episode_number,
                 p.platform,p.content_type,p.game_topic,p.status,p.priority,
                 e.name AS editor,p.recording_date,p.sent_to_editor_at,
                 p.expected_draft_at,p.actual_draft_at,p.review_due_at,
                 p.planned_publish_at,p.progress_percent,p.revision_count,
                 p.folder_url,p.updated_at
                 FROM production_projects p
                 LEFT JOIN editors e ON e.id=p.editor_id"""
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += """ ORDER BY
            CASE p.priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2
                 WHEN 'Normal' THEN 3 ELSE 4 END,
            COALESCE(p.expected_draft_at,p.planned_publish_at,'9999-12-31'),
            p.updated_at DESC"""
        return self.db.frame(sql, params)

    def update_project(self, project_id, **changes):
        allowed = {
            "title","series_name","episode_number","platform","content_type",
            "game_topic","status","priority","editor_id","recording_date",
            "sent_to_editor_at","expected_draft_at","actual_draft_at",
            "review_due_at","planned_publish_at","actual_publish_at",
            "progress_percent","revision_count","source_stream_id",
            "pipeline_item_id","folder_url","notes"
        }
        values = {k:v for k,v in changes.items() if k in allowed}
        if not values:
            return self.project(project_id)
        old = self.project(project_id)
        if values.get("status") == "Sent to editor" and not values.get("sent_to_editor_at"):
            values["sent_to_editor_at"] = datetime.now().isoformat()
        if values.get("status") == "Ready for review" and not values.get("actual_draft_at"):
            values["actual_draft_at"] = datetime.now().isoformat()
        if values.get("status") == "Published" and not values.get("actual_publish_at"):
            values["actual_publish_at"] = datetime.now().isoformat()
        values["updated_at"] = datetime.now().isoformat()
        columns = list(values)
        self.db.execute(
            "UPDATE production_projects SET " +
            ",".join(f"{column}=?" for column in columns) +
            " WHERE id=?",
            [values[column] for column in columns] + [int(project_id)]
        )
        self._log(project_id,"project_updated",{
            "before":old,"changes":changes
        })
        self._notify_transition(project_id, old.get("status"), values.get("status"))
        return self.project(project_id)

    def assign_editor(self, project_id, editor_id, expected_draft_at=None):
        editor = self.db.frame(
            "SELECT * FROM editors WHERE id=?",(int(editor_id),)
        )
        if editor.empty:
            raise KeyError(editor_id)
        changes = {"editor_id":int(editor_id)}
        if expected_draft_at:
            changes["expected_draft_at"] = expected_draft_at
        return self.update_project(project_id, **changes)

    def add_asset(self, project_id, asset_type, label, status="Missing",
                  location=None, required=True, notes=None):
        now = datetime.now().isoformat()
        asset_id = self.db.execute(
            """INSERT INTO production_assets(
                project_id,asset_type,label,status,location,required,notes,
                created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (int(project_id),asset_type,label,status,location,int(required),
             notes,now,now)
        )
        self._log(project_id,"asset_added",{"asset_id":asset_id,"label":label})
        return asset_id

    def update_asset(self, asset_id, status=None, location=None, notes=None):
        frame = self.db.frame(
            "SELECT * FROM production_assets WHERE id=?",(int(asset_id),)
        )
        if frame.empty:
            raise KeyError(asset_id)
        row = frame.iloc[0].to_dict()
        now = datetime.now().isoformat()
        delivered = now if status == "Available" and not row.get("delivered_at") else row.get("delivered_at")
        approved = now if status == "Approved" else row.get("approved_at")
        self.db.execute(
            """UPDATE production_assets SET
               status=COALESCE(?,status),location=COALESCE(?,location),
               notes=COALESCE(?,notes),delivered_at=?,approved_at=?,
               updated_at=? WHERE id=?""",
            (status,location,notes,delivered,approved,now,int(asset_id))
        )
        self._log(row["project_id"],"asset_updated",{
            "asset_id":asset_id,"status":status
        })

    def assets(self, project_id):
        return self.db.frame(
            """SELECT * FROM production_assets
               WHERE project_id=?
               ORDER BY required DESC,asset_type,label""",(int(project_id),)
        )

    def add_delivery(self, project_id, version_label, file_location=None,
                     status="Delivered", duration_seconds=None,
                     file_size_mb=None, editor_notes=None):
        now = datetime.now().isoformat()
        delivered_at = now if status == "Delivered" else None
        delivery_id = self.db.execute(
            """INSERT INTO production_deliveries(
                project_id,version_label,status,file_location,delivered_at,
                duration_seconds,file_size_mb,editor_notes,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (int(project_id),version_label,status,file_location,delivered_at,
             duration_seconds,file_size_mb,editor_notes,now,now)
        )
        self.update_project(
            project_id,status="Ready for review",
            actual_draft_at=delivered_at,progress_percent=75
        )
        self._log(project_id,"delivery_added",{
            "delivery_id":delivery_id,"version":version_label
        })
        return delivery_id

    def deliveries(self, project_id):
        return self.db.frame(
            """SELECT * FROM production_deliveries
               WHERE project_id=? ORDER BY created_at DESC""",(int(project_id),)
        )

    def add_review_note(self, project_id, comment, timestamp_seconds=None,
                        category="Edit", delivery_id=None,
                        created_by="Creator"):
        now = datetime.now().isoformat()
        note_id = self.db.execute(
            """INSERT INTO production_review_notes(
                project_id,delivery_id,timestamp_seconds,category,comment,
                created_by,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (int(project_id),delivery_id,timestamp_seconds,category,comment,
             created_by,now,now)
        )
        self._log(project_id,"review_note_added",{
            "note_id":note_id,"timestamp_seconds":timestamp_seconds
        })
        return note_id

    def resolve_review_note(self, note_id, status="Resolved"):
        if status not in REVIEW_STATUSES:
            raise ValueError(status)
        frame = self.db.frame(
            "SELECT * FROM production_review_notes WHERE id=?",(int(note_id),)
        )
        if frame.empty:
            raise KeyError(note_id)
        row = frame.iloc[0].to_dict()
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE production_review_notes SET status=?,resolved_at=?,
               updated_at=? WHERE id=?""",
            (status,now if status=="Resolved" else None,now,int(note_id))
        )
        self._log(row["project_id"],"review_note_updated",{
            "note_id":note_id,"status":status
        })

    def review_notes(self, project_id, status=None):
        sql = """SELECT * FROM production_review_notes WHERE project_id=?"""
        params = [int(project_id)]
        if status and status != "All":
            sql += " AND status=?"; params.append(status)
        sql += " ORDER BY COALESCE(timestamp_seconds,999999),created_at"
        return self.db.frame(sql,params)

    def request_revision(self, project_id, notes=None):
        project = self.project(project_id)
        count = int(project.get("revision_count") or 0) + 1
        result = self.update_project(
            project_id,status="Revision requested",
            revision_count=count,progress_percent=70,
            notes=notes or project.get("notes")
        )
        self._log(project_id,"revision_requested",{"revision_count":count})
        return result

    def approve_final(self, project_id):
        open_notes = self.review_notes(project_id,"Open")
        if not open_notes.empty:
            raise ValueError("Resolve or dismiss open review notes before final approval.")
        return self.update_project(
            project_id,status="Final approved",progress_percent=90
        )

    def workload(self):
        return self.db.frame("""
            SELECT e.id,e.name,e.specialty,e.target_weekly_capacity,
                   e.default_turnaround_days,
                   SUM(CASE WHEN p.status IN(
                     'Sent to editor','Editing','Ready for review',
                     'Revision requested'
                   ) THEN 1 ELSE 0 END) AS active_projects,
                   SUM(CASE WHEN p.status IN('Sent to editor','Editing')
                     THEN 1 ELSE 0 END) AS editing_projects,
                   SUM(CASE WHEN p.status='Ready for review'
                     THEN 1 ELSE 0 END) AS waiting_for_creator,
                   AVG(CASE WHEN p.actual_draft_at IS NOT NULL
                             AND p.sent_to_editor_at IS NOT NULL
                       THEN julianday(p.actual_draft_at)-
                            julianday(p.sent_to_editor_at) END)
                       AS average_turnaround_days,
                   SUM(CASE WHEN p.expected_draft_at < datetime('now')
                             AND p.status IN('Sent to editor','Editing')
                       THEN 1 ELSE 0 END) AS overdue_projects
            FROM editors e
            LEFT JOIN production_projects p ON p.editor_id=e.id
            WHERE e.active=1
            GROUP BY e.id
            ORDER BY overdue_projects DESC,active_projects DESC,e.name
        """)

    def dashboard(self):
        projects = self.projects()
        workload = self.workload()
        counts = {}
        if not projects.empty:
            counts = projects["status"].value_counts().to_dict()
        return {
            "active_projects": int(sum(
                counts.get(status,0) for status in [
                    "Sent to editor","Editing","Ready for review",
                    "Revision requested"
                ]
            )),
            "waiting_for_editor": int(
                counts.get("Sent to editor",0)+counts.get("Editing",0)
            ),
            "needs_creator_review": int(counts.get("Ready for review",0)),
            "revision_requested": int(counts.get("Revision requested",0)),
            "ready_to_publish": int(
                counts.get("Final approved",0)+counts.get("Thumbnail",0)+
                counts.get("Scheduled",0)
            ),
            "workload": workload
        }

    def recommendations(self):
        results = []
        projects = self.projects()
        workload = self.workload()
        if not projects.empty:
            review = projects[projects["status"]=="Ready for review"]
            for _, row in review.head(3).iterrows():
                results.append({
                    "priority":"Critical",
                    "action":f'Review "{row["title"]}"',
                    "reason":"The editor has delivered a draft and production is waiting on you.",
                    "project_id":int(row["id"])
                })
            overdue = projects[
                projects["status"].isin(["Sent to editor","Editing"]) &
                projects["expected_draft_at"].notna() &
                (projects["expected_draft_at"].astype(str) <
                 datetime.now().isoformat())
            ]
            for _, row in overdue.head(3).iterrows():
                results.append({
                    "priority":"High",
                    "action":f'Follow up on "{row["title"]}"',
                    "reason":"The expected draft date has passed.",
                    "project_id":int(row["id"])
                })
        if not workload.empty:
            overloaded = workload[
                workload["active_projects"] >
                workload["target_weekly_capacity"]
            ]
            for _, row in overloaded.iterrows():
                results.append({
                    "priority":"High",
                    "action":f'Reduce assignments for {row["name"]}',
                    "reason":(
                        f'{int(row["active_projects"])} active projects exceed '
                        f'the target capacity of {row["target_weekly_capacity"]:.0f}.'
                    ),
                    "project_id":None
                })
        return results

    def _notify_transition(self, project_id, old_status, new_status):
        if not self.notifications or not new_status or old_status == new_status:
            return
        project = self.project(project_id)
        level = "Success" if new_status in (
            "Ready for review","Final approved","Published"
        ) else "Info"
        self.notifications.create(
            "Production",level,f'Production status: {new_status}',
            f'{project["title"]} moved from {old_status} to {new_status}.',
            "production_project",project_id
        )

    def _log(self, project_id, activity_type, detail=None):
        self.db.execute(
            """INSERT INTO production_activity(
                project_id,activity_type,detail_json,created_at
            ) VALUES(?,?,?,?)""",
            (project_id,activity_type,json.dumps(detail or {},default=str),
             datetime.now().isoformat())
        )
