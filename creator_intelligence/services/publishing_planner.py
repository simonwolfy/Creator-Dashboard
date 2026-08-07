from __future__ import annotations
from datetime import datetime, timedelta
import json
import math

PLATFORMS = ["YouTube","YouTube Shorts","TikTok","Twitch","Instagram","Multi-platform"]
PUBLISH_STATUSES = ["Draft","Planned","Ready","Scheduled","Published","Skipped","Cancelled"]

class PublishingPlannerService:
    def __init__(self, db, production_service=None, notifications=None):
        self.db = db
        self.production_service = production_service
        self.notifications = notifications
        self._ensure_schema()
        from creator_intelligence.services.publishing_outcomes import PublishingOutcomeService
        self.outcomes = PublishingOutcomeService(db)
        from creator_intelligence.services.packaging_experiments import PackagingExperimentService
        self.experiments = PackagingExperimentService(db,self.outcomes)

    def outcome_dashboard(self):
        return self.outcomes.dashboard()

    def outcome_summary(self):
        return self.outcomes.summary()

    def refresh_outcomes(self):
        return self.outcomes.process_sync()

    def set_package_decision(self, package_id, status, used=None):
        return self.outcomes.record_decision(package_id, status, used)

    def link_package(self, package_id, source_video_id):
        return self.outcomes.link(package_id, source_video_id)

    def experiment_dashboard(self):
        return self.experiments.dashboard()

    def experiment_variants(self, experiment_id):
        return self.experiments.variants(experiment_id)

    def experiment_patterns(self):
        return self.experiments.winning_patterns()

    def select_experiment_variant(self, variant_id):
        return self.experiments.select(variant_id)

    def reject_experiment_variant(self, variant_id):
        return self.experiments.reject(variant_id)

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS publishing_slots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                weekday INTEGER NOT NULL,
                publish_time TEXT NOT NULL,
                content_type TEXT,
                active INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 100,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS publishing_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                platform TEXT NOT NULL,
                content_type TEXT,
                status TEXT NOT NULL DEFAULT 'Draft',
                production_project_id INTEGER,
                pipeline_item_id INTEGER,
                planned_publish_at TEXT,
                scheduled_publish_at TEXT,
                actual_publish_at TEXT,
                timezone TEXT DEFAULT 'America/Chicago',
                score REAL DEFAULT 0,
                confidence REAL DEFAULT 0,
                rationale TEXT,
                description_status TEXT DEFAULT 'Missing',
                thumbnail_status TEXT DEFAULT 'Missing',
                metadata_status TEXT DEFAULT 'Missing',
                upload_status TEXT DEFAULT 'Not uploaded',
                external_url TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(production_project_id) REFERENCES production_projects(id)
            )""",
            """CREATE TABLE IF NOT EXISTS publishing_dependencies(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publishing_item_id INTEGER NOT NULL,
                dependency_type TEXT NOT NULL,
                label TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Open',
                due_at TEXT,
                owner TEXT DEFAULT 'Creator',
                source_record_type TEXT,
                source_record_id INTEGER,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(publishing_item_id) REFERENCES publishing_items(id)
            )""",
            """CREATE TABLE IF NOT EXISTS publishing_performance(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                content_type TEXT,
                published_at TEXT NOT NULL,
                views REAL DEFAULT 0,
                impressions REAL DEFAULT 0,
                click_through_rate REAL,
                average_view_duration REAL,
                retention_rate REAL,
                engagement_rate REAL,
                subscribers_gained REAL DEFAULT 0,
                source_content_id TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS publishing_recommendations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_key TEXT NOT NULL UNIQUE,
                recommendation_type TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                priority TEXT NOT NULL,
                score REAL NOT NULL,
                related_item_id INTEGER,
                related_project_id INTEGER,
                status TEXT DEFAULT 'Active',
                generated_at TEXT NOT NULL,
                resolved_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS publishing_activity(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publishing_item_id INTEGER,
                activity_type TEXT NOT NULL,
                detail_json TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_publishing_items_schedule
               ON publishing_items(status,planned_publish_at,platform)""",
            """CREATE INDEX IF NOT EXISTS idx_publishing_dependencies
               ON publishing_dependencies(publishing_item_id,status,due_at)""",
            """CREATE INDEX IF NOT EXISTS idx_publishing_performance
               ON publishing_performance(platform,content_type,published_at)"""
        ]
        for statement in statements:
            self.db.execute(statement)
        self._seed_default_slots()

    def _seed_default_slots(self):
        count = int(self.db.frame("SELECT COUNT(*) AS c FROM publishing_slots").iloc[0]["c"])
        if count:
            return
        now = datetime.now().isoformat()
        defaults = [
            ("YouTube",5,"10:00","Long-form",10,"Primary weekly long-form release"),
            ("YouTube Shorts",1,"10:00","Short",20,"Early-week short"),
            ("YouTube Shorts",3,"10:00","Short",20,"Mid-week short"),
            ("TikTok",2,"18:00","Short",30,"Evening TikTok"),
            ("TikTok",5,"18:00","Short",30,"Weekend TikTok"),
        ]
        for platform,weekday,time_value,content_type,priority,notes in defaults:
            self.db.execute(
                """INSERT INTO publishing_slots(
                    platform,weekday,publish_time,content_type,priority,notes,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (platform,weekday,time_value,content_type,priority,notes,now,now)
            )

    def slots(self, active_only=False):
        sql = "SELECT * FROM publishing_slots"
        params = []
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY weekday,publish_time,priority"
        return self.db.frame(sql, params)

    def create_slot(self, platform, weekday, publish_time,
                    content_type=None, priority=100, notes=None):
        now = datetime.now().isoformat()
        return self.db.execute(
            """INSERT INTO publishing_slots(
                platform,weekday,publish_time,content_type,priority,notes,
                created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (platform,int(weekday),publish_time,content_type,int(priority),
             notes,now,now)
        )

    def create_item(self, values):
        now = datetime.now().isoformat()
        fields = [
            "title","platform","content_type","status",
            "production_project_id","pipeline_item_id","planned_publish_at",
            "scheduled_publish_at","timezone","score","confidence","rationale",
            "description_status","thumbnail_status","metadata_status",
            "upload_status","external_url","notes"
        ]
        data = [values.get(field) for field in fields]
        item_id = int(self.db.execute(
            f"""INSERT INTO publishing_items(
                {",".join(fields)},created_at,updated_at
            ) VALUES({",".join("?" for _ in fields)},?,?)""",
            (*data,now,now)
        ))
        self._log(item_id,"item_created",values)
        return item_id

    def item(self, item_id):
        frame = self.db.frame(
            """SELECT i.*,p.title AS production_title,p.status AS production_status,
               p.editor_id,p.expected_draft_at,p.actual_draft_at
               FROM publishing_items i
               LEFT JOIN production_projects p ON p.id=i.production_project_id
               WHERE i.id=?""",(int(item_id),)
        )
        if frame.empty:
            raise KeyError(item_id)
        return frame.iloc[0].to_dict()

    def items(self, status=None, platform=None):
        clauses, params = [], []
        if status and status != "All":
            clauses.append("i.status=?"); params.append(status)
        if platform and platform != "All":
            clauses.append("i.platform=?"); params.append(platform)
        sql = """SELECT i.id,i.title,i.platform,i.content_type,i.status,
                 p.title AS production_project,p.status AS production_status,
                 i.planned_publish_at,i.scheduled_publish_at,i.actual_publish_at,
                 i.score,i.confidence,i.description_status,i.thumbnail_status,
                 i.metadata_status,i.upload_status,i.external_url,i.updated_at
                 FROM publishing_items i
                 LEFT JOIN production_projects p ON p.id=i.production_project_id"""
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += """ ORDER BY
            CASE i.status WHEN 'Ready' THEN 1 WHEN 'Planned' THEN 2
                          WHEN 'Scheduled' THEN 3 ELSE 4 END,
            COALESCE(i.planned_publish_at,i.scheduled_publish_at,'9999-12-31')"""
        return self.db.frame(sql,params)

    def update_item(self, item_id, **changes):
        allowed = {
            "title","platform","content_type","status","production_project_id",
            "pipeline_item_id","planned_publish_at","scheduled_publish_at",
            "actual_publish_at","timezone","score","confidence","rationale",
            "description_status","thumbnail_status","metadata_status",
            "upload_status","external_url","notes"
        }
        values = {k:v for k,v in changes.items() if k in allowed}
        if not values:
            return self.item(item_id)
        old = self.item(item_id)
        if values.get("status") == "Published" and not values.get("actual_publish_at"):
            values["actual_publish_at"] = datetime.now().isoformat()
        values["updated_at"] = datetime.now().isoformat()
        columns = list(values)
        self.db.execute(
            "UPDATE publishing_items SET " +
            ",".join(f"{column}=?" for column in columns) +
            " WHERE id=?",
            [values[column] for column in columns] + [int(item_id)]
        )
        self._log(item_id,"item_updated",{"before":old,"changes":changes})
        self._notify_transition(item_id,old.get("status"),values.get("status"))
        return self.item(item_id)

    def add_dependency(self, item_id, dependency_type, label, due_at=None,
                       owner="Creator", source_record_type=None,
                       source_record_id=None, notes=None):
        now = datetime.now().isoformat()
        return self.db.execute(
            """INSERT INTO publishing_dependencies(
                publishing_item_id,dependency_type,label,due_at,owner,
                source_record_type,source_record_id,notes,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (int(item_id),dependency_type,label,due_at,owner,
             source_record_type,source_record_id,notes,now,now)
        )

    def dependencies(self, item_id, status=None):
        sql = """SELECT * FROM publishing_dependencies
                 WHERE publishing_item_id=?"""
        params = [int(item_id)]
        if status and status != "All":
            sql += " AND status=?"; params.append(status)
        sql += " ORDER BY COALESCE(due_at,'9999-12-31'),owner,label"
        return self.db.frame(sql,params)

    def resolve_dependency(self, dependency_id, status="Complete"):
        frame = self.db.frame(
            "SELECT * FROM publishing_dependencies WHERE id=?",
            (int(dependency_id),)
        )
        if frame.empty:
            raise KeyError(dependency_id)
        row = frame.iloc[0].to_dict()
        self.db.execute(
            """UPDATE publishing_dependencies SET status=?,updated_at=?
               WHERE id=?""",
            (status,datetime.now().isoformat(),int(dependency_id))
        )
        self._log(row["publishing_item_id"],"dependency_updated",{
            "dependency_id":dependency_id,"status":status
        })

    def synchronize_production(self):
        if not self.production_service:
            return 0
        projects = self.production_service.projects()
        created = 0
        for _, project in projects.iterrows():
            if project["status"] not in ("Final approved","Thumbnail","Scheduled"):
                continue
            exists = self.db.frame(
                """SELECT id FROM publishing_items
                   WHERE production_project_id=?""",(int(project["id"]),)
            )
            if not exists.empty:
                continue
            item_id = self.create_item({
                "title":project["title"],
                "platform":project["platform"] or "YouTube",
                "content_type":project["content_type"],
                "status":"Ready" if project["status"]=="Final approved" else "Planned",
                "production_project_id":int(project["id"]),
                "planned_publish_at":project["planned_publish_at"],
                "score":70,
                "confidence":0.7,
                "rationale":"Created from an approved production project.",
                "description_status":"Missing",
                "thumbnail_status":"Ready" if project["status"] in ("Thumbnail","Scheduled") else "Missing",
                "metadata_status":"Missing",
                "upload_status":"Not uploaded"
            })
            self.add_dependency(
                item_id,"Production","Final edit approved",
                owner="Editor",source_record_type="production_project",
                source_record_id=int(project["id"])
            )
            created += 1
        return created

    def suggest_next_slot(self, platform, content_type=None, after=None):
        after_dt = after or datetime.now()
        slots = self.slots(active_only=True)
        slots = slots[slots["platform"]==platform]
        if content_type:
            matching = slots[
                slots["content_type"].isna() |
                (slots["content_type"]==content_type)
            ]
            if not matching.empty:
                slots = matching
        if slots.empty:
            return after_dt + timedelta(days=1)

        candidates = []
        for day_offset in range(0,28):
            day = after_dt + timedelta(days=day_offset)
            weekday = day.weekday()
            for _, slot in slots[slots["weekday"]==weekday].iterrows():
                hour,minute = map(int,str(slot["publish_time"]).split(":")[:2])
                candidate = day.replace(hour=hour,minute=minute,second=0,microsecond=0)
                if candidate > after_dt:
                    candidates.append((candidate,int(slot["priority"])))
        if not candidates:
            return after_dt + timedelta(days=1)
        candidates.sort(key=lambda pair:(pair[0],pair[1]))
        return candidates[0][0]

    def auto_schedule_ready_items(self):
        items = self.items(status="Ready")
        scheduled = []
        occupied = set(
            self.items()["planned_publish_at"].dropna().astype(str).tolist()
        )
        cursor = datetime.now()
        for _, row in items.iterrows():
            slot = self.suggest_next_slot(
                row["platform"],row["content_type"],cursor
            )
            while slot.isoformat() in occupied:
                slot = self.suggest_next_slot(
                    row["platform"],row["content_type"],slot+timedelta(minutes=1)
                )
            self.update_item(
                int(row["id"]),status="Planned",
                planned_publish_at=slot.isoformat(),
                score=max(float(row["score"] or 0),75),
                confidence=max(float(row["confidence"] or 0),0.75),
                rationale="Placed into the next available recurring publishing slot."
            )
            occupied.add(slot.isoformat())
            cursor = slot
            scheduled.append(int(row["id"]))
        return scheduled

    def propagate_deadlines(self, item_id):
        item = self.item(item_id)
        planned = item.get("planned_publish_at") or item.get("scheduled_publish_at")
        if not planned:
            raise ValueError("Assign a publish date before generating deadlines.")
        publish_at = datetime.fromisoformat(str(planned))
        defaults = [
            ("Thumbnail","Thumbnail complete",publish_at-timedelta(days=2),"Creator"),
            ("Metadata","Title, description, and tags complete",publish_at-timedelta(days=1),"Creator"),
            ("Upload","Final file uploaded",publish_at-timedelta(hours=12),"Creator"),
            ("Review","Final scheduling check",publish_at-timedelta(hours=2),"Creator")
        ]
        existing = self.dependencies(item_id)
        labels = set(existing["label"].tolist()) if not existing.empty else set()
        created = 0
        for dep_type,label,due_at,owner in defaults:
            if label in labels:
                continue
            self.add_dependency(
                item_id,dep_type,label,due_at.isoformat(),owner
            )
            created += 1
        return created

    def record_performance(self, platform, content_type, published_at,
                           views=0, impressions=0, click_through_rate=None,
                           average_view_duration=None, retention_rate=None,
                           engagement_rate=None, subscribers_gained=0,
                           source_content_id=None):
        return self.db.execute(
            """INSERT INTO publishing_performance(
                platform,content_type,published_at,views,impressions,
                click_through_rate,average_view_duration,retention_rate,
                engagement_rate,subscribers_gained,source_content_id,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (platform,content_type,published_at,float(views),float(impressions),
             click_through_rate,average_view_duration,retention_rate,
             engagement_rate,float(subscribers_gained),source_content_id,
             datetime.now().isoformat())
        )

    def timing_insights(self, platform=None, content_type=None):
        clauses, params = [], []
        if platform:
            clauses.append("platform=?"); params.append(platform)
        if content_type:
            clauses.append("content_type=?"); params.append(content_type)
        sql = """SELECT *,
                 CAST(strftime('%w',published_at) AS INTEGER) AS weekday_sun0,
                 CAST(strftime('%H',published_at) AS INTEGER) AS publish_hour
                 FROM publishing_performance"""
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        frame = self.db.frame(sql,params)
        if frame.empty:
            return frame
        frame["quality_score"] = (
            frame["views"].fillna(0).apply(lambda v:math.log10(max(v,1))*15) +
            frame["retention_rate"].fillna(0)*40 +
            frame["engagement_rate"].fillna(0)*30 +
            frame["subscribers_gained"].fillna(0).apply(lambda v:min(v,20))
        )
        grouped = frame.groupby(
            ["platform","content_type","weekday_sun0","publish_hour"],
            dropna=False
        ).agg(
            uploads=("id","count"),
            average_views=("views","mean"),
            average_retention=("retention_rate","mean"),
            average_engagement=("engagement_rate","mean"),
            average_subscribers=("subscribers_gained","mean"),
            timing_score=("quality_score","mean")
        ).reset_index()
        return grouped.sort_values(
            ["timing_score","uploads"],ascending=[False,False]
        )

    def generate_recommendations(self):
        self.db.execute(
            """UPDATE publishing_recommendations SET status='Expired'
               WHERE status='Active'"""
        )
        generated = []
        now = datetime.now()
        items = self.items()

        for _, row in items.iterrows():
            item_id = int(row["id"])
            if row["status"] in ("Planned","Scheduled"):
                planned = row["planned_publish_at"] or row["scheduled_publish_at"]
                if planned:
                    planned_dt = datetime.fromisoformat(str(planned))
                    deps = self.dependencies(item_id,"Open")
                    overdue = deps[
                        deps["due_at"].notna() &
                        (deps["due_at"].astype(str) < now.isoformat())
                    ]
                    if not overdue.empty:
                        generated.append(self._recommend(
                            f"overdue:{item_id}",
                            "Dependency",
                            f'Finish prerequisites for "{row["title"]}"',
                            f'{len(overdue)} publishing dependencies are overdue.',
                            "Critical",95,item_id,None
                        ))
                    if planned_dt < now and row["status"] != "Published":
                        generated.append(self._recommend(
                            f"missed:{item_id}",
                            "Schedule",
                            f'Reschedule "{row["title"]}"',
                            "The planned publish time has passed.",
                            "Critical",100,item_id,None
                        ))
            if row["status"]=="Ready":
                generated.append(self._recommend(
                    f"ready:{item_id}",
                    "Schedule",
                    f'Schedule "{row["title"]}"',
                    "The final content is ready but has no publishing slot.",
                    "High",85,item_id,None
                ))
            if row["status"] in ("Planned","Scheduled"):
                missing = []
                for field,label in (
                    ("description_status","description"),
                    ("thumbnail_status","thumbnail"),
                    ("metadata_status","metadata"),
                    ("upload_status","upload")
                ):
                    if str(row[field]).lower() in ("missing","not uploaded"):
                        missing.append(label)
                if missing:
                    generated.append(self._recommend(
                        f"missing:{item_id}:{','.join(missing)}",
                        "Readiness",
                        f'Prepare "{row["title"]}"',
                        "Missing: " + ", ".join(missing) + ".",
                        "High",80,item_id,None
                    ))

        insights = self.timing_insights()
        if not insights.empty:
            for _, row in insights.head(3).iterrows():
                weekday = int(row["weekday_sun0"])
                weekday_name = ["Sunday","Monday","Tuesday","Wednesday",
                                "Thursday","Friday","Saturday"][weekday]
                generated.append(self._recommend(
                    f'timing:{row["platform"]}:{row["content_type"]}:{weekday}:{int(row["publish_hour"])}',
                    "Timing",
                    f'Prefer {weekday_name} at {int(row["publish_hour"]):02d}:00',
                    f'{row["platform"]} {row["content_type"]} posts perform best in this observed window.',
                    "Normal",float(row["timing_score"]),None,None
                ))
        return generated

    def recommendations(self, status="Active"):
        return self.db.frame(
            """SELECT * FROM publishing_recommendations
               WHERE status=? ORDER BY
               CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2
                             WHEN 'Normal' THEN 3 ELSE 4 END,
               score DESC,generated_at DESC""",(status,)
        )

    def calendar(self, start_at=None, days=30):
        start = start_at or datetime.now()
        end = start + timedelta(days=int(days))
        return self.db.frame(
            """SELECT i.id,i.title,i.platform,i.content_type,i.status,
               COALESCE(i.scheduled_publish_at,i.planned_publish_at) AS publish_at,
               i.thumbnail_status,i.description_status,i.metadata_status,
               i.upload_status,p.status AS production_status
               FROM publishing_items i
               LEFT JOIN production_projects p ON p.id=i.production_project_id
               WHERE COALESCE(i.scheduled_publish_at,i.planned_publish_at)
                     BETWEEN ? AND ?
               ORDER BY publish_at""",
            (start.isoformat(),end.isoformat())
        )

    def _recommend(self,key,kind,title,detail,priority,score,item_id,project_id):
        now = datetime.now().isoformat()
        self.db.execute(
            """INSERT OR REPLACE INTO publishing_recommendations(
                recommendation_key,recommendation_type,title,detail,priority,
                score,related_item_id,related_project_id,status,generated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (key,kind,title,detail,priority,float(score),item_id,project_id,
             "Active",now)
        )
        return {
            "recommendation_key":key,"recommendation_type":kind,
            "title":title,"detail":detail,"priority":priority,
            "score":float(score),"related_item_id":item_id,
            "related_project_id":project_id
        }

    def _notify_transition(self,item_id,old_status,new_status):
        if not self.notifications or not new_status or old_status==new_status:
            return
        item = self.item(item_id)
        level = "Success" if new_status in ("Scheduled","Published") else "Info"
        self.notifications.create(
            "Publishing",level,f'Publishing status: {new_status}',
            f'{item["title"]} moved from {old_status} to {new_status}.',
            "publishing_item",item_id
        )

    def _log(self,item_id,activity_type,detail=None):
        self.db.execute(
            """INSERT INTO publishing_activity(
                publishing_item_id,activity_type,detail_json,created_at
            ) VALUES(?,?,?,?)""",
            (item_id,activity_type,json.dumps(detail or {},default=str),
             datetime.now().isoformat())
        )
