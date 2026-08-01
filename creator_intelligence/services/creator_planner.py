from __future__ import annotations
from datetime import datetime, timedelta
import json
import math

SOURCE_TYPES = [
    "Stream VOD",
    "Highlight candidate",
    "Dedicated recording",
    "Imported video",
    "Highlight compilation"
]

DELIVERABLE_TYPES = [
    "Long-form VOD edit",
    "YouTube Short",
    "TikTok",
    "Highlight reel",
    "Standalone clip",
    "Dedicated video"
]

class CreatorPlannerService:
    def __init__(
        self,
        db,
        production_service=None,
        publishing_service=None,
        highlight_service=None,
        notifications=None
    ):
        self.db = db
        self.production_service = production_service
        self.publishing_service = publishing_service
        self.highlight_service = highlight_service
        self.notifications = notifications
        self._ensure_schema()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS content_sources(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL,
                platform TEXT,
                game_topic TEXT,
                stream_session_id INTEGER,
                highlight_candidate_id INTEGER,
                source_url TEXT,
                local_path TEXT,
                recorded_at TEXT,
                duration_seconds INTEGER,
                status TEXT DEFAULT 'Available',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS source_deliverables(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                deliverable_type TEXT NOT NULL,
                title TEXT NOT NULL,
                platform TEXT,
                start_seconds INTEGER,
                end_seconds INTEGER,
                confidence REAL DEFAULT 0,
                score REAL DEFAULT 0,
                status TEXT DEFAULT 'Suggested',
                production_project_id INTEGER,
                publishing_item_id INTEGER,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES content_sources(id),
                FOREIGN KEY(production_project_id) REFERENCES production_projects(id),
                FOREIGN KEY(publishing_item_id) REFERENCES publishing_items(id)
            )""",
            """CREATE TABLE IF NOT EXISTS creator_goals(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                metric TEXT NOT NULL,
                current_value REAL DEFAULT 0,
                target_value REAL NOT NULL,
                target_date TEXT,
                platform TEXT,
                status TEXT DEFAULT 'Active',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS creator_plan_actions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_key TEXT NOT NULL UNIQUE,
                action_type TEXT NOT NULL,
                title TEXT NOT NULL,
                reason TEXT NOT NULL,
                owner TEXT DEFAULT 'Creator',
                priority TEXT NOT NULL,
                score REAL NOT NULL,
                source_id INTEGER,
                deliverable_id INTEGER,
                production_project_id INTEGER,
                publishing_item_id INTEGER,
                status TEXT DEFAULT 'Active',
                due_at TEXT,
                generated_at TEXT NOT NULL,
                completed_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS creator_planner_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS source_performance(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                deliverable_id INTEGER,
                platform TEXT,
                views REAL DEFAULT 0,
                watch_hours REAL DEFAULT 0,
                engagement_rate REAL,
                retention_rate REAL,
                subscribers_gained REAL DEFAULT 0,
                revenue REAL DEFAULT 0,
                measured_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES content_sources(id),
                FOREIGN KEY(deliverable_id) REFERENCES source_deliverables(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_content_sources_type
               ON content_sources(source_type,recorded_at,status)""",
            """CREATE INDEX IF NOT EXISTS idx_source_deliverables_source
               ON source_deliverables(source_id,status,score)""",
            """CREATE INDEX IF NOT EXISTS idx_creator_actions
               ON creator_plan_actions(status,priority,score,due_at)"""
        ]
        for statement in statements:
            self.db.execute(statement)

    def create_source(self, values):
        now = datetime.now().isoformat()
        fields = [
            "source_type","title","platform","game_topic",
            "stream_session_id","highlight_candidate_id","source_url",
            "local_path","recorded_at","duration_seconds","status","notes"
        ]
        data = [values.get(field) for field in fields]
        return int(self.db.execute(
            f"""INSERT INTO content_sources(
                {",".join(fields)},created_at,updated_at
            ) VALUES({",".join("?" for _ in fields)},?,?)""",
            (*data,now,now)
        ))

    def create_vod_source(
        self,title,platform="Twitch",game_topic=None,
        stream_session_id=None,source_url=None,recorded_at=None,
        duration_seconds=None,notes=None
    ):
        return self.create_source({
            "source_type":"Stream VOD",
            "title":title,
            "platform":platform,
            "game_topic":game_topic,
            "stream_session_id":stream_session_id,
            "source_url":source_url,
            "recorded_at":recorded_at or datetime.now().isoformat(),
            "duration_seconds":duration_seconds,
            "status":"Available",
            "notes":notes
        })

    def create_dedicated_recording(
        self,title,game_topic=None,local_path=None,
        recorded_at=None,duration_seconds=None,notes=None
    ):
        return self.create_source({
            "source_type":"Dedicated recording",
            "title":title,
            "platform":"Local",
            "game_topic":game_topic,
            "local_path":local_path,
            "recorded_at":recorded_at or datetime.now().isoformat(),
            "duration_seconds":duration_seconds,
            "status":"Available",
            "notes":notes
        })

    def sources(self, source_type=None, status=None):
        clauses,params=[],[]
        if source_type and source_type!="All":
            clauses.append("s.source_type=?"); params.append(source_type)
        if status and status!="All":
            clauses.append("s.status=?"); params.append(status)
        sql = """SELECT s.id,s.source_type,s.title,s.platform,s.game_topic,
                 s.recorded_at,s.duration_seconds,s.status,s.source_url,
                 s.local_path,
                 COUNT(d.id) AS deliverable_count,
                 SUM(CASE WHEN d.production_project_id IS NOT NULL THEN 1 ELSE 0 END)
                    AS production_project_count,
                 SUM(CASE WHEN d.publishing_item_id IS NOT NULL THEN 1 ELSE 0 END)
                    AS publishing_item_count
                 FROM content_sources s
                 LEFT JOIN source_deliverables d ON d.source_id=s.id"""
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " GROUP BY s.id ORDER BY COALESCE(s.recorded_at,s.created_at) DESC"
        return self.db.frame(sql,params)

    def source(self, source_id):
        frame=self.db.frame(
            "SELECT * FROM content_sources WHERE id=?",(int(source_id),)
        )
        if frame.empty:
            raise KeyError(source_id)
        return frame.iloc[0].to_dict()

    def add_deliverable(
        self,source_id,deliverable_type,title,platform=None,
        start_seconds=None,end_seconds=None,confidence=0,score=0,
        status="Suggested",notes=None
    ):
        now=datetime.now().isoformat()
        return int(self.db.execute(
            """INSERT INTO source_deliverables(
                source_id,deliverable_type,title,platform,start_seconds,
                end_seconds,confidence,score,status,notes,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(source_id),deliverable_type,title,platform,start_seconds,
             end_seconds,float(confidence),float(score),status,notes,now,now)
        ))

    def deliverables(self, source_id=None, status=None):
        clauses,params=[],[]
        if source_id:
            clauses.append("d.source_id=?"); params.append(int(source_id))
        if status and status!="All":
            clauses.append("d.status=?"); params.append(status)
        sql = """SELECT d.id,d.source_id,s.title AS source_title,
                 s.source_type,d.deliverable_type,d.title,d.platform,
                 d.start_seconds,d.end_seconds,d.confidence,d.score,d.status,
                 d.production_project_id,d.publishing_item_id,d.updated_at
                 FROM source_deliverables d
                 JOIN content_sources s ON s.id=d.source_id"""
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY d.score DESC,d.created_at DESC"
        return self.db.frame(sql,params)

    def suggest_vod_deliverables(self, source_id):
        source=self.source(source_id)
        if source["source_type"]!="Stream VOD":
            raise ValueError("Automatic VOD deliverables require a Stream VOD source.")
        existing=self.deliverables(source_id)
        existing_types=set(existing["deliverable_type"].tolist()) if not existing.empty else set()
        duration=int(source.get("duration_seconds") or 0)
        suggestions=[]

        if "Long-form VOD edit" not in existing_types:
            suggestions.append(self.add_deliverable(
                source_id,"Long-form VOD edit",
                f'{source["title"]} — Edited Episode',
                platform="YouTube",
                confidence=0.9,score=90,
                notes="Primary edited-down VOD deliverable."
            ))

        short_count=3
        if duration >= 4*3600:
            short_count=5
        elif duration and duration < 90*60:
            short_count=2

        current_short_count=0
        if not existing.empty:
            current_short_count=int(
                (existing["deliverable_type"]=="YouTube Short").sum()
            )
        for number in range(current_short_count+1,short_count+1):
            suggestions.append(self.add_deliverable(
                source_id,"YouTube Short",
                f'{source["title"]} — Short {number}',
                platform="YouTube Shorts",
                confidence=0.55,score=60-number,
                notes="Timestamp should be replaced by a highlight candidate."
            ))

        if "TikTok" not in existing_types:
            suggestions.append(self.add_deliverable(
                source_id,"TikTok",
                f'{source["title"]} — TikTok cut',
                platform="TikTok",
                confidence=0.5,score=55
            ))
        return suggestions

    def import_highlight_candidate(
        self,source_id,candidate_id,title,start_seconds,end_seconds,
        score=0,confidence=0,platform="YouTube Shorts"
    ):
        return self.add_deliverable(
            source_id,"YouTube Short",title,platform,
            start_seconds,end_seconds,confidence,score,
            status="Suggested",
            notes=f"Imported from highlight candidate {candidate_id}."
        )

    def convert_deliverable_to_production(self, deliverable_id, editor_id=None):
        if not self.production_service:
            raise RuntimeError("Production service is unavailable.")
        frame=self.db.frame(
            """SELECT d.*,s.title AS source_title,s.source_type,
               s.source_url,s.local_path,s.game_topic
               FROM source_deliverables d
               JOIN content_sources s ON s.id=d.source_id
               WHERE d.id=?""",(int(deliverable_id),)
        )
        if frame.empty:
            raise KeyError(deliverable_id)
        row=frame.iloc[0].to_dict()
        if row.get("production_project_id"):
            return int(row["production_project_id"])

        content_type = (
            "Long-form" if row["deliverable_type"] in (
                "Long-form VOD edit","Dedicated video","Highlight reel"
            ) else "Short"
        )
        project_id=self.production_service.create_project({
            "title":row["title"],
            "series_name":row["source_title"],
            "platform":row["platform"] or "YouTube",
            "content_type":content_type,
            "game_topic":row.get("game_topic"),
            "status":"Assets ready",
            "priority":"High" if float(row.get("score") or 0)>=80 else "Normal",
            "editor_id":editor_id,
            "source_stream_id":str(row["source_id"]),
            "folder_url":row.get("source_url") or row.get("local_path"),
            "notes":(
                f'Source type: {row["source_type"]}. '
                f'Deliverable type: {row["deliverable_type"]}. '
                f'Timestamps: {row.get("start_seconds")}–{row.get("end_seconds")}.'
            )
        })
        location=row.get("source_url") or row.get("local_path")
        self.production_service.add_asset(
            project_id,
            "Raw footage" if row["source_type"]!="Stream VOD" else "Stream VOD",
            row["source_title"],
            status="Available" if location else "Missing",
            location=location,
            notes="Automatically linked from Creator Planner."
        )
        self.db.execute(
            """UPDATE source_deliverables SET production_project_id=?,
               status='In production',updated_at=? WHERE id=?""",
            (project_id,datetime.now().isoformat(),int(deliverable_id))
        )
        return int(project_id)

    def create_goal(
        self,name,metric,target_value,current_value=0,
        target_date=None,platform=None,notes=None
    ):
        now=datetime.now().isoformat()
        return int(self.db.execute(
            """INSERT INTO creator_goals(
                name,metric,current_value,target_value,target_date,platform,
                notes,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (name,metric,float(current_value),float(target_value),target_date,
             platform,notes,now,now)
        ))

    def goals(self,status="Active"):
        return self.db.frame(
            """SELECT *,
               CASE WHEN target_value=0 THEN 0
                    ELSE ROUND(current_value/target_value*100,1) END
                    AS progress_percent
               FROM creator_goals WHERE status=?
               ORDER BY target_date,name""",(status,)
        )

    def record_source_performance(
        self,source_id,deliverable_id=None,platform=None,views=0,
        watch_hours=0,engagement_rate=None,retention_rate=None,
        subscribers_gained=0,revenue=0,measured_at=None
    ):
        now=datetime.now().isoformat()
        return self.db.execute(
            """INSERT INTO source_performance(
                source_id,deliverable_id,platform,views,watch_hours,
                engagement_rate,retention_rate,subscribers_gained,revenue,
                measured_at,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (int(source_id),deliverable_id,platform,float(views),
             float(watch_hours),engagement_rate,retention_rate,
             float(subscribers_gained),float(revenue),
             measured_at or now,now)
        )

    def source_yield(self):
        return self.db.frame("""
            SELECT s.id,s.title,s.source_type,s.game_topic,s.recorded_at,
                   COUNT(DISTINCT d.id) AS deliverables_created,
                   COUNT(DISTINCT d.production_project_id) AS projects_created,
                   COUNT(DISTINCT d.publishing_item_id) AS published_items,
                   COALESCE(SUM(p.views),0) AS total_views,
                   COALESCE(SUM(p.watch_hours),0) AS total_watch_hours,
                   COALESCE(SUM(p.subscribers_gained),0) AS subscribers_gained,
                   COALESCE(SUM(p.revenue),0) AS revenue
            FROM content_sources s
            LEFT JOIN source_deliverables d ON d.source_id=s.id
            LEFT JOIN source_performance p ON p.source_id=s.id
            GROUP BY s.id
            ORDER BY total_views DESC,deliverables_created DESC
        """)

    def generate_daily_plan(self):
        now=datetime.now()
        self.db.execute(
            """UPDATE creator_plan_actions SET status='Expired'
               WHERE status='Active'"""
        )
        generated=[]

        production = (
            self.production_service.projects()
            if self.production_service else None
        )
        publishing = (
            self.publishing_service.items()
            if self.publishing_service else None
        )

        if production is not None and not production.empty:
            review=production[production["status"]=="Ready for review"]
            for _,row in review.head(4).iterrows():
                generated.append(self._action(
                    f'review:{int(row["id"])}',"Review",
                    f'Review "{row["title"]}"',
                    "Your editor delivered a draft and the project is waiting on you.",
                    "Creator","Critical",100,
                    production_project_id=int(row["id"])
                ))

            missing_assets=production[
                production["status"].isin(["Planning","Recorded"])
            ]
            for _,row in missing_assets.head(3).iterrows():
                generated.append(self._action(
                    f'assets:{int(row["id"])}',"Assets",
                    f'Prepare assets for "{row["title"]}"',
                    "The project cannot move to the editor until source files are ready.",
                    "Creator","High",82,
                    production_project_id=int(row["id"])
                ))

            active_editor=int(
                production["status"].isin([
                    "Sent to editor","Editing","Revision requested"
                ]).sum()
            )
        else:
            active_editor=0

        if publishing is not None and not publishing.empty:
            ready=publishing[publishing["status"]=="Ready"]
            for _,row in ready.head(3).iterrows():
                generated.append(self._action(
                    f'schedule:{int(row["id"])}',"Publish",
                    f'Schedule "{row["title"]}"',
                    "The content is ready but does not have a release slot.",
                    "Creator","High",88,
                    publishing_item_id=int(row["id"])
                ))
            planned=publishing[
                publishing["status"].isin(["Planned","Scheduled"])
            ]
            for _,row in planned.head(5).iterrows():
                planned_at=row["planned_publish_at"] or row["scheduled_publish_at"]
                if planned_at and str(planned_at)[:10] == now.date().isoformat():
                    generated.append(self._action(
                        f'publish-today:{int(row["id"])}',"Publish",
                        f'Publish "{row["title"]}" today',
                        "This item is on today's publishing calendar.",
                        "Creator","Critical",98,
                        publishing_item_id=int(row["id"]),
                        due_at=str(planned_at)
                    ))

        available=self.sources(status="Available")
        unprocessed=[]
        for _,source in available.iterrows():
            ds=self.deliverables(int(source["id"]))
            if ds.empty:
                unprocessed.append(source)

        if active_editor >= 5:
            generated.append(self._action(
                "backlog:editor-high","Capacity",
                "Do not create another long-form edit today",
                f"The editor queue already contains {active_editor} active projects.",
                "Creator","High",90
            ))
            for source in unprocessed[:2]:
                generated.append(self._action(
                    f'shorts:{int(source["id"])}',"Content",
                    f'Extract Shorts from "{source["title"]}"',
                    "Short-form deliverables add output without another full long-form edit.",
                    "Creator","Normal",70,source_id=int(source["id"])
                ))
        else:
            for source in unprocessed[:3]:
                source_id=int(source["id"])
                action_title=(
                    f'Create deliverables from "{source["title"]}"'
                    if source["source_type"]=="Stream VOD"
                    else f'Create a production project for "{source["title"]}"'
                )
                reason=(
                    "This VOD has not been converted into long-form or short-form opportunities."
                    if source["source_type"]=="Stream VOD"
                    else "This dedicated recording has not entered the production pipeline."
                )
                generated.append(self._action(
                    f'process-source:{source_id}',"Content",
                    action_title,reason,"Creator","High",84,
                    source_id=source_id
                ))

        yield_frame=self.source_yield()
        if not yield_frame.empty and float(yield_frame["total_views"].max() or 0)>0:
            top=yield_frame.iloc[0]
            generated.append(self._action(
                f'opportunity:{int(top["id"])}',"Opportunity",
                f'Create more content like "{top["title"]}"',
                f'This source generated {int(top["total_views"]):,} tracked views.',
                "Creator","Normal",75,source_id=int(top["id"])
            ))

        summary=self.command_center()
        self.db.execute(
            """INSERT INTO creator_planner_snapshots(
                snapshot_date,summary_json,created_at
            ) VALUES(?,?,?)""",
            (now.date().isoformat(),json.dumps(summary,default=str),
             now.isoformat())
        )
        return generated

    def actions(self,status="Active"):
        return self.db.frame(
            """SELECT * FROM creator_plan_actions
               WHERE status=? ORDER BY
               CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2
                             WHEN 'Normal' THEN 3 ELSE 4 END,
               score DESC,COALESCE(due_at,'9999-12-31')""",(status,)
        )

    def complete_action(self,action_id):
        self.db.execute(
            """UPDATE creator_plan_actions SET status='Completed',
               completed_at=? WHERE id=?""",
            (datetime.now().isoformat(),int(action_id))
        )

    def command_center(self):
        production=self.production_service.projects() if self.production_service else None
        publishing=self.publishing_service.items() if self.publishing_service else None
        sources=self.sources()
        deliverables=self.deliverables()

        production_counts={}
        if production is not None and not production.empty:
            production_counts=production["status"].value_counts().to_dict()

        publishing_counts={}
        if publishing is not None and not publishing.empty:
            publishing_counts=publishing["status"].value_counts().to_dict()

        return {
            "available_sources":int(
                (sources["status"]=="Available").sum()
            ) if not sources.empty else 0,
            "stream_vods":int(
                (sources["source_type"]=="Stream VOD").sum()
            ) if not sources.empty else 0,
            "dedicated_recordings":int(
                (sources["source_type"]=="Dedicated recording").sum()
            ) if not sources.empty else 0,
            "suggested_deliverables":int(
                (deliverables["status"]=="Suggested").sum()
            ) if not deliverables.empty else 0,
            "waiting_on_editor":int(
                sum(production_counts.get(x,0) for x in [
                    "Sent to editor","Editing","Revision requested"
                ])
            ),
            "waiting_on_creator_review":int(
                production_counts.get("Ready for review",0)
            ),
            "ready_to_schedule":int(
                publishing_counts.get("Ready",0)
            ),
            "scheduled":int(
                publishing_counts.get("Scheduled",0)
            )
        }

    def if_i_were_you(self):
        actions=self.actions()
        if actions.empty:
            return ["Generate a daily plan to receive prioritized guidance."]
        return [
            f'{idx+1}. {row["title"]} — {row["reason"]}'
            for idx,(_,row) in enumerate(actions.head(5).iterrows())
        ]

    def _action(
        self,key,action_type,title,reason,owner,priority,score,
        source_id=None,deliverable_id=None,production_project_id=None,
        publishing_item_id=None,due_at=None
    ):
        now=datetime.now().isoformat()
        self.db.execute(
            """INSERT OR REPLACE INTO creator_plan_actions(
                action_key,action_type,title,reason,owner,priority,score,
                source_id,deliverable_id,production_project_id,
                publishing_item_id,status,due_at,generated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (key,action_type,title,reason,owner,priority,float(score),
             source_id,deliverable_id,production_project_id,
             publishing_item_id,"Active",due_at,now)
        )
        return {
            "action_key":key,"action_type":action_type,"title":title,
            "reason":reason,"owner":owner,"priority":priority,
            "score":float(score),"source_id":source_id,
            "deliverable_id":deliverable_id,
            "production_project_id":production_project_id,
            "publishing_item_id":publishing_item_id,"due_at":due_at
        }
