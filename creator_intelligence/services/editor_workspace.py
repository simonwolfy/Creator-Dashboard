from __future__ import annotations
from datetime import datetime
import json

class EditorWorkspaceService:
    def __init__(
        self, db, production_service=None, scoring_service=None,
        recommendation_service=None, transcript_service=None,
        scene_service=None, notifications=None
    ):
        self.db = db
        self.production_service = production_service
        self.scoring_service = scoring_service
        self.recommendation_service = recommendation_service
        self.transcript_service = transcript_service
        self.scene_service = scene_service
        self.notifications = notifications
        self._ensure_schema()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS editor_workspace_projects(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                production_project_id INTEGER NOT NULL UNIQUE,
                editor_id INTEGER,
                workspace_status TEXT DEFAULT 'Queued',
                queue_rank INTEGER DEFAULT 100,
                estimated_hours REAL DEFAULT 0,
                completed_hours REAL DEFAULT 0,
                source_vod_title TEXT,
                source_vod_url TEXT,
                transcript_id INTEGER,
                briefing_status TEXT DEFAULT 'Not generated',
                packet_status TEXT DEFAULT 'Not generated',
                editor_acknowledged INTEGER DEFAULT 0,
                editor_started_at TEXT,
                editor_completed_at TEXT,
                creator_reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS editor_briefs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_project_id INTEGER NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                objective TEXT,
                summary TEXT,
                editing_style TEXT,
                pacing TEXT,
                target_duration_seconds INTEGER,
                hook_notes TEXT,
                ending_notes TEXT,
                avoid_notes TEXT,
                required_elements_json TEXT,
                highlight_ids_json TEXT,
                chapter_ids_json TEXT,
                asset_checklist_json TEXT,
                generated_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(workspace_project_id,version)
            )""",
            """CREATE TABLE IF NOT EXISTS editor_brief_moments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_id INTEGER NOT NULL,
                moment_index INTEGER NOT NULL,
                start_seconds REAL NOT NULL,
                peak_seconds REAL,
                end_seconds REAL NOT NULL,
                title TEXT NOT NULL,
                category TEXT,
                score REAL,
                confidence REAL,
                role TEXT,
                instruction TEXT,
                source_highlight_id INTEGER,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS editor_workspace_notes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_project_id INTEGER NOT NULL,
                note_type TEXT NOT NULL,
                timestamp_seconds REAL,
                author_role TEXT NOT NULL,
                author_name TEXT,
                body TEXT NOT NULL,
                status TEXT DEFAULT 'Open',
                priority TEXT DEFAULT 'Normal',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS editor_workspace_checklist(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_project_id INTEGER NOT NULL,
                section TEXT NOT NULL,
                item TEXT NOT NULL,
                owner TEXT DEFAULT 'Editor',
                status TEXT DEFAULT 'Open',
                due_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS editor_workspace_activity(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_project_id INTEGER,
                action_type TEXT NOT NULL,
                detail_json TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_editor_workspace_queue
               ON editor_workspace_projects(workspace_status,queue_rank,updated_at)""",
            """CREATE INDEX IF NOT EXISTS idx_editor_brief_moments
               ON editor_brief_moments(brief_id,moment_index)""",
            """CREATE INDEX IF NOT EXISTS idx_editor_workspace_notes
               ON editor_workspace_notes(workspace_project_id,status,timestamp_seconds)"""
        ]
        for statement in statements:
            self.db.execute(statement)

    def sync_from_production(self):
        if not self.production_service:
            return 0
        projects = self.production_service.projects()
        created = 0
        active_statuses = {
            "Assets ready","Sent to editor","Editing",
            "Ready for review","Revision requested"
        }
        for _,row in projects.iterrows():
            if row["status"] not in active_statuses:
                continue
            exists = self.db.frame(
                """SELECT id FROM editor_workspace_projects
                   WHERE production_project_id=?""",(int(row["id"]),)
            )
            if not exists.empty:
                continue
            now = datetime.now().isoformat()
            workspace_status = {
                "Assets ready":"Queued",
                "Sent to editor":"Assigned",
                "Editing":"Editing",
                "Ready for review":"Ready for creator review",
                "Revision requested":"Revision"
            }.get(row["status"],"Queued")
            self.db.execute(
                """INSERT INTO editor_workspace_projects(
                    production_project_id,workspace_status,queue_rank,
                    source_vod_title,source_vod_url,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    int(row["id"]),workspace_status,
                    self._priority_rank(row.get("priority")),
                    row.get("series_name") or row.get("title"),
                    row.get("folder_url"),now,now
                )
            )
            created += 1
        return created

    def _priority_rank(self, priority):
        return {
            "Critical":10,"High":25,"Normal":50,"Low":80
        }.get(str(priority),50)

    def workspace_project(self, workspace_id):
        frame = self.db.frame(
            """SELECT w.*,p.title,p.series_name,p.content_type,p.platform,
               p.game_topic,p.priority,p.status AS production_status,
               p.progress_percent,p.expected_draft_at,p.revision_count,
               p.folder_url,e.name AS editor_name
               FROM editor_workspace_projects w
               JOIN production_projects p ON p.id=w.production_project_id
               LEFT JOIN editors e ON e.id=p.editor_id
               WHERE w.id=?""",(int(workspace_id),)
        )
        if frame.empty:
            raise KeyError(workspace_id)
        return frame.iloc[0].to_dict()

    def queue(self, editor_id=None):
        clauses,params=[],[]
        if editor_id:
            clauses.append("p.editor_id=?")
            params.append(int(editor_id))
        sql = """SELECT w.id,w.production_project_id,p.title,p.series_name,
                 p.content_type,p.platform,p.game_topic,p.priority,
                 w.workspace_status,e.name AS editor,w.queue_rank,
                 w.estimated_hours,w.completed_hours,p.progress_percent,
                 p.expected_draft_at,p.revision_count,w.briefing_status,
                 w.packet_status,w.editor_acknowledged,w.updated_at
                 FROM editor_workspace_projects w
                 JOIN production_projects p ON p.id=w.production_project_id
                 LEFT JOIN editors e ON e.id=p.editor_id"""
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += """ ORDER BY
            CASE w.workspace_status
              WHEN 'Revision' THEN 1
              WHEN 'Assigned' THEN 2
              WHEN 'Editing' THEN 3
              WHEN 'Queued' THEN 4
              WHEN 'Ready for creator review' THEN 5
              ELSE 6 END,
            w.queue_rank,p.expected_draft_at,w.updated_at"""
        return self.db.frame(sql,params)

    def assign_editor(self, workspace_id, editor_id):
        workspace = self.workspace_project(workspace_id)
        if self.production_service:
            self.production_service.assign_editor(
                workspace["production_project_id"],editor_id
            )
        self.db.execute(
            """UPDATE editor_workspace_projects SET editor_id=?,
               workspace_status='Assigned',updated_at=? WHERE id=?""",
            (int(editor_id),datetime.now().isoformat(),int(workspace_id))
        )
        self._log(workspace_id,"editor_assigned",{"editor_id":editor_id})
        return self.workspace_project(workspace_id)

    def acknowledge(self, workspace_id):
        self.db.execute(
            """UPDATE editor_workspace_projects SET editor_acknowledged=1,
               workspace_status=CASE WHEN workspace_status='Queued'
                   THEN 'Assigned' ELSE workspace_status END,
               updated_at=? WHERE id=?""",
            (datetime.now().isoformat(),int(workspace_id))
        )
        self._log(workspace_id,"editor_acknowledged",{})
        return self.workspace_project(workspace_id)

    def start_editing(self, workspace_id):
        workspace = self.workspace_project(workspace_id)
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE editor_workspace_projects SET workspace_status='Editing',
               editor_started_at=COALESCE(editor_started_at,?),
               updated_at=? WHERE id=?""",
            (now,now,int(workspace_id))
        )
        if self.production_service:
            self.production_service.update_project(
                workspace["production_project_id"],
                status="Editing",progress_percent=max(
                    40,int(workspace.get("progress_percent") or 0)
                )
            )
        self._log(workspace_id,"editing_started",{})
        return self.workspace_project(workspace_id)

    def mark_ready_for_review(self, workspace_id, completed_hours=None):
        workspace = self.workspace_project(workspace_id)
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE editor_workspace_projects
               SET workspace_status='Ready for creator review',
                   editor_completed_at=?,completed_hours=COALESCE(?,completed_hours),
                   updated_at=? WHERE id=?""",
            (now,completed_hours,now,int(workspace_id))
        )
        if self.production_service:
            self.production_service.update_project(
                workspace["production_project_id"],
                status="Ready for review",progress_percent=75
            )
        self._log(workspace_id,"ready_for_review",{
            "completed_hours":completed_hours
        })
        if self.notifications:
            self.notifications.create(
                "Production","Success","Editor draft ready",
                f'{workspace["title"]} is ready for creator review.',
                "production_project",workspace["production_project_id"]
            )
        return self.workspace_project(workspace_id)

    def generate_brief(
        self, workspace_id, transcript_id=None, target_duration_seconds=None
    ):
        workspace = self.workspace_project(workspace_id)
        highlights = self._project_highlights(workspace)
        scenes = self._top_scenes(transcript_id)
        now = datetime.now().isoformat()
        existing = self.db.frame(
            """SELECT MAX(version) AS max_version FROM editor_briefs
               WHERE workspace_project_id=?""",(int(workspace_id),)
        )
        max_version = existing.iloc[0]["max_version"]
        version = int(max_version)+1 if max_version is not None else 1

        content_type = str(workspace.get("content_type") or "")
        if target_duration_seconds is None:
            target_duration_seconds = 60 if "Short" in content_type else 1200

        objective = (
            "Create a fast, self-contained vertical clip with an immediate hook."
            if "Short" in content_type
            else "Create an edited-down VOD episode focused on progression and strong moments."
        )
        pacing = "Fast" if "Short" in content_type else "Moderate with fast highlight pacing"
        required = [
            "Open with the strongest moment or a concise setup.",
            "Remove dead air, AFK time, menus, and unnecessary repetition.",
            "Keep enough context for the payoff to make sense.",
            "Preserve strong reactions and community moments.",
        ]
        avoid = (
            "Avoid extended inventory management, loading, AFK sections, "
            "and repeated explanations unless they are necessary context."
        )

        brief_id = int(self.db.execute(
            """INSERT INTO editor_briefs(
                workspace_project_id,version,objective,summary,editing_style,
                pacing,target_duration_seconds,hook_notes,ending_notes,
                avoid_notes,required_elements_json,highlight_ids_json,
                chapter_ids_json,asset_checklist_json,generated_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(workspace_id),version,objective,
                self._summary_text(workspace,highlights,scenes),
                "Creator-focused gaming edit",pacing,int(target_duration_seconds),
                self._hook_note(highlights),
                self._ending_note(highlights,scenes),
                avoid,json.dumps(required),
                json.dumps([int(x["id"]) for x in highlights]),
                json.dumps([]),
                json.dumps(self._asset_checklist(workspace["production_project_id"])),
                now,now
            )
        ))

        moments = self._brief_moments(highlights,scenes)
        for index,moment in enumerate(moments):
            self.db.execute(
                """INSERT INTO editor_brief_moments(
                    brief_id,moment_index,start_seconds,peak_seconds,end_seconds,
                    title,category,score,confidence,role,instruction,
                    source_highlight_id,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    brief_id,index,moment["start_seconds"],
                    moment.get("peak_seconds"),moment["end_seconds"],
                    moment["title"],moment.get("category"),
                    moment.get("score"),moment.get("confidence"),
                    moment.get("role"),moment.get("instruction"),
                    moment.get("source_highlight_id"),now
                )
            )

        self.db.execute(
            """UPDATE editor_workspace_projects SET briefing_status='Generated',
               transcript_id=COALESCE(?,transcript_id),estimated_hours=?,
               updated_at=? WHERE id=?""",
            (
                transcript_id,self._estimate_hours(workspace,moments),
                now,int(workspace_id)
            )
        )
        self._seed_checklist(workspace_id)
        self._log(workspace_id,"brief_generated",{
            "brief_id":brief_id,"version":version,
            "moment_count":len(moments)
        })
        return self.brief(brief_id)

    def _project_highlights(self, workspace):
        if not self.scoring_service:
            return []
        frame = self.scoring_service.highlights()
        if frame.empty:
            return []
        project_id = int(workspace["production_project_id"])
        linked = frame[frame["production_project_id"]==project_id]
        if linked.empty:
            linked = frame[
                frame["review_status"].isin(["Approved","Needs changes"])
            ].head(12)
        return linked.to_dict("records")

    def _top_scenes(self, transcript_id):
        if not transcript_id or not self.scene_service:
            return []
        frame = self.scene_service.scene_segments(transcript_id)
        if frame.empty:
            return []
        return frame.sort_values(
            "content_value_score",ascending=False
        ).head(10).to_dict("records")

    def _summary_text(self, workspace, highlights, scenes):
        return (
            f'Project: {workspace["title"]}. '
            f'Format: {workspace.get("content_type") or "Video"}. '
            f'Game/topic: {workspace.get("game_topic") or "Unspecified"}. '
            f'{len(highlights)} scored highlights and '
            f'{len(scenes)} high-value transcript scenes are available.'
        )

    def _hook_note(self, highlights):
        if not highlights:
            return "Use the strongest available reaction or result in the first 5–10 seconds."
        top = sorted(
            highlights,
            key=lambda x:float(x.get("effective_score") or x.get("score") or 0),
            reverse=True
        )[0]
        return (
            f'Lead with "{top["title"]}" near '
            f'{self.format_time(top["peak_seconds"])}.'
        )

    def _ending_note(self, highlights, scenes):
        if highlights:
            latest = max(highlights,key=lambda x:float(x["end_seconds"]))
            return (
                f'End after the payoff near '
                f'{self.format_time(latest["end_seconds"])}.'
            )
        if scenes:
            latest = max(scenes,key=lambda x:float(x["end_seconds"]))
            return f'End after "{latest["title"]}".'
        return "End on a clear payoff or next-episode setup."

    def _asset_checklist(self, production_project_id):
        if not self.production_service:
            return []
        assets = self.production_service.assets(production_project_id)
        return [
            {
                "label":row["label"],
                "type":row["asset_type"],
                "status":row["status"],
                "location":row["location"]
            }
            for _,row in assets.iterrows()
        ]

    def _brief_moments(self, highlights, scenes):
        moments = []
        for row in highlights[:12]:
            moments.append({
                "start_seconds":float(
                    row.get("recommended_short_start")
                    if "Short" in str(row.get("recommended_output"))
                    else row.get("recommended_long_start")
                    or row["start_seconds"]
                ),
                "peak_seconds":float(row["peak_seconds"]),
                "end_seconds":float(
                    row.get("recommended_short_end")
                    if "Short" in str(row.get("recommended_output"))
                    else row.get("recommended_long_end")
                    or row["end_seconds"]
                ),
                "title":row["title"],
                "category":row.get("primary_category"),
                "score":float(row.get("effective_score") or row.get("score") or 0),
                "confidence":float(row.get("confidence") or 0),
                "role":"Primary highlight",
                "instruction":(
                    f'Prioritize this moment for {row.get("recommended_output")}.'
                ),
                "source_highlight_id":int(row["id"])
            })
        if not moments:
            for row in scenes[:8]:
                moments.append({
                    "start_seconds":float(row["start_seconds"]),
                    "peak_seconds":(
                        float(row["start_seconds"])+float(row["end_seconds"])
                    )/2,
                    "end_seconds":float(row["end_seconds"]),
                    "title":row["title"],
                    "category":row["segment_type"],
                    "score":float(row["content_value_score"]),
                    "confidence":float(row["confidence"]),
                    "role":"High-value scene",
                    "instruction":"Use as a candidate story or progression section.",
                    "source_highlight_id":None
                })
        return sorted(moments,key=lambda x:x["start_seconds"])

    def _estimate_hours(self, workspace, moments):
        content_type = str(workspace.get("content_type") or "")
        base = 0.75 if "Short" in content_type else 2.5
        complexity = len(moments)*0.12
        revision = int(workspace.get("revision_count") or 0)*0.5
        return round(base+complexity+revision,2)

    def brief(self, brief_id):
        frame = self.db.frame(
            "SELECT * FROM editor_briefs WHERE id=?",(int(brief_id),)
        )
        if frame.empty:
            raise KeyError(brief_id)
        return frame.iloc[0].to_dict()

    def latest_brief(self, workspace_id):
        frame = self.db.frame(
            """SELECT * FROM editor_briefs
               WHERE workspace_project_id=?
               ORDER BY version DESC LIMIT 1""",(int(workspace_id),)
        )
        return frame.iloc[0].to_dict() if not frame.empty else None

    def brief_moments(self, brief_id):
        return self.db.frame(
            """SELECT * FROM editor_brief_moments
               WHERE brief_id=? ORDER BY moment_index""",(int(brief_id),)
        )

    def add_note(
        self, workspace_id, body, note_type="General",
        timestamp_seconds=None, author_role="Creator",
        author_name=None, priority="Normal"
    ):
        now = datetime.now().isoformat()
        note_id = int(self.db.execute(
            """INSERT INTO editor_workspace_notes(
                workspace_project_id,note_type,timestamp_seconds,author_role,
                author_name,body,status,priority,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                int(workspace_id),note_type,timestamp_seconds,author_role,
                author_name,body,"Open",priority,now
            )
        ))
        self._log(workspace_id,"note_added",{"note_id":note_id})
        return note_id

    def notes(self, workspace_id, status=None):
        sql = """SELECT * FROM editor_workspace_notes
                 WHERE workspace_project_id=?"""
        params = [int(workspace_id)]
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 ELSE 3 END,COALESCE(timestamp_seconds,999999),created_at"
        return self.db.frame(sql,params)

    def resolve_note(self, note_id):
        frame = self.db.frame(
            "SELECT * FROM editor_workspace_notes WHERE id=?",(int(note_id),)
        )
        if frame.empty:
            raise KeyError(note_id)
        workspace_id = int(frame.iloc[0]["workspace_project_id"])
        self.db.execute(
            """UPDATE editor_workspace_notes SET status='Resolved',
               resolved_at=? WHERE id=?""",
            (datetime.now().isoformat(),int(note_id))
        )
        self._log(workspace_id,"note_resolved",{"note_id":note_id})

    def checklist(self, workspace_id):
        return self.db.frame(
            """SELECT * FROM editor_workspace_checklist
               WHERE workspace_project_id=?
               ORDER BY section,id""",(int(workspace_id),)
        )

    def _seed_checklist(self, workspace_id):
        existing = self.checklist(workspace_id)
        if not existing.empty:
            return
        items = [
            ("Setup","Open source VOD and confirm audio tracks","Editor"),
            ("Setup","Review AI brief and highlight timestamps","Editor"),
            ("Edit","Build rough cut","Editor"),
            ("Edit","Remove dead air and repetitive sections","Editor"),
            ("Edit","Add captions/zooms where appropriate","Editor"),
            ("Delivery","Export draft and upload version","Editor"),
            ("Review","Creator reviews draft","Creator"),
            ("Revision","Resolve open timestamp notes","Editor"),
        ]
        now = datetime.now().isoformat()
        for section,item,owner in items:
            self.db.execute(
                """INSERT INTO editor_workspace_checklist(
                    workspace_project_id,section,item,owner,status,created_at
                ) VALUES(?,?,?,?,?,?)""",
                (int(workspace_id),section,item,owner,"Open",now)
            )

    def set_checklist_status(self, checklist_id, status):
        if status not in {"Open","In progress","Complete","Skipped"}:
            raise ValueError(status)
        completed = datetime.now().isoformat() if status=="Complete" else None
        self.db.execute(
            """UPDATE editor_workspace_checklist SET status=?,
               completed_at=? WHERE id=?""",
            (status,completed,int(checklist_id))
        )

    def dashboard(self):
        queue = self.queue()
        counts = queue["workspace_status"].value_counts().to_dict() if not queue.empty else {}
        estimated = float(queue["estimated_hours"].sum()) if not queue.empty else 0
        completed = float(queue["completed_hours"].sum()) if not queue.empty else 0
        return {
            "queued":int(counts.get("Queued",0)),
            "assigned":int(counts.get("Assigned",0)),
            "editing":int(counts.get("Editing",0)),
            "ready_for_review":int(counts.get("Ready for creator review",0)),
            "revision":int(counts.get("Revision",0)),
            "estimated_hours":round(estimated,2),
            "completed_hours":round(completed,2),
            "open_notes":int(
                self.db.frame(
                    """SELECT COUNT(*) AS c FROM editor_workspace_notes
                       WHERE status='Open'"""
                ).iloc[0]["c"]
            )
        }

    def editor_packet_data(self, workspace_id):
        workspace = self.workspace_project(workspace_id)
        brief = self.latest_brief(workspace_id)
        moments = (
            self.brief_moments(brief["id"]).to_dict("records")
            if brief else []
        )
        return {
            "workspace":workspace,
            "brief":brief,
            "moments":moments,
            "notes":self.notes(workspace_id).to_dict("records"),
            "checklist":self.checklist(workspace_id).to_dict("records"),
            "assets":(
                self.production_service.assets(
                    workspace["production_project_id"]
                ).to_dict("records")
                if self.production_service else []
            )
        }

    @staticmethod
    def format_time(seconds):
        seconds = int(float(seconds or 0))
        hours,remaining = divmod(seconds,3600)
        minutes,secs = divmod(remaining,60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _log(self, workspace_id, action_type, detail=None):
        self.db.execute(
            """INSERT INTO editor_workspace_activity(
                workspace_project_id,action_type,detail_json,created_at
            ) VALUES(?,?,?,?)""",
            (
                workspace_id,action_type,
                json.dumps(detail or {},default=str),
                datetime.now().isoformat()
            )
        )
